import importlib.util
import os
import subprocess

from core import config, paths

PERSONA_FILE = "persona.md"
PLUGINS_DIR = "plugins"
REQUIREMENTS_FILE = "requirements.txt"
_MAX_PERSONA_CHARS = 4000
TRUST_KEY = "personal_trusted_commit"
_REVIEWED_PATHS = (PLUGINS_DIR, REQUIREMENTS_FILE, PERSONA_FILE)


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


def head_commit(ref: str = "HEAD") -> str | None:
    if not is_installed():
        return None
    try:
        return _git("rev-parse", ref, cwd=paths.PERSONAL_DIR) or None
    except RuntimeError:
        return None


def is_trusted() -> bool:
    head = head_commit()
    return bool(head) and config.get(TRUST_KEY) == head


def review_summary(base: str | None = None, ref: str = "HEAD") -> str:
    """What runs or is injected from the repository: plugin code, extra packages and the persona."""
    if base:
        out = _git("diff", "--stat", base, ref, "--", *_REVIEWED_PATHS, cwd=paths.PERSONAL_DIR)
        return out or "No changes to plugins, requirements or persona."
    out = _git("ls-tree", "-r", "--name-only", ref, "--", *_REVIEWED_PATHS, cwd=paths.PERSONAL_DIR)
    return out or "No plugins, requirements or persona in this repository."


def _approve(summary: str, confirm, ref: str = "HEAD") -> bool:
    approved = bool(confirm and confirm(summary))
    config.set_value(TRUST_KEY, head_commit(ref) if approved else None)
    return approved


def trust(confirm) -> str:
    if not is_installed():
        raise RuntimeError("No personal repository is installed.")
    if _approve(review_summary(), confirm):
        return "Personal repository approved. Plugins, packages and persona will load."
    return "Not approved. Plugins, packages and persona stay disabled."


def set_repo(url: str, confirm=None) -> str:
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
    approved = _approve(review_summary(), confirm)
    return f"Personal repository cloned from {url}." + (
        "" if previous in (None, url) else f" (replaced {previous})"
    ) + ("" if approved else " Not approved: plugins, packages and persona stay disabled "
         "until you run: jarvis personal trust")


def pull(confirm=None) -> str:
    if not repo_url():
        raise RuntimeError("No personal repository configured. Run: jarvis personal set <git-url>")
    if not is_installed():
        return set_repo(repo_url(), confirm)
    old = head_commit()
    _git("fetch", "origin", cwd=paths.PERSONAL_DIR)
    new = head_commit("FETCH_HEAD")
    if not new or new == old:
        return "Already up to date."
    if not confirm or not confirm(review_summary(old, new)):
        return "Update not applied. The current version stays in place."
    _git("merge", "--ff-only", "FETCH_HEAD", cwd=paths.PERSONAL_DIR)
    config.set_value(TRUST_KEY, head_commit())
    return "Personal repository updated and approved."


def remove() -> str:
    existed = os.path.isdir(paths.PERSONAL_DIR)
    paths.rmtree(paths.PERSONAL_DIR)
    config.set_value("personal_repo", None)
    config.set_value(TRUST_KEY, None)
    return "Personal repository removed." if existed else "No personal repository was installed."


def status() -> str:
    url = repo_url()
    if not url:
        return "No personal repository configured."
    if not is_installed():
        state = "configured but not cloned (run: jarvis personal pull)"
    else:
        state = "installed, approved" if is_trusted() else "installed, NOT approved (run: jarvis personal trust)"
    return f"{url} ({state})"


def requirements_path() -> str | None:
    if not is_trusted():
        return None
    path = os.path.join(paths.PERSONAL_DIR, REQUIREMENTS_FILE)
    return path if os.path.isfile(path) else None


def persona_text() -> str:
    if not is_trusted():
        return ""
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
    if not is_trusted():
        log("Personal repository is not approved (new or changed). Plugins and persona are "
            "not loaded. Review it with: jarvis personal trust")
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
