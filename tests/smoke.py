import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JARVIS = os.path.join(ROOT, "jarvis.py")
IS_WIN = sys.platform == "win32"

tmp = tempfile.mkdtemp(prefix="jarvis-smoke-")
home = os.path.join(tmp, "home")
data = os.path.join(tmp, "data")
os.makedirs(home)
env = dict(os.environ, JARVIS_HOME=data, HOME=home, USERPROFILE=home, SHELL="/bin/sh")
env.pop("GEMINI_API_KEY", None)
failures = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name, flush=True)
    if not ok:
        print("     " + detail[-1500:].replace("\n", "\n     "), flush=True)
        failures.append(name)


def run(cmd, **kw):
    return subprocess.run(
        cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=kw.pop("timeout", 1800), **kw,
    )


def jarvis(*args, **kw):
    return run([sys.executable, JARVIS, *args], **kw)


def venv_python():
    sub = ("Scripts", "python.exe") if IS_WIN else ("bin", "python")
    return os.path.join(data, "venv", *sub)


r = jarvis("--version")
check("version", r.returncode == 0 and re.fullmatch(r"\d+\.\d+\.\d+", r.stdout.strip()) is not None, r.stdout + r.stderr)

r = jarvis("doctor")
check("doctor before setup reports missing environment", r.returncode == 1 and "[FAIL] Environment" in r.stdout, r.stdout + r.stderr)

r = jarvis("setup", "--yes", input="\n")
check("setup", "[ ok ] Environment" in r.stdout and "[ ok ] Web browsing browser" in r.stdout, r.stdout + r.stderr)
check("setup does not install tts without --with-tts", "Skipped. Add --with-tts" in r.stdout or "already installed" in r.stdout, r.stdout)

r = jarvis("doctor")
check("doctor after setup", "[ ok ] Environment" in r.stdout and "[FAIL] Gemini API key" in r.stdout, r.stdout + r.stderr)

r = run([venv_python(), os.path.join(ROOT, "tests", "tui_smoke.py")], cwd=ROOT)
check("chat asks for a key and rejects a fake one", r.returncode == 0 and "tui ok" in r.stdout, r.stdout + r.stderr)

r = run([venv_python(), "-c", "import core.gemini_client, core.tts, core.stt, core.browser, core.memory"], cwd=ROOT)
check("core modules import", r.returncode == 0, r.stdout + r.stderr)

src = os.path.join(tmp, "personal_src")
os.makedirs(src)
with open(os.path.join(src, "persona.md"), "w") as f:
    f.write("test persona")
git = ["git", "-c", "user.name=ci", "-c", "user.email=ci@example.com"]
run(["git", "init", "-q", src])
run(git + ["-C", src, "add", "-A"])
run(git + ["-C", src, "commit", "-qm", "init"])
r = jarvis("personal", "set", src)
check("personal set", r.returncode == 0, r.stdout + r.stderr)
check("personal persona file present", os.path.isfile(os.path.join(data, "personal", "persona.md")))
r = jarvis("personal", "remove")
check("personal remove", r.returncode == 0 and not os.path.isdir(os.path.join(data, "personal")), r.stdout + r.stderr)

r = jarvis("install", input="n\n")
check("install command", r.returncode == 0, r.stdout + r.stderr)
shim = os.path.join(data, "bin", "jarvis.cmd") if IS_WIN else os.path.join(home, ".local", "bin", "jarvis")
check("shim exists", os.path.isfile(shim), shim)
r = run([shim, "--version"], shell=IS_WIN)
check("shim runs", r.returncode == 0 and re.search(r"\d+\.\d+\.\d+", r.stdout) is not None, r.stdout + r.stderr)

r = jarvis("uninstall", "--yes")
check("uninstall", r.returncode == 0 and not os.path.exists(data) and not os.path.exists(shim), r.stdout + r.stderr)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\n{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
