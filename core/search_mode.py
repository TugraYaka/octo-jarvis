import json
import os

STATE_PATH = os.path.join(os.path.dirname(__file__), "..", "search_mode.json")

_DEFAULT_STATE = {"google": True, "duck": False}


def _load() -> dict:
    if not os.path.exists(STATE_PATH):
        return dict(_DEFAULT_STATE)
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_STATE)
    return {
        "google": bool(data.get("google", _DEFAULT_STATE["google"])),
        "duck": bool(data.get("duck", _DEFAULT_STATE["duck"])),
    }


def _save(state: dict) -> None:
    tmp_path = f"{STATE_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp_path, STATE_PATH)


def is_google_online() -> bool:
    return _load()["google"]


def is_duck_online() -> bool:
    return _load()["duck"]


def get_modes() -> tuple[bool, bool]:
    state = _load()
    return state["google"], state["duck"]


def set_google_online(online: bool) -> str:
    state = _load()
    if state["google"] == online:
        return f"Google search already {'online' if online else 'offline'}."
    state["google"] = online
    _save(state)
    return "Google search online." if online else "Google search offline."


def set_duck_online(online: bool) -> str:
    state = _load()
    if state["duck"] == online:
        return f"DuckDuckGo search already {'online' if online else 'offline'}."
    state["duck"] = online
    _save(state)
    return "DuckDuckGo search online." if online else "DuckDuckGo search offline."
