import json
import os
import time
import uuid

from core import paths
from core.paths import CHATS_DIR

TITLE_LEN = 60


def new_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


def _path(chat_id: str) -> str:
    return os.path.join(CHATS_DIR, f"{os.path.basename(chat_id)}.json")


def load(chat_id: str) -> dict | None:
    try:
        with open(_path(chat_id), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        return None
    return data


def append(chat_id: str, prompt: str, reply: str) -> None:
    now = time.time()
    chat = load(chat_id) or {"id": chat_id, "created": now, "messages": []}
    if not chat.get("title"):
        title = " ".join(prompt.split())
        chat["title"] = title if len(title) <= TITLE_LEN else title[: TITLE_LEN - 1] + "…"
    chat["updated"] = now
    chat["messages"] += [
        {"role": "user", "text": prompt, "time": now},
        {"role": "assistant", "text": reply, "time": now},
    ]
    os.makedirs(CHATS_DIR, exist_ok=True)
    tmp_path = _path(chat_id) + ".tmp"
    with paths.open_private(tmp_path) as f:
        json.dump(chat, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, _path(chat_id))


def list_chats() -> list[dict]:
    try:
        names = os.listdir(CHATS_DIR)
    except OSError:
        return []
    chats = [load(n[:-5]) for n in names if n.endswith(".json")]
    return sorted((c for c in chats if c), key=lambda c: c.get("updated", 0), reverse=True)


def delete(chat_id: str) -> bool:
    try:
        os.remove(_path(chat_id))
        return True
    except OSError:
        return False
