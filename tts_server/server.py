import hmac
import json
import os
import secrets
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import soundfile
import torch
from chatterbox.mtl_tts import SUPPORTED_LANGUAGES, ChatterboxMultilingualTTS

HOST = os.environ.get("JARVIS_TTS_HOST", "127.0.0.1")
PORT = int(os.environ.get("JARVIS_TTS_PORT", "8765"))
SERVICE_ID = "jarvis-tts"
MAX_BODY_BYTES = 64 * 1024
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")
FALLBACK_LANG = "en"
SUPPORTED_LANGS = frozenset(SUPPORTED_LANGUAGES)

ASSETS_DIR = os.environ.get("JARVIS_ASSETS_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "assets"
)
PERSONAL_DIR = os.environ.get("JARVIS_PERSONAL_DIR", "")
VOICE_ROOTS = [
    os.path.join(root, "voices") for root in (PERSONAL_DIR, ASSETS_DIR) if root
]


def pick_device():
    override = os.environ.get("JARVIS_TTS_DEVICE")
    if override:
        return override
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def wavs_in(folder):
    if not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".wav")
    )


def reference_voice(lang):
    for root in VOICE_ROOTS:
        if not os.path.isdir(root):
            continue
        names = os.listdir(root)
        for wanted in (lang, FALLBACK_LANG):
            match = [n for n in names if n == wanted]
            if match:
                found = wavs_in(os.path.join(root, match[0]))
                if found:
                    return found[0]
    return None


DEVICE = pick_device()
print(f"Voice folders: {', '.join(VOICE_ROOTS)}")
print(f"Loading Chatterbox Multilingual on {DEVICE}...")
model = ChatterboxMultilingualTTS.from_pretrained(device=DEVICE)
print("Model loading complete. Server ready.")

_lock = threading.Lock()
_current_ref = None


def synthesize(text, lang, out_path):
    global _current_ref
    ref = reference_voice(lang)
    with _lock:
        if ref and ref != _current_ref:
            model.prepare_conditionals(ref)
            _current_ref = ref
        wav = model.generate(text, language_id=lang)
    soundfile.write(out_path, wav.squeeze(0).numpy(), model.sr, subtype="PCM_16")


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status, body, content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _host_allowed(self):
        if HOST not in LOOPBACK_HOSTS:
            return True
        host = (self.headers.get("Host") or "").strip().lower()
        return host in {f"127.0.0.1:{PORT}", f"localhost:{PORT}", f"[::1]:{PORT}"}

    def do_GET(self):
        if not self._host_allowed():
            self._reply(403, b"Forbidden")
            return
        body = {"service": SERVICE_ID, "languages": sorted(SUPPORTED_LANGS)}
        self._reply(200, json.dumps(body).encode(), "application/json")

    def do_POST(self):
        token = (self.headers.get("X-JARVIS-Token") or "").encode()
        if not self._host_allowed() or not hmac.compare_digest(token, TOKEN.encode()):
            self._reply(403, b"Forbidden")
            return
        if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
            self._reply(415, b"Content-Type must be application/json")
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > MAX_BODY_BYTES:
                self._reply(413, b"Request body too large or empty")
                return
            body = json.loads(self.rfile.read(length))
            text = body["text"]
            lang = body.get("lang", FALLBACK_LANG)
            if not isinstance(text, str) or not text.strip():
                raise ValueError("text must be a non-empty string")
            if lang not in SUPPORTED_LANGS:
                raise ValueError("unsupported language")
        except (ValueError, KeyError, TypeError) as e:
            self._reply(400, f"Bad request: {e}".encode())
            return

        raw_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            synthesize(text, lang, raw_path)
            with open(raw_path, "rb") as f:
                data = f.read()
        except Exception as e:
            print(f"Synthesis failed: {e}", file=sys.stderr)
            self._reply(500, f"Synthesis failed: {e}".encode())
            return
        finally:
            os.remove(raw_path)

        self._reply(200, data, "audio/wav")

    def log_message(self, format, *args):
        pass


def load_token():
    path = os.environ.get("JARVIS_TTS_TOKEN_FILE", "")
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
        if token:
            return token
    except OSError:
        pass
    print("No JARVIS_TTS_TOKEN_FILE set; synthesis requests will be refused.", file=sys.stderr)
    return secrets.token_urlsafe(32)


TOKEN = load_token()


if __name__ == "__main__":
    print(f"Listening on http://{HOST}:{PORT}")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
