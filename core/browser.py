import atexit
import ipaddress
import locale
import os
import re
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from core import paths

paths.apply_cache_env()

from playwright.sync_api import sync_playwright

MAX_TEXT_CHARS = 4000
MAX_LINKS = 20
NAV_TIMEOUT_MS = 15_000
LOG_PATH = paths.SEARCH_LOG
LIVE_PROFILE_DIR = paths.BROWSER_PROFILE_DIR

# Playwright's sync API is bound to the thread that started it, while every chat
# request runs in a fresh worker thread. All browser work goes through this one thread.
_pw_thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="playwright")

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


def _browser_locale() -> str:
    try:
        name = locale.getlocale()[0]
    except (ValueError, TypeError):
        name = None
    if name and "_" in name and name.replace("_", "").isalpha():
        return name.replace("_", "-")
    return "en-US"


def _user_agent() -> str:
    if sys.platform == "win32":
        platform_token = "Windows NT 10.0; Win64; x64"
    elif sys.platform == "darwin":
        platform_token = "Macintosh; Intel Mac OS X 10_15_7"
    else:
        platform_token = "X11; Linux x86_64"
    return (
        f"Mozilla/5.0 ({platform_token}) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    )


_CHALLENGE_TITLES = ("just a moment", "attention required", "checking your browser", "access denied")


def _looks_like_challenge(title: str) -> bool:
    title = (title or "").lower()
    return any(t in title for t in _CHALLENGE_TITLES)


def _log(message: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{message}\n")
    except OSError:
        pass


class BlockedURLError(Exception):
    pass


def _is_missing_browser(error: Exception) -> bool:
    text = str(error)
    return "Executable doesn't exist" in text or "playwright install" in text


def install_chromium() -> None:
    from playwright._impl._driver import compute_driver_executable, get_driver_env

    _log("[browser] chromium missing, downloading it")
    driver = compute_driver_executable()
    command = list(driver) if isinstance(driver, (tuple, list)) else [driver]
    result = subprocess.run(
        command + ["install", "chromium"], env=get_driver_env(),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-400:]
        raise RuntimeError(f"Could not download the browser used for web browsing: {detail}")


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
    """A browser tab the assistant can drive.

    In hidden mode (default) it runs headless, muted, and is never shown to
    the user - it only feeds extracted text and links back to the model as
    data. In live mode it opens a real, visible Chrome window backed by a
    profile saved to disk, for tasks like purchases where the user should
    see, log in once, and be able to take over what's happening.
    """

    def __init__(self, headless: bool = True, persistent: bool = False) -> None:
        self._headless = headless
        self._persistent = persistent
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _launch(self) -> None:
        args = ["--disable-blink-features=AutomationControlled"]
        if self._headless:
            args += ["--mute-audio", "--autoplay-policy=user-gesture-required"]
        context_kwargs = dict(
            user_agent=_user_agent(),
            viewport={"width": 1280, "height": 800},
            locale=_browser_locale(),
        )
        if self._persistent:
            os.makedirs(LIVE_PROFILE_DIR, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                LIVE_PROFILE_DIR, headless=self._headless, args=args, **context_kwargs
            )
        else:
            self._browser = self._playwright.chromium.launch(headless=self._headless, args=args)
            self._context = self._browser.new_context(**context_kwargs)
        self._context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        self._context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def _ensure_page(self):
        if self._page is not None:
            return self._page
        self._playwright = sync_playwright().start()
        try:
            try:
                self._launch()
            except Exception as e:
                if not _is_missing_browser(e):
                    raise
                install_chromium()
                self._launch()
        except Exception:
            self._playwright.stop()
            self._playwright = None
            raise
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
        """Snapshot the page, waiting out JS-rendered content that hasn't landed yet.

        Many sites (e.g. YouTube) report domcontentloaded before their JS framework
        has actually painted the list/content the model needs - a bare snapshot right
        after navigation can come back with just a stray fragment (e.g. a video
        player's "0:00 / 12:50" timer) instead of the real page content, which looks
        non-empty but isn't actually settled yet. How long this takes varies run to
        run, so wait for network activity to quiet down first (best signal, but some
        sites never go fully idle) and then poll on a length threshold as a backstop.
        """
        try:
            self._page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        snapshot = self._snapshot()
        for _ in range(4):
            if len(snapshot["text"]) >= 150 or len(snapshot["links"]) >= 3:
                break
            self._page.wait_for_timeout(2000)
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

    def type(self, field_text: str, value: str) -> dict:
        if self._page is None:
            raise RuntimeError("No open page to type into. Call browser_open first.")
        page = self._page
        locator = None
        for candidate in (
            page.get_by_label(field_text, exact=False),
            page.get_by_placeholder(field_text, exact=False),
            page.locator(f"[name={field_text!r}]"),
        ):
            try:
                if candidate.count() > 0:
                    locator = candidate.first
                    break
            except Exception:
                continue
        if locator is None:
            raise RuntimeError(f"No input field found matching {field_text!r}.")
        input_type = (locator.get_attribute("type") or "").lower()
        if input_type == "password":
            raise PermissionError(
                "Refusing to type into a password field. The user must enter their "
                "own password."
            )
        locator.fill(value, timeout=NAV_TIMEOUT_MS)
        _log(f"[browser] type into {field_text!r}")
        return self._snapshot()

    def screenshot(self) -> bytes:
        if self._page is None:
            raise RuntimeError("No open page to screenshot. Call browser_open first.")
        return self._page.screenshot(type="png")

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        _log("[browser] session closed")


_session: BrowserSession | None = None
_live_session: BrowserSession | None = None


def _get_session() -> BrowserSession:
    global _session
    if _session is None:
        _session = BrowserSession()
    return _session


def _get_live_session() -> BrowserSession:
    global _live_session
    if _live_session is None:
        _live_session = BrowserSession(headless=False, persistent=True)
    return _live_session


def _run(fn, *args):
    return _pw_thread.submit(fn, *args).result()


def browser_open(url: str) -> dict:
    return _run(lambda: _get_session().open(url))


def browser_click(target_text: str) -> dict:
    return _run(lambda: _get_session().click(target_text))


def browser_scroll(direction: str) -> dict:
    return _run(lambda: _get_session().scroll(direction))


def _close_hidden() -> str:
    global _session
    if _session is not None:
        _session.close()
        _session = None
    return "Browser closed."


def browser_close() -> str:
    return _run(_close_hidden)


def browser_open_live(url: str) -> dict:
    """Open a URL in a real, visible Chrome window for the user to watch/take over."""
    return _run(lambda: _get_live_session().open(url))


def browser_click_live(target_text: str) -> dict:
    return _run(lambda: _get_live_session().click(target_text))


def browser_scroll_live(direction: str) -> dict:
    return _run(lambda: _get_live_session().scroll(direction))


def browser_type_live(field_text: str, value: str) -> dict:
    return _run(lambda: _get_live_session().type(field_text, value))


def browser_screenshot_live() -> bytes:
    return _run(lambda: _get_live_session().screenshot())


def _close_live() -> str:
    global _live_session
    if _live_session is not None:
        _live_session.close()
        _live_session = None
    return "Live browser closed."


def browser_close_live() -> str:
    return _run(_close_live)


def _close_all_at_exit() -> None:
    try:
        browser_close()
        browser_close_live()
    except Exception:
        pass


atexit.register(_close_all_at_exit)


def format_snapshot(snapshot: dict) -> str:
    lines = [f"URL: {snapshot['url']}", f"Title: {snapshot['title']}", "", snapshot["text"], "", "Links:"]
    for l in snapshot["links"]:
        lines.append(f"- {l['text']}: {l['href']}")
    return "\n".join(lines)
