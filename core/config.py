import json
import os

from core import paths

API_KEY_ENV = "GEMINI_API_KEY"


def load() -> dict:
    try:
        with open(paths.CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> None:
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    tmp_path = f"{paths.CONFIG_PATH}.tmp"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, paths.CONFIG_PATH)


def get(key: str, default=None):
    return load().get(key, default)


def set_value(key: str, value) -> None:
    data = load()
    if value is None:
        data.pop(key, None)
    else:
        data[key] = value
    save(data)


def stored_api_key() -> str | None:
    key = load().get("api_key")
    return key.strip() if isinstance(key, str) and key.strip() else None


def env_api_key() -> str | None:
    key = os.environ.get(API_KEY_ENV, "").strip()
    return key or None


def get_api_key() -> str | None:
    return stored_api_key() or env_api_key()


def set_api_key(key: str) -> None:
    set_value("api_key", key.strip())


def clear_api_key() -> None:
    set_value("api_key", None)


UNSPECIFIED = "unspecified"
PROFILE_FIELDS = ("name", "age", "gender")


def get_profile() -> dict:
    profile = get("profile")
    return profile if isinstance(profile, dict) else {}


def profile_complete() -> bool:
    profile = get_profile()
    return all(field in profile for field in PROFILE_FIELDS)


def set_profile_field(field: str, value) -> None:
    profile = get_profile()
    profile[field] = value
    set_value("profile", profile)
