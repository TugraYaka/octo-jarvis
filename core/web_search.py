import os
import re

from ddgs import DDGS

MAX_RESULTS = 3
TIMEOUT = 5
BACKENDS = ("brave", "duckduckgo")

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


def _log(message: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{message}\n")
    except OSError:
        pass


def search(query: str) -> list[dict]:
    for backend in BACKENDS:
        try:
            results = DDGS(timeout=TIMEOUT).text(query, max_results=MAX_RESULTS, backend=backend)
        except Exception as e:
            _log(f"[web_search] {backend} failed: {e}")
            continue
        if not results:
            continue
        clean = [
            r for r in results
            if not _looks_like_injection(f"{r.get('title', '')} {r.get('body', '')}")
        ]
        dropped = len(results) - len(clean)
        if dropped:
            _log(f"[web_search] dropped {dropped} suspicious result(s) for {query!r}")
        if clean:
            return clean
    return []


def format_results(results: list[dict]) -> str:
    lines = []
    for r in results:
        lines.append(f"- {r.get('title', '')}: {r.get('body', '')} ({r.get('href', '')})")
    return "\n".join(lines)
