import json
import os
import subprocess
import tempfile
import urllib.request
import urllib.error

SERVER_URL = "http://127.0.0.1:8765"


def speak(text: str, lang: str = "tr") -> None:
    payload = json.dumps({"text": text, "lang": lang}).encode()
    req = urllib.request.Request(
        SERVER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            audio = resp.read()
    except urllib.error.URLError as e:
        raise RuntimeError(
            "TTS server not reachable. Start it with: "
            "venv_tts/bin/python tts/server.py"
        ) from e

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio)
        out_path = tmp.name

    try:
        subprocess.run(["afplay", out_path], check=True)
    finally:
        os.remove(out_path)
