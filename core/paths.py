import os
import sys

APP_NAME = "JARVIS"
VERSION = "0.2.0"

IS_WIN = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

SOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_data_dir() -> str:
    if IS_MAC:
        return os.path.expanduser("~/Library/Application Support/JARVIS")
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
        return os.path.join(base, "JARVIS")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "jarvis")


DATA_DIR = os.path.abspath(os.environ.get("JARVIS_HOME") or _default_data_dir())

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
VENV_DIR = os.path.join(DATA_DIR, "venv")
LOG_DIR = os.path.join(DATA_DIR, "logs")
DEBUG_LOG = os.path.join(LOG_DIR, "debug.log")
SEARCH_LOG = os.path.join(LOG_DIR, "search.log")
MEMORY_PATH = os.path.join(DATA_DIR, "memory.json")
SEARCH_MODE_PATH = os.path.join(DATA_DIR, "search_mode.json")
SEARCH_USAGE_PATH = os.path.join(DATA_DIR, "search_usage.json")
BROWSER_PROFILE_DIR = os.path.join(DATA_DIR, "browser_profile")
BROWSERS_DIR = os.path.join(DATA_DIR, "browsers")
HF_HOME = os.path.join(DATA_DIR, "huggingface")
PERSONAL_DIR = os.path.join(DATA_DIR, "personal")
BIN_DIR = os.path.join(DATA_DIR, "bin")

TTS_DIR = os.path.join(DATA_DIR, "tts")
TTS_VENV_DIR = os.path.join(TTS_DIR, "venv")
TTS_HOME = os.path.join(TTS_DIR, "cache")
TTS_LOG = os.path.join(LOG_DIR, "tts_server.log")
DEFAULT_ASSETS_DIR = os.path.join(DATA_DIR, "assets")
TTS_SERVER_SCRIPT = os.path.join(SOURCE_ROOT, "tts_server", "server.py")
TTS_REQUIREMENTS = os.path.join(SOURCE_ROOT, "tts_server", "requirements.txt")


def venv_python(venv_dir: str) -> str:
    if IS_WIN:
        return os.path.join(venv_dir, "Scripts", "python.exe")
    return os.path.join(venv_dir, "bin", "python")


def ensure_dirs() -> None:
    os.makedirs(LOG_DIR, exist_ok=True)


def apply_cache_env() -> None:
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", BROWSERS_DIR)
    os.environ.setdefault("HF_HOME", HF_HOME)
