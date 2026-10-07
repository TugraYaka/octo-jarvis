import importlib.util
import os
import subprocess

from core import config, paths

PERSONA_FILE = "persona.md"
PLUGINS_DIR = "plugins"
REQUIREMENTS_FILE = "requirements.txt"
_MAX_PERSONA_CHARS = 4000


def repo_url() -> str | None:
    url = config.get("personal_repo")
    return url if isinstance(url, str) and url else None


def is_installed() -> bool:
    return os.path.isdir(os.path.join(paths.PERSONAL_DIR, ".git"))


def _git(*args: str, cwd: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace"
        )
    except FileNotFoundError:
        raise RuntimeError("git is not installed or not on PATH.") from None
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "git failed.")
    return result.stdout.strip()


def set_repo(url: str) -> str:
    url = url.strip()
    if not url or url.startswith("-"):
        raise RuntimeError("Invalid repository URL.")
    previous = repo_url()
    staging = paths.PERSONAL_DIR + ".new"
    paths.rmtree(staging)
    os.makedirs(paths.DATA_DIR, exist_ok=True)
    _git("clone", "--depth", "1", "--", url, staging)
    paths.rmtree(paths.PERSONAL_DIR)
    os.replace(staging, paths.PERSONAL_DIR)
    config.set_value("personal_repo", url)
    return f"Personal repository cloned from {url}." + (
        "" if previous in (None, url) else f" (replaced {previous})"
    )


def pull() -> str:
    if not repo_url():
        raise RuntimeError("No personal repository configured. Run: jarvis personal set <git-url>")
    if not is_installed():
        return set_repo(repo_url())
    out = _git("pull", "--ff-only", cwd=paths.PERSONAL_DIR)
    return out or "Already up to date."


def remove() -> str:
    existed = os.path.isdir(paths.PERSONAL_DIR)
    paths.rmtree(paths.PERSONAL_DIR)
    config.set_value("personal_repo", None)
    return "Personal repository removed." if existed else "No personal repository was installed."


def status() -> str:
    url = repo_url()
    if not url:
        return "No personal repository configured."
    state = "installed" if is_installed() else "configured but not cloned (run: jarvis personal pull)"
    return f"{url} ({state})"


def requirements_path() -> str | None:
    path = os.path.join(paths.PERSONAL_DIR, REQUIREMENTS_FILE)
    return path if os.path.isfile(path) else None


def persona_text() -> str:
    path = os.path.join(paths.PERSONAL_DIR, PERSONA_FILE)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read(_MAX_PERSONA_CHARS).strip()
    except OSError:
        return ""


def load_plugins(app, log) -> list[str]:
    folder = os.path.join(paths.PERSONAL_DIR, PLUGINS_DIR)
    if not os.path.isdir(folder):
        return []
    loaded = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".py") or name.startswith("_"):
            continue
        module_name = f"jarvis_personal_{name[:-3]}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, os.path.join(folder, name))
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            setup = getattr(module, "setup", None)
            if callable(setup):
                setup(app)
            loaded.append(name)
        except Exception as e:
            log(f"Personal plugin {name} failed: {e}")
    return loaded
