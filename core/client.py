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


class ProviderHTTPError(RuntimeError):
    def __init__(self, provider: str, status: int, body: str):
        super().__init__(f"{provider} HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


def is_provider_auth_error(exc: BaseException) -> bool:
    if isinstance(exc, MissingKeyError):
        return True
    return isinstance(exc, ProviderHTTPError) and exc.status in (401, 403)


def is_provider_transient(exc: BaseException) -> bool:
    if isinstance(exc, (httpx.ReadTimeout, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    return isinstance(exc, ProviderHTTPError) and (exc.status in (408, 429, 529) or exc.status >= 500)


_rest_clients: dict = {}


def rest_post(provider: str, url: str, headers: dict, payload: dict, read_timeout: float) -> dict:
    response = _rest_client(read_timeout).post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        raise ProviderHTTPError(provider, response.status_code, response.text)
    return response.json()


def rest_get(provider: str, url: str, headers: dict) -> dict:
    response = _rest_client(30).get(url, headers=headers)
    if response.status_code >= 400:
        raise ProviderHTTPError(provider, response.status_code, response.text)
    return response.json()


def _rest_client(read_timeout: float) -> httpx.Client:
    with _lock:
        client = _rest_clients.get(read_timeout)
        if client is None:
            client = httpx.Client(
                timeout=httpx.Timeout(read_timeout, connect=15),
                verify=certifi.where(),
            )
            _rest_clients[read_timeout] = client
        return client
