import glob
import os
import shutil
import socket
import subprocess
import sys

from core import config, paths, personal, ttsinstall

OK, WARN, FAIL = "ok", "warn", "fail"
MARKS = {OK: "[ ok ]", WARN: "[warn]", FAIL: "[FAIL]"}
API_HOST = "generativelanguage.googleapis.com"


def _online() -> bool:
    try:
        with socket.create_connection((API_HOST, 443), timeout=4):
            return True
    except OSError:
        return False


def _probe(py: str, code: str, timeout: int = 60):
    try:
        result = subprocess.run(
            [py, *paths.python_c_args(code)], cwd=paths.RESOURCE_DIR, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return result.returncode, (result.stdout or result.stderr).strip()


def check_key(py: str):
    code = (
        "import sys\n"
        "from core.client import validate_key, is_auth_error\n"
        "try:\n"
        "    validate_key()\n"
        "except Exception as e:\n"
        "    print(str(e)[:150]); sys.exit(2 if is_auth_error(e) else 3)\n"
    )
    return _probe(py, code, timeout=30)


def run_checks(venv_py: str, venv_ok: bool, deps_current: bool) -> list:
    results = []

    def add(status, name, detail=""):
        results.append((status, name, detail))

    v = sys.version_info
    add(OK if v >= (3, 10) else FAIL, "Python", f"{v.major}.{v.minor}.{v.micro} on {sys.platform}")

    try:
        os.makedirs(paths.DATA_DIR, exist_ok=True)
        probe = os.path.join(paths.DATA_DIR, ".write-test")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        free = shutil.disk_usage(paths.DATA_DIR).free / 1024 ** 3
        add(OK if free >= 2 else WARN, "Data folder", f"{paths.DATA_DIR} ({free:.1f} GB free)")
    except OSError as e:
        add(FAIL, "Data folder", f"{paths.DATA_DIR} is not writable: {e}")

    if not venv_ok:
        add(FAIL, "Environment", "not set up yet. Run: jarvis setup")
    elif not deps_current:
        add(WARN, "Environment", "dependencies out of date; they update on the next launch or: jarvis setup")
    else:
        add(OK, "Environment", "private Python environment is ready")

    online = _online()
    add(OK if online else FAIL, "Internet", f"{API_HOST} reachable" if online else f"cannot reach {API_HOST}")

    key = config.get_api_key()
    provider = config.get_provider()
    if provider != "gemini":
        ready = config.provider_ready(provider)
        add(OK if ready else FAIL, "AI provider", f"{config.PROVIDERS[provider]['label']} "
            f"({config.provider_model(provider)}), {'configured' if ready else 'not configured. Start jarvis and use /setkey'}")
    if not key and provider != "gemini":
        add(WARN, "Gemini API key", "not set (optional: enables semantic memory search; keyword search is used instead)")
    elif not key:
        add(FAIL, "Gemini API key", "not set. Run: jarvis setup (or start jarvis)")
    elif not (venv_ok and online):
        add(WARN, "Gemini API key", "present, could not be verified (no environment or no internet)")
    else:
        source = f"saved in {config.key_storage()}" if config.stored_api_key() else "environment variable"
        code, message = check_key(venv_py)
        if code == 0:
            add(OK, "Gemini API key", f"{source}, accepted by Google")
        elif code == 2:
            add(FAIL, "Gemini API key", f"{source}, rejected by Google. Use /logout in JARVIS to replace it")
        else:
            add(WARN, "Gemini API key", f"{source}, could not be verified: {message}")

    on_path = shutil.which("jarvis")
    add(OK if on_path else WARN, "jarvis command", on_path or "not on PATH. Run: jarvis install")
    add(OK if shutil.which("git") else WARN, "git", "found" if shutil.which("git") else "missing (only needed for jarvis personal)")

    if venv_ok:
        code, message = _probe(
            venv_py,
            "import sounddevice as sd; print(sum(1 for d in sd.query_devices() if d['max_input_channels'] > 0))",
        )
        if code != 0:
            add(WARN, "Microphone", "audio library unavailable" + (" (Linux: sudo apt install libportaudio2)" if sys.platform.startswith("linux") else ""))
        elif message.strip() == "0":
            add(WARN, "Microphone", "no input device found")
        else:
            add(OK, "Microphone", f"{message.strip()} input device(s)")

    chromium = glob.glob(os.path.join(paths.BROWSERS_DIR, "chromium*"))
    add(OK if chromium else WARN, "Web browsing browser", "downloaded" if chromium else "not downloaded yet (downloads on first use, or jarvis setup)")

    whisper = glob.glob(os.path.join(paths.HF_HOME, "hub", "models--Systran--faster-whisper-small", "snapshots", "*"))
    add(OK if whisper else WARN, "Speech model", "downloaded" if whisper else "not downloaded yet (downloads on first /talk, or jarvis setup)")

    runtime = ttsinstall.find_runtime()
    if runtime is None:
        add(WARN, "TTS server", "not installed (spoken replies off). Run: jarvis tts install")
    else:
        add(OK, "TTS server", f"{runtime.python} ({'managed' if runtime.owned else 'external'})")
        voice = ttsinstall.custom_voice()
        add(OK if voice else WARN, "Custom voice", voice or f"no .wav in {' or '.join(ttsinstall.voice_folders())} (default voice is used)")

    if sys.platform.startswith("linux"):
        player = next((p for p in ("paplay", "aplay", "ffplay") if shutil.which(p)), None)
        add(OK if player else WARN, "Audio player", player or "none found (install pulseaudio-utils, alsa-utils or ffmpeg)")

    add(OK, "Personal repository", personal.status())
    return results


def report(results: list) -> int:
    for status, name, detail in results:
        print(f"{MARKS[status]} {name}: {detail}", flush=True)
    fails = sum(1 for r in results if r[0] == FAIL)
    warns = sum(1 for r in results if r[0] == WARN)
    print(f"\n{len(results) - fails - warns} ok, {warns} warning(s), {fails} problem(s).", flush=True)
    return 1 if fails else 0
