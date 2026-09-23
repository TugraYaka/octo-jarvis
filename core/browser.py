import atexit
import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

MAX_TEXT_CHARS = 4000
MAX_LINKS = 20
NAV_TIMEOUT_MS = 15_000
LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "search.log")

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"ignore (all |any )?(previous|prior|above) instructions",
        r"disregard (all |any )?(previous|prior|above)",
        r"\byou are now\b",
        r"new instructions?:",
        r"system prompt",
        r"reveal your (instructions|prompt|rules)",
        r"\bact as (an?|the) ",
        r"\bjailbreak\b",
        r"\bdan mode\b",
        r"\bdo anything now\b",
    )
]


def _looks_like_injection(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION_PATTERNS)


_CHALLENGE_TITLES = ("just a moment", "attention required", "checking your browser", "access denied")


def _looks_like_challenge(title: str) -> bool:
    title = (title or "").lower()
    return any(t in title for t in _CHALLENGE_TITLES)


def _log(message: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{message}\n")
    except OSError:
        pass


class BlockedURLError(Exception):
    pass


def _assert_url_allowed(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BlockedURLError(f"Scheme not allowed: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise BlockedURLError("No hostname in URL")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise BlockedURLError(f"Could not resolve host: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise BlockedURLError(f"Blocked internal address: {ip}")


class BrowserSession:
    """A single hidden, muted, headless browser tab the assistant can drive.

    Never shown or made audible to the user - it only feeds extracted text and
    links back to the model as data.
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._page = None

    def _ensure_page(self):
        if self._page is not None:
            return self._page
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--mute-audio",
                "--autoplay-policy=user-gesture-required",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="tr-TR",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        self._page = context.new_page()
        return self._page

    def _snapshot(self) -> dict:
        page = self._page
        title = page.title()
        if _looks_like_challenge(title):
            return {
                "url": page.url,
                "title": title,
                "text": (
                    "[This page is blocking automated browsers with a bot-check/CAPTCHA "
                    "challenge. Its real content could not be read. Do not invent prices "
                    "or details for this page - tell the user it's blocked and offer the "
                    "site's general URL instead.]"
                ),
                "links": [],
            }
        body_text = page.inner_text("body") if page.query_selector("body") else ""
        body_text = re.sub(r"\n{3,}", "\n\n", body_text).strip()[:MAX_TEXT_CHARS]

        links = []
        seen = set()
        for handle in page.query_selector_all("a[href]"):
            href = handle.get_attribute("href") or ""
            text = (handle.inner_text() or "").strip()
            if not href or not text or href.startswith(("javascript:", "#")):
                continue
            key = (text, href)
            if key in seen:
                continue
            seen.add(key)
            links.append({"text": text[:120], "href": href})
            if len(links) >= MAX_LINKS:
                break

        clean_links = [l for l in links if not _looks_like_injection(l["text"])]
        if _looks_like_injection(f"{title} {body_text}"):
            body_text = "[Page text withheld: looked like a prompt-injection attempt]"

        return {"url": page.url, "title": title, "text": body_text, "links": clean_links}

    def _snapshot_settled(self) -> dict:
        """Snapshot the page, retrying once if JS-rendered content hasn't landed yet.

        Many sites (e.g. YouTube) report domcontentloaded before their JS framework
        has actually painted the list/content the model needs - a bare snapshot right
        after navigation can come back empty.
        """
        snapshot = self._snapshot()
        if not snapshot["text"] and not snapshot["links"]:
            self._page.wait_for_timeout(1500)
            snapshot = self._snapshot()
        return snapshot

    def open(self, url: str) -> dict:
        _assert_url_allowed(url)
        page = self._ensure_page()
        page.goto(url, wait_until="domcontentloaded")
        _assert_url_allowed(page.url)
        if _looks_like_challenge(page.title()):
            page.wait_for_timeout(4000)  # let Cloudflare/anti-bot JS challenge resolve
        _log(f"[browser] open {url!r} -> {page.url!r}")
        return self._snapshot_settled()

    def click(self, target_text: str) -> dict:
        if self._page is None:
            raise RuntimeError("No open page to click on. Call browser_open first.")
        page = self._page
        locator = page.get_by_text(target_text, exact=False).first
        locator.click(timeout=NAV_TIMEOUT_MS)
        page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT_MS)
        _assert_url_allowed(page.url)
        _log(f"[browser] click {target_text!r} -> {page.url!r}")
        return self._snapshot_settled()

    def scroll(self, direction: str) -> dict:
        if self._page is None:
            raise RuntimeError("No open page to scroll. Call browser_open first.")
        delta = 1200 if direction == "down" else -1200
        self._page.mouse.wheel(0, delta)
        self._page.wait_for_timeout(300)
        return self._snapshot()

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._browser = None
        self._page = None
        self._playwright = None
        _log("[browser] session closed")


_session: BrowserSession | None = None


def _get_session() -> BrowserSession:
    global _session
    if _session is None:
        _session = BrowserSession()
    return _session


def browser_open(url: str) -> dict:
    return _get_session().open(url)


def browser_click(target_text: str) -> dict:
    return _get_session().click(target_text)


def browser_scroll(direction: str) -> dict:
    return _get_session().scroll(direction)


def browser_close() -> str:
    global _session
    if _session is not None:
        _session.close()
        _session = None
    return "Browser closed."


atexit.register(browser_close)


def format_snapshot(snapshot: dict) -> str:
    lines = [f"URL: {snapshot['url']}", f"Title: {snapshot['title']}", "", snapshot["text"], "", "Links:"]
    for l in snapshot["links"]:
        lines.append(f"- {l['text']}: {l['href']}")
    return "\n".join(lines)
