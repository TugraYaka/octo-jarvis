import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")
IS_WIN = sys.platform == "win32"

COLLECT_ALL = [
    "playwright", "textual", "faster_whisper", "ctranslate2", "onnxruntime", "av",
    "sounddevice", "_sounddevice_data", "uv", "ddgs", "primp", "lxml", "tokenizers",
    "huggingface_hub", "certifi", "google.genai", "rich", "keyring", "jaraco",
]


def target_name():
    system = {"darwin": "macos", "win32": "windows"}.get(sys.platform, "linux")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "x64"
    return f"jarvis-{system}-{arch}"


def build():
    shutil.rmtree(DIST, ignore_errors=True)
    shutil.rmtree(BUILD, ignore_errors=True)
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
        "--name", "jarvis", "--distpath", DIST, "--workpath", BUILD, "--specpath", BUILD,
        "--paths", ROOT,
        "--add-data", f"{os.path.join(ROOT, 'tts_server')}{os.pathsep}tts_server",
        "--hidden-import", "jarvis", "--hidden-import", "terminal.main",
    ]
    for name in COLLECT_ALL:
        cmd += ["--collect-all", name]
    cmd.append(os.path.join(ROOT, "packaging", "pyinstaller", "entry.py"))
    subprocess.check_call(cmd, cwd=ROOT)


def package():
    name = target_name()
    folder = os.path.join(DIST, "jarvis")
    if IS_WIN:
        archive = os.path.join(DIST, f"{name}.zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            for base, _, files in os.walk(folder):
                for f in files:
                    full = os.path.join(base, f)
                    z.write(full, os.path.join("jarvis", os.path.relpath(full, folder)))
    else:
        archive = os.path.join(DIST, f"{name}.tar.gz")
        with tarfile.open(archive, "w:gz") as t:
            t.add(folder, arcname="jarvis")
    digest = hashlib.sha256()
    with open(archive, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    with open(archive + ".sha256", "w") as f:
        f.write(f"{digest.hexdigest()}  {os.path.basename(archive)}\n")
    print(f"Built {archive} ({os.path.getsize(archive) / 1e6:.0f} MB)")


if __name__ == "__main__":
    build()
    package()
