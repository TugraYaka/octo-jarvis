import os
import certifi
import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

_httpx_client = httpx.Client(
    transport=httpx.HTTPTransport(local_address="0.0.0.0"),
    timeout=15,
    verify=certifi.where(),
)

_api_key = os.environ.get("GEMINI_API_KEY")
if not _api_key:
    raise RuntimeError(
        "GEMINI_API_KEY is not set. Add it to your .env file."
    )

client = genai.Client(
    api_key=_api_key,
    http_options=types.HttpOptions(timeout=15_000, httpx_client=_httpx_client),
)
