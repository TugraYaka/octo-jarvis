import threading

import certifi
import httpx
from google import genai
from google.genai import errors, types

from core import config

_lock = threading.Lock()
_client = None
_client_key = None
_http = None


class MissingKeyError(RuntimeError):
    pass


def get_client():
    global _client, _client_key, _http
    key = config.get_api_key()
    if not key:
        raise MissingKeyError("No Gemini API key set.")
    with _lock:
        if _client is None or key != _client_key:
            if _http is not None:
                _http.close()
            _http = httpx.Client(
                transport=httpx.HTTPTransport(local_address="0.0.0.0"),
                timeout=15,
                verify=certifi.where(),
            )
            _client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(timeout=15_000, httpx_client=_http),
            )
            _client_key = key
        return _client


def is_auth_error(exc: BaseException) -> bool:
    if isinstance(exc, MissingKeyError):
        return True
    if not isinstance(exc, errors.ClientError):
        return False
    if exc.code in (401, 403):
        return True
    text = str(exc).lower()
    return exc.code == 400 and ("api key" in text or "api_key_invalid" in text)


def validate_key() -> None:
    next(iter(get_client().models.list()), None)
