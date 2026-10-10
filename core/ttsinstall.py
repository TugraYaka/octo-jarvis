import os
import shutil
import subprocess
import sys
import time
from typing import Callable, NamedTuple

from core import config, paths

PYTHON_VERSION = "3.11"
MIN_FREE_GB = 8
INSTALLED_MARKER = os.path.join(paths.TTS_DIR, ".installed")
DOWNLOAD_NOTICE = (
    "The voice server needs Python 3.11, PyTorch and the Chatterbox Multilingual voice model "
    "(roughly 3-5 GB of downloads). Chatterbox is open source under the MIT license."
)
MODEL_DOWNLOAD = (
    "from chatterbox.mtl_tts import ChatterboxMultilingualTTS;"
    "ChatterboxMultilingualTTS.from_pretrained(device='cpu')"
)


class Runtime(NamedTuple):
    python: str
    owned: bool


def find_runtime() -> Runtime | None:
    override = os.environ.get("JARVIS_TTS_PYTHON")
    if override and os.path.isfile(override):
        return Runtime(override, False)
    owned = paths.venv_python(paths.TTS_VENV_DIR)
    if os.path.isfile(owned) and os.path.isfile(INSTALLED_MARKER):
        return Runtime(owned, True)
    return None


def is_installed() -> bool:
    return find_runtime() is not None


def assets_dir() -> str:
    return (
        os.environ.get("JARVIS_ASSETS_DIR")
        or config.get("assets_dir")
        or paths.DEFAULT_ASSETS_DIR
    )


PACK_LANGS = ("en", "tr")


def voice_folders() -> list:
    return [os.path.join(paths.PERSONAL_DIR, "voices"), os.path.join(assets_dir(), "voices")]


def open_voice_folder() -> str:
    folder = voice_folders()[0]
    for lang in PACK_LANGS:
        os.makedirs(os.path.join(folder, lang), exist_ok=True)
    if paths.IS_MAC:
        subprocess.run(["open", folder])
    elif paths.IS_WIN:
        subprocess.run(["explorer", folder])
    else:
        subprocess.run(["xdg-open", folder])
    return folder


def custom_voice() -> str | None:
    for root in voice_folders():
        if not os.path.isdir(root):
            continue
        for lang in sorted(os.listdir(root)):
            folder = os.path.join(root, lang)
            if os.path.isdir(folder) and any(f.lower().endswith(".wav") for f in os.listdir(folder)):
                return folder
    return None


def server_env(runtime: Runtime) -> dict:
    env = {
        "JARVIS_ASSETS_DIR": assets_dir(),
        "JARVIS_PERSONAL_DIR": paths.PERSONAL_DIR,
        "JARVIS_TTS_TOKEN_FILE": paths.TTS_TOKEN_PATH,
        "PYTHONUNBUFFERED": "1",
    }
    if runtime.owned:
        env["HF_HOME"] = paths.TTS_HOME
    return env


def ensure_server_files() -> None:
    shutil.copytree(
        paths.TTS_SERVER_SRC, paths.TTS_SERVER_DIR, dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "assets"),
    )


def _uv_command() -> list:
    if paths.FROZEN:
        import uv

        return [uv.find_uv_bin()]
    return [sys.executable, "-m", "uv"]


def _run(cmd: list, progress: Callable[[str], None], env: dict) -> None:
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        encoding="utf-8", errors="replace", env={**os.environ, **env},
    )
    tail: list = []
    for line in proc.stdout:
        line = line.rstrip()
        if not line:
            continue
        tail = (tail + [line])[-12:]
        progress(line[:140])
    if proc.wait() != 0:
        raise RuntimeError("Command failed:\n" + "\n".join(tail))


def install(progress: Callable[[str], None]) -> None:
    os.makedirs(paths.TTS_DIR, exist_ok=True)
    free_gb = shutil.disk_usage(paths.TTS_DIR).free / 1024 ** 3
    if free_gb < MIN_FREE_GB:
        raise RuntimeError(f"Not enough disk space: {free_gb:.1f} GB free, {MIN_FREE_GB} GB needed.")

    uv_cache = os.path.join(paths.TTS_DIR, "uv-cache")
    uv_env = {
        "UV_CACHE_DIR": uv_cache,
        "UV_PYTHON_INSTALL_DIR": os.path.join(paths.TTS_DIR, "python"),
        "NO_COLOR": "1",
    }
    uv = _uv_command()
    ensure_server_files()
    try:
        if os.path.exists(INSTALLED_MARKER):
            os.remove(INSTALLED_MARKER)
        shutil.rmtree(paths.TTS_VENV_DIR, ignore_errors=True)

        progress(f"Creating a Python {PYTHON_VERSION} environment...")
        _run(uv + ["venv", "--python", PYTHON_VERSION, paths.TTS_VENV_DIR], progress, uv_env)

        python = paths.venv_python(paths.TTS_VENV_DIR)
        progress("Installing PyTorch and TTS packages (this takes a while)...")
        _run(
            uv + ["pip", "install", "--python", python, "-r", paths.TTS_REQUIREMENTS],
            progress, uv_env,
        )

        progress("Downloading the Chatterbox Multilingual voice model...")
        _run([python, "-c", MODEL_DOWNLOAD], progress, server_env(Runtime(python, True)))

        with open(INSTALLED_MARKER, "w", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S"))
    finally:
        shutil.rmtree(uv_cache, ignore_errors=True)


def uninstall() -> bool:
    existed = os.path.isdir(paths.TTS_DIR)
    shutil.rmtree(paths.TTS_DIR, ignore_errors=True)
    return existed


def cli_install() -> None:
    try:
        install(lambda line: print(line, flush=True))
    except Exception as e:
        sys.exit(f"TTS install failed: {e}")
    print("TTS server installed.")


if __name__ == "__main__":
    cli_install()
