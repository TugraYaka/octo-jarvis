import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp(prefix="jarvis-tts-smoke-")
os.environ["JARVIS_HOME"] = os.path.join(tmp, "data")
sys.path.insert(0, ROOT)

import jarvis
from core import paths, tts, ttsinstall

py = jarvis.ensure_env()
paths.apply_cache_env()
subprocess.check_call([py, "-m", "core.ttsinstall", "install"], cwd=ROOT)
runtime = ttsinstall.find_runtime()
token = tts.server_token()
assert runtime and runtime.owned, "managed TTS runtime not found after install"

env = {**os.environ, **ttsinstall.server_env(runtime), "JARVIS_ASSETS_DIR": os.path.join(tmp, "empty")}
log = open(os.path.join(tmp, "server.log"), "wb")
server = subprocess.Popen([runtime.python, paths.TTS_SERVER_SCRIPT], env=env, stdout=log, stderr=log)
try:
    end = time.time() + 900
    while time.time() < end:
        if server.poll() is not None:
            raise SystemExit("server exited early:\n" + open(os.path.join(tmp, "server.log"), errors="replace").read()[-2000:])
        try:
            urllib.request.urlopen("http://127.0.0.1:8765", timeout=2)
            break
        except Exception:
            time.sleep(3)
    else:
        raise SystemExit("server did not become ready")
    request = urllib.request.Request(
        "http://127.0.0.1:8765",
        data=json.dumps({"text": "Good evening. All systems are ready.", "lang": "en"}).encode(),
        headers={"Content-Type": "application/json", "X-JARVIS-Token": token},
    )
    audio = urllib.request.urlopen(request, timeout=300).read()
    assert audio[:4] == b"RIFF" and len(audio) > 10000, "no audio returned"
finally:
    server.terminate()
print("tts ok")
