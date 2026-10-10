import re
import time

from core import assistant, claude_client, config, gemini_client, openai_client
from core.assistant import get_reply_lang, get_thinking_level, set_thinking_level  # noqa: F401
from core.client import is_auth_error as _is_gemini_auth_error
from core.client import is_provider_auth_error, is_provider_transient


def provider() -> str:
    return config.get_provider()


def label(name: str | None = None) -> str:
    name = name or provider()
    return f"{config.PROVIDERS[name]['label']} ({config.provider_model(name) or 'no model set'})"


def thinking_supported() -> bool:
    if provider() != "claude":
        return True
    return claude_client.thinking_supported(config.provider_model("claude") or "")


def thinking_label() -> str:
    return get_thinking_level() if thinking_supported() else "managed by the model"


def _ask_once(name: str, prompt: str, history: list, on_status=None) -> tuple[str, list]:
    if name == "gemini":
        return gemini_client.ask_once(prompt, history, on_status=on_status)
    if name == "claude":
        return claude_client.ask_once(prompt, history, on_status=on_status)
    return openai_client.ask_once(prompt, history, on_status=on_status, provider=name)


def is_auth_error(exc: BaseException) -> bool:
    return _is_gemini_auth_error(exc) or is_provider_auth_error(exc)


def _is_transient(exc: BaseException) -> bool:
    return isinstance(exc, gemini_client.TRANSIENT_ERRORS) or is_provider_transient(exc)


def validate_key(name: str | None = None) -> None:
    name = name or provider()
    if name == "gemini":
        gemini_client.validate_key()
    elif name == "claude":
        claude_client.validate_key()
    else:
        openai_client.validate_key(name)


def warmup() -> None:
    validate_key()


def ask(prompt: str, history: list | None = None, on_status=None) -> tuple[str, list]:
    name = provider()
    history = history or []
    try:
        try:
            return _ask_once(name, prompt, history, on_status=on_status)
        except Exception as e:
            if not _is_transient(e):
                raise
            assistant.log(f"[{name}] transient error, retrying once: {type(e).__name__}: {e}")
            time.sleep(1)
            try:
                return _ask_once(name, prompt, history, on_status=on_status)
            except Exception as e2:
                if not _is_transient(e2):
                    raise
                assistant.log(f"[{name}] retry also failed: {type(e2).__name__}: {e2}")
                return (
                    assistant.Notice("[yellow]I am experiencing a temporary connection issue with the servers, sir. "
                    "Please try again shortly.[/yellow]"),
                    history,
                )
    except Exception as e:
        if is_auth_error(e):
            assistant.log(f"[{name}] key rejected: {type(e).__name__}")
            return (
                assistant.Notice(f"[red]JARVIS can't respond: the {config.PROVIDERS[name]['label']} API key or "
                "settings are missing or were rejected. Run /setkey to enter a valid key, "
                "or /provider to switch models.[/red]"),
                history,
            )
        raise


_GEMINI_VERSION_RE = re.compile(r"^gemini-(\d+)(?:\.(\d+))?-")
MIN_GEMINI_VERSION = (3, 6)


def _gemini_supported(model: str) -> bool:
    match = _GEMINI_VERSION_RE.match(model)
    return bool(match) and (int(match[1]), int(match[2] or 0)) >= MIN_GEMINI_VERSION


CLAUDE_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1")
_OPENAI_SKIP = ("audio", "realtime", "transcribe", "tts", "image", "embedding", "search", "moderation", "instruct")


def list_models(name: str | None = None, limit: int = 25) -> list[str]:
    """Chat models the provider offers; empty when they can't be listed."""
    name = name or provider()
    if name == "claude":
        return list(CLAUDE_MODELS)
    if name == "gemini":
        models = [
            m.name.removeprefix("models/") for m in gemini_client.get_client().models.list()
            if "generateContent" in (m.supported_actions or []) and "gemini" in (m.name or "")
            and "embedding" not in m.name and _gemini_supported(m.name.removeprefix("models/"))
        ]
        return sorted(models, reverse=True)[:limit]
    ids = openai_client.list_model_ids(name)
    if name == "openai":
        ids = [i for i in ids if i.startswith(("gpt-", "o")) and not any(s in i for s in _OPENAI_SKIP)]
    return sorted(ids, reverse=True)[:limit]
