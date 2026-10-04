import os
import shlex
import subprocess
import tempfile
import urllib.request
import urllib.error
import signal
import time
import threading
import queue
import re
import concurrent.futures
import json

from core import config, paths, ttsinstall

SERVER_URL = "http://127.0.0.1:8765"
SERVER_PORT = 8765
SERVICE_ID = "jarvis-tts"
IS_MAC = paths.IS_MAC
IS_WIN = paths.IS_WIN

voice_enabled = ttsinstall.is_installed()
server_disabled = False
_start_lock = threading.Lock()


def is_installed() -> bool:
    return ttsinstall.is_installed()


def get_autostart() -> bool:
    return bool(config.get("tts_autostart", True))


def set_autostart(value: bool) -> None:
    config.set_value("tts_autostart", value)


def set_server_disabled(value: bool) -> None:
    global server_disabled
    server_disabled = value


_window_id = None
_proc = None
_started_by_us = False


def set_voice(enabled: bool) -> None:
    global voice_enabled
    voice_enabled = enabled


def _listening_pids() -> list:
    try:
        if IS_WIN:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True,
            ).stdout.splitlines()
            pids = []
            for line in out:
                cols = line.split()
                if (len(cols) >= 5 and cols[3] == "LISTENING"
                        and cols[1].endswith(f":{SERVER_PORT}") and cols[4].isdigit()):
                    pids.append(int(cols[4]))
            return pids
        out = subprocess.run(
            ["lsof", "-ti", f"tcp:{SERVER_PORT}", "-sTCP:LISTEN"],
            capture_output=True, text=True,
        ).stdout.split()
    except FileNotFoundError:
        return []
    return [int(p) for p in out if p.isdigit()]


def server_running() -> bool:
    if _listening_pids():
        return True
    if IS_MAC or IS_WIN:
        return False
    import socket
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", SERVER_PORT)) == 0


def _is_our_server() -> bool:
    try:
        with urllib.request.urlopen(SERVER_URL, timeout=2) as resp:
            return json.loads(resp.read()).get("service") == SERVICE_ID
    except Exception:
        return False


def start_server() -> None:
    global server_disabled
    server_disabled = False
    with _start_lock:
        if _started_by_us or server_running():
            return
        _launch()


def _launch() -> None:
    global _window_id, _started_by_us, _proc
    runtime = ttsinstall.find_runtime()
    if runtime is None:
        raise RuntimeError("TTS server is not installed. Run /installtts to install it.")
    overrides = ttsinstall.server_env(runtime)
    if IS_MAC:
        exports = " ".join(f"{key}={shlex.quote(value)}" for key, value in overrides.items())
        cmd = (
            f"cd {shlex.quote(paths.SOURCE_ROOT)} && env {exports} "
            f"{shlex.quote(runtime.python)} {shlex.quote(paths.TTS_SERVER_SCRIPT)}"
        )
        cmd = cmd.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            'tell application "Terminal"\n'
            f'set t to do script "{cmd}"\n'
            "return id of window 1\n"
            "end tell"
        )
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        _window_id = res.stdout.strip() or None
    else:
        paths.ensure_dirs()
        flags = subprocess.CREATE_NEW_CONSOLE if IS_WIN else 0
        out = None if IS_WIN else open(paths.TTS_LOG, "ab")
        _proc = subprocess.Popen(
            [runtime.python, paths.TTS_SERVER_SCRIPT],
            cwd=paths.SOURCE_ROOT,
            env={**os.environ, **overrides},
            creationflags=flags,
            stdout=out,
            stderr=out,
        )
    _started_by_us = True


def stop_server(force: bool = False) -> None:
    global _started_by_us, _proc
    if not _started_by_us and not force:
        return
    if _is_our_server():
        for pid in _listening_pids():
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                pass
    if _proc is not None:
        _proc.terminate()
        _proc = None
    if IS_MAC and _window_id:
        time.sleep(0.5)
        subprocess.run(
            ["osascript", "-e",
             f'tell application "Terminal" to close (every window whose id is {_window_id}) saving no'],
            capture_output=True,
        )
    _started_by_us = False


def wait_for_server(timeout: float = 180) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if _proc is not None and _proc.poll() is not None:
            return False
        try:
            urllib.request.urlopen(SERVER_URL, timeout=2)
            return True
        except urllib.error.HTTPError:
            return True
        except Exception:
            time.sleep(1)
    return False


_queue: "queue.Queue" = queue.Queue()
_player = None
_worker_started = False
_generation = 0
on_error = None


def _split_sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text.strip())
    chunks, buf = [], ""
    for part in parts:
        if not part.strip():
            continue
        buf = f"{buf} {part}".strip()
        if len(buf) >= 40:
            chunks.append(buf)
            buf = ""
    if buf:
        if chunks and len(buf) < 15:
            chunks[-1] = f"{chunks[-1]} {buf}"
        else:
            chunks.append(buf)
    return chunks


def _synthesize(text: str, lang: str) -> bytes:
    payload = json.dumps({"text": text, "lang": lang}).encode()
    req = urllib.request.Request(
        SERVER_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"TTS server error {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError("TTS server not reachable") from e


def _player_cmd(path: str) -> list:
    if IS_MAC:
        return ["afplay", path]
    import shutil
    if shutil.which("paplay"):
        return ["paplay", path]
    if shutil.which("aplay"):
        return ["aplay", "-q", path]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]
    raise RuntimeError("No audio player found (install pulseaudio-utils, alsa-utils or ffmpeg)")


def _play(audio: bytes) -> None:
    global _player
    if IS_WIN:
        import winsound
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio)
            out_path = tmp.name
        try:
            winsound.PlaySound(out_path, winsound.SND_FILENAME)
        finally:
            os.remove(out_path)
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio)
        out_path = tmp.name
    try:
        _player = subprocess.Popen(_player_cmd(out_path))
        _player.wait()
    finally:
        _player = None
        os.remove(out_path)


def _ensure_server() -> bool:
    if voice_enabled is False or server_disabled:
        return False
    if not _started_by_us and not server_running():
        return False
    if _started_by_us and not wait_for_server():
        raise RuntimeError("TTS server did not become ready")
    return True


def is_ready() -> bool:
    try:
        urllib.request.urlopen(SERVER_URL, timeout=1)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def wait_until_ready() -> None:
    _ensure_server()


def _run_item(text: str, lang: str, gen: int) -> None:
    if not _ensure_server():
        return
    sentences = _split_sentences(text)
    if not sentences:
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(_synthesize, sentences[0], lang)
        for idx in range(len(sentences)):
            audio = pending.result()
            if idx + 1 < len(sentences):
                pending = pool.submit(_synthesize, sentences[idx + 1], lang)
            if gen != _generation:
                return
            _play(audio)


def _worker() -> None:
    while True:
        text, lang, gen = _queue.get()
        if gen != _generation or not voice_enabled:
            continue
        try:
            _run_item(text, lang, gen)
        except Exception as e:
            if on_error:
                on_error(e)


def speak(text: str, lang: str = "tr") -> None:
    global _worker_started
    if not voice_enabled or server_disabled:
        return
    if not _worker_started:
        _worker_started = True
        threading.Thread(target=_worker, daemon=True).start()
    _queue.put((text, lang, _generation))


def clear() -> None:
    global _generation
    _generation += 1
    if IS_WIN:
        import winsound
        winsound.PlaySound(None, winsound.SND_PURGE)
    if _player is not None:
        _player.terminate()
