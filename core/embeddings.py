import os
import sys

from google.genai import types

from core.client import client

DIM = 768

_MODEL = "gemini-embedding-001"
_TASK_TYPES = {
    "document": "RETRIEVAL_DOCUMENT",
    "query": "RETRIEVAL_QUERY",
}
_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "search.log")


def _log_failure(text: str, kind: str, error: Exception) -> None:
    print(f"[memory] embedding failed: {error}", file=sys.stderr)
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[embedding] {kind} embed failed for {text[:50]!r}: {error}\n")
    except OSError:
        pass


def embed(text: str, kind: str) -> list[float] | None:
    try:
        response = client.models.embed_content(
            model=_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type=_TASK_TYPES[kind],
                output_dimensionality=DIM,
            ),
        )
        vector = response.embeddings[0].values
        norm = sum(x * x for x in vector) ** 0.5
        if norm == 0:
            return None
        return [x / norm for x in vector]
    except Exception as e:
        _log_failure(text, kind, e)
        return None
