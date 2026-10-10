import ipaddress
import json
import os
from urllib.parse import urlsplit

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
    paths.ensure_dirs()
    tmp_path = f"{paths.CONFIG_PATH}.tmp"
    with paths.open_private(tmp_path) as f:
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


KEYRING_SERVICE = "JARVIS"
KEYRING_ENV = "JARVIS_KEYRING"


def _keyring():
    """The OS credential store (Keychain, Credential Manager, Secret Service), or None."""
    if os.environ.get(KEYRING_ENV, "").strip() == "0":
        return None
    try:
        import keyring
        from keyring.backends import fail
        backend = keyring.get_keyring()
    except Exception:
        return None
    if isinstance(backend, fail.Keyring) or getattr(backend, "priority", 0) <= 0:
        return None
    return keyring


def _keyring_user(provider: str) -> str:
    import hashlib

    return f"{provider}:{hashlib.sha256(paths.DATA_DIR.encode()).hexdigest()[:12]}"


def _file_key(provider: str) -> str | None:
    key = load().get("api_key") if provider == "gemini" else _provider_settings(provider).get("api_key")
    return key.strip() if isinstance(key, str) and key.strip() else None


def _set_file_key(provider: str, key: str | None) -> None:
    if provider == "gemini":
        set_value("api_key", key)
    else:
        set_provider_value(provider, "api_key", key)


def _stored_key(provider: str) -> str | None:
    store = _keyring()
    file_key = _file_key(provider)
    if store is None:
        return file_key
    try:
        if file_key:
            store.set_password(KEYRING_SERVICE, _keyring_user(provider), file_key)
            _set_file_key(provider, None)
            return file_key
        key = store.get_password(KEYRING_SERVICE, _keyring_user(provider))
    except Exception:
        return file_key
    return key.strip() if key and key.strip() else None


def _store_key(provider: str, key: str | None) -> None:
    key = key.strip() if key and key.strip() else None
    store = _keyring()
    if store is not None:
        try:
            if key:
                store.set_password(KEYRING_SERVICE, _keyring_user(provider), key)
            else:
                try:
                    store.delete_password(KEYRING_SERVICE, _keyring_user(provider))
                except Exception:
                    pass
            _set_file_key(provider, None)
            return
        except Exception:
            pass
    _set_file_key(provider, key)


def key_storage() -> str:
    return "system keychain" if _keyring() is not None else "config file (0600)"


def stored_api_key() -> str | None:
    return _stored_key("gemini")


def env_api_key() -> str | None:
    key = os.environ.get(API_KEY_ENV, "").strip()
    return key or None


def get_api_key() -> str | None:
    return stored_api_key() or env_api_key()


def set_api_key(key: str) -> None:
    _store_key("gemini", key)


def clear_api_key() -> None:
    _store_key("gemini", None)


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


PROVIDERS = {
    "gemini": {"search": "Google Search", "label": "Gemini", "model": "gemini-3.6-flash", "env": API_KEY_ENV},
    "claude": {"search": "Claude web search", "label": "Claude", "model": "claude-opus-5-5", "env": "ANTHROPIC_API_KEY",
               "base_url": "https://api.anthropic.com/v1"},
    "openai": {"search": "ChatGPT web search", "label": "ChatGPT", "model": "gpt-5", "env": "OPENAI_API_KEY",
               "base_url": "https://api.openai.com/v1"},
    "custom": {"search": "Undefined search engine", "label": "Custom", "model": None, "env": "JARVIS_CUSTOM_API_KEY", "base_url": None},
}


def get_provider() -> str:
    name = get("provider")
    return name if name in PROVIDERS else "gemini"


def set_provider(name: str) -> None:
    set_value("provider", None if name == "gemini" else name)


def _provider_settings(name: str) -> dict:
    data = get("providers")
    settings = data.get(name) if isinstance(data, dict) else None
    return settings if isinstance(settings, dict) else {}


def set_provider_value(name: str, field: str, value) -> None:
    data = get("providers")
    data = data if isinstance(data, dict) else {}
    settings = data.get(name) if isinstance(data.get(name), dict) else {}
    if value is None:
        settings.pop(field, None)
    else:
        settings[field] = value
    data[name] = settings
    set_value("providers", data)


def provider_api_key(name: str) -> str | None:
    if name == "gemini":
        return get_api_key()
    return _stored_key(name) or os.environ.get(PROVIDERS[name]["env"], "").strip() or None


def provider_env_key(name: str) -> str | None:
    if name == "gemini":
        return env_api_key()
    return os.environ.get(PROVIDERS[name]["env"], "").strip() or None


def set_provider_api_key(name: str, key: str | None) -> None:
    _store_key(name, key)


def provider_model(name: str) -> str | None:
    model = _provider_settings(name).get("model")
    return model if isinstance(model, str) and model.strip() else PROVIDERS[name]["model"]


def provider_base_url(name: str) -> str | None:
    url = _provider_settings(name).get("base_url")
    url = url if isinstance(url, str) and url.strip() else PROVIDERS[name].get("base_url")
    return url.rstrip("/") if url else None


def base_url_problem(url: str) -> str | None:
    """API keys may only travel over plain HTTP to this machine or the local network."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return "The URL must start with http:// or https:// and include a host."
    if parts.scheme == "https":
        return None
    host = parts.hostname.lower()
    if host == "localhost" or host.endswith(".localhost"):
        return None
    lan = host.endswith(".local")
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_loopback:
            return None
        lan = lan or addr.is_private or addr.is_link_local
    except ValueError:
        pass
    if lan:
        if get("allow_lan_http"):
            return None
        return ("Plain http:// to another device sends the API key unencrypted over your network. "
                "Use https://, or run /baseurl <url> --allow-lan-http if you accept that.")
    return "Plain http:// is only allowed for servers on this computer. Use https:// for remote servers."


def provider_ready(name: str) -> bool:
    if name == "custom":
        return bool(provider_base_url(name) and provider_model(name))
    return bool(provider_api_key(name))
