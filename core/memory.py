import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

try:
    import fcntl
except ImportError:  # Not available on Windows — locking is silently disabled
    fcntl = None

from core import paths
from core.embeddings import embed

MEMORY_PATH = paths.MEMORY_PATH
_LOG_PATH = paths.SEARCH_LOG
_LOCK_PATH = MEMORY_PATH + ".lock"

_MAX_ENTRIES = 200
_MAX_ENTRY_CHARS = 400
_DUPLICATE_SIMILARITY = 0.93
_RETRIEVAL_TOP_K = 5
_RETRIEVAL_MIN_SCORE = 0.65
_RECENCY_HALFLIFE_DAYS = 180

# Every mutation (append/replace, reset, forget) goes through this single
# worker so operations are strictly ordered — e.g. /resetmemory can never be
# undone by an append that was queued earlier but finishes later.
_writer = ThreadPoolExecutor(max_workers=1)


class _locked:
    """Cross-process advisory lock around memory.json's read-modify-write.

    Same-process writes are already serialized by the single-worker `_writer`
    executor; this additionally stops a second JARVIS process (e.g. a second
    terminal window) from reading/writing the file at the same time and
    silently dropping one side's update.
    """

    def __enter__(self):
        os.makedirs(os.path.dirname(_LOCK_PATH), exist_ok=True)
        self._fh = open(_LOCK_PATH, "w")
        if fcntl is not None:
            fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc_info):
        if fcntl is not None:
            fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()
        return False


def _log(message: str) -> None:
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{message}\n")
    except OSError:
        pass


def _truncate(text: str) -> str:
    if len(text) <= _MAX_ENTRY_CHARS:
        return text
    cut = text[:_MAX_ENTRY_CHARS]
    last_space = cut.rfind(" ")
    if last_space > _MAX_ENTRY_CHARS * 0.6:
        cut = cut[:last_space]
    return cut.rstrip() + "…"


def _score(query_embedding: list[float], entry: dict) -> float:
    try:
        entry_embedding = entry["embedding"]
        if len(query_embedding) != len(entry_embedding):
            return 0.0
        return sum(x * y for x, y in zip(query_embedding, entry_embedding))
    except (TypeError, KeyError):
        return 0.0


def _recency_weight(entry: dict) -> float:
    ts = entry.get("ts")
    if not isinstance(ts, (int, float)):
        return 1.0
    age_days = max(0.0, (time.time() - ts) / 86400)
    return 0.5 ** (age_days / _RECENCY_HALFLIFE_DAYS)


def _ranked_score(query_embedding: list[float], entry: dict) -> float:
    # Mild recency nudge so a stale fact that contradicts a newer one (but
    # wasn't explicitly flagged as a replacement) doesn't permanently
    # outrank it just because its wording happens to match better.
    return _score(query_embedding, entry) * (0.85 + 0.15 * _recency_weight(entry))


def _load_entries() -> list[dict]:
    if not os.path.exists(MEMORY_PATH):
        return []
    try:
        with open(MEMORY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [
        e for e in data
        if isinstance(e, dict) and "text" in e and "embedding" in e
    ]


def _save_entries(entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(MEMORY_PATH), exist_ok=True)
    tmp_path = f"{MEMORY_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, MEMORY_PATH)


def _next_id(entries: list[dict]) -> int:
    existing_ids = [e["id"] for e in entries if isinstance(e.get("id"), int)]
    return (max(existing_ids) + 1) if existing_ids else 1


def _do_remember(text: str, replace_id: int | None) -> None:
    try:
        text = _truncate(" ".join(text.split()))
        if not text:
            return

        # Embedding is computed without holding the lock — so another
        # process isn't blocked during the network call.
        embedding = embed(text, "document")
        if embedding is None:
            _log(f"[memory] fact not saved (embedding failed): {text[:80]!r}")
            return

        with _locked():
            entries = _load_entries()

            if replace_id is not None:
                for e in entries:
                    if e.get("id") == replace_id:
                        e["text"] = text
                        e["embedding"] = embedding
                        e["ts"] = time.time()
                        _save_entries(entries)
                        return
                _log(f"[memory] replace id={replace_id} not found, saving as new fact")

            if any(e["text"] == text for e in entries):
                return
            if any(_score(embedding, e) >= _DUPLICATE_SIMILARITY for e in entries):
                return

            entries.append({
                "id": _next_id(entries),
                "text": text,
                "embedding": embedding,
                "ts": time.time(),
            })
            entries = entries[-_MAX_ENTRIES:]
            _save_entries(entries)
    except OSError as e:
        _log(f"[memory] fact not saved (disk error): {e}")


def _do_reset() -> None:
    try:
        with _locked():
            if os.path.exists(MEMORY_PATH):
                os.remove(MEMORY_PATH)
    except OSError as e:
        _log(f"[memory] reset failed: {e}")


def _do_forget(entry_id: int) -> bool:
    try:
        with _locked():
            entries = _load_entries()
            remaining = [e for e in entries if e.get("id") != entry_id]
            if len(remaining) == len(entries):
                return False
            _save_entries(remaining)
            return True
    except OSError as e:
        _log(f"[memory] forget id={entry_id} failed: {e}")
        return False


def queue_remember(text: str, replace_id: int | None = None) -> None:
    """Fire-and-forget: queues a save (or, with replace_id, an update) on the
    serialized writer thread."""
    _writer.submit(_do_remember, text, replace_id)


def reset_memory() -> None:
    """Waits for every already-queued write to finish, then wipes memory."""
    _writer.submit(_do_reset).result()


def forget_memory(entry_id: int) -> bool:
    """Waits for queued writes to finish, then removes a single entry by id."""
    return _writer.submit(_do_forget, entry_id).result()


def list_memory() -> list[dict]:
    entries = _load_entries()
    return [
        {"id": e.get("id"), "text": e["text"], "ts": e.get("ts")}
        for e in sorted(entries, key=lambda e: e.get("id") or 0)
    ]


def full_memory(limit: int = 40) -> list[dict]:
    """All stored facts, most recent first, without relevance filtering."""
    entries = sorted(_load_entries(), key=lambda e: e.get("ts") or 0, reverse=True)
    return [
        {"id": e.get("id"), "text": e["text"]}
        for e in entries[:limit]
    ]


def search_memory(query: str, top_k: int = _RETRIEVAL_TOP_K) -> list[dict]:
    entries = _load_entries()
    if not entries:
        return []

    embedding = embed(query, "query")
    if embedding is None:
        _log("[memory] search skipped (embedding failed)")
        return []

    scored = sorted(entries, key=lambda e: _ranked_score(embedding, e), reverse=True)
    return [
        {"id": e.get("id"), "text": e["text"]}
        for e in scored[:top_k]
        if _score(embedding, e) >= _RETRIEVAL_MIN_SCORE
    ]
