#!/usr/bin/env python3
import os
import shlex
import shutil
import subprocess
import sys

if sys.version_info < (3, 10):
    sys.exit("JARVIS needs Python 3.10 or newer (found %d.%d)." % sys.version_info[:2])

ROOT = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, ROOT)

from core import config, paths, personal, ttsinstall  # noqa: E402

DEPS_MARKER = os.path.join(paths.VENV_DIR, ".jarvis-deps")
RC_START = "# >>> jarvis >>>"
RC_END = "# <<< jarvis <<<"
SHIM_TAG = "JARVIS launcher (managed by 'jarvis install')"
UNIX_BIN_DIR = os.path.expanduser("~/.local/bin")
HELP = """JARVIS %s

Usage:
  jarvis                          start the assistant
  jarvis install                  make the 'jarvis' command available everywhere
  jarvis uninstall [--yes]        remove JARVIS, its TTS server and all its data
  jarvis tts install              download and install the TTS server
  jarvis tts uninstall            remove only the TTS server
  jarvis tts status               show TTS server and voice model status
  jarvis tts assets [folder]      show or set the folder holding voices/ and models/
  jarvis personal set <git-url>   clone your personal repository (persona, plugins, packages)
  jarvis personal pull            update it
  jarvis personal remove          remove it
  jarvis personal status          show it
  jarvis --version
""" % paths.VERSION


def say(message=""):
    print(message, flush=True)


def fail(message, code=1):
    print(message, file=sys.stderr, flush=True)
    sys.exit(code)


def confirm(question):
    try:
        return input(question + " [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        say()
        return False


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _requirement_files():
    files = [os.path.join(ROOT, "requirements.txt")]
    extra = personal.requirements_path()
    if extra:
        files.append(extra)
    return files


def _deps_signature():
    import hashlib

    digest = hashlib.sha256()
    for path in _requirement_files():
        digest.update(_read(path).encode("utf-8"))
    return digest.hexdigest()


def _venv_works(py):
    if not os.path.isfile(py):
        return False
    return subprocess.run([py, "-c", "import sys"], capture_output=True).returncode == 0


def ensure_env():
    py = paths.venv_python(paths.VENV_DIR)
    if not _venv_works(py):
        say("Setting up JARVIS (first run only)...")
        shutil.rmtree(paths.VENV_DIR, ignore_errors=True)
        os.makedirs(paths.DATA_DIR, exist_ok=True)
        import venv

        try:
            venv.EnvBuilder(with_pip=True).create(paths.VENV_DIR)
        except Exception as e:
            shutil.rmtree(paths.VENV_DIR, ignore_errors=True)
            fail(
                "Could not create the Python environment: %s\n"
                "On Debian/Ubuntu install it with: sudo apt install python3-venv" % e
            )
    signature = _deps_signature()
    if _read(DEPS_MARKER) != signature:
        say("Installing dependencies (this can take a few minutes the first time)...")
        cmd = [py, "-m", "pip", "install", "--disable-pip-version-check"]
        for path in _requirement_files():
            cmd += ["-r", path]
        if subprocess.call(cmd) != 0:
            fail("Dependency installation failed. Check your internet connection and run jarvis again.")
        with open(DEPS_MARKER, "w", encoding="utf-8") as f:
            f.write(signature)
    return py


def run_app(args):
    py = ensure_env()
    cmd = [py, os.path.join(ROOT, "terminal", "main.py")] + args
    if paths.IS_WIN:
        try:
            sys.exit(subprocess.call(cmd))
        except KeyboardInterrupt:
            sys.exit(130)
    os.execv(py, cmd)


def _dir_size(path):
    total = 0
    for base, _, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def _fmt_size(num):
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return "%.1f %s" % (num, unit) if unit != "B" else "%d B" % num
        num /= 1024.0


def _rmtree(path):
    def retry(func, target, _):
        os.chmod(target, 0o700)
        func(target)

    option = "onexc" if sys.version_info >= (3, 12) else "onerror"
    shutil.rmtree(path, **{option: retry})


def _shell_rc_files():
    home = os.path.expanduser("~")
    return [os.path.join(home, name) for name in (".zshrc", ".zprofile", ".bashrc", ".bash_profile", ".profile")]


def _strip_rc_block(path):
    text = _read(path)
    if RC_START not in text:
        return False
    out, skipping = [], False
    for line in text.splitlines(keepends=True):
        if line.strip() == RC_START:
            skipping = True
            continue
        if skipping:
            if line.strip() == RC_END:
                skipping = False
            continue
        out.append(line)
    with open(path, "w", encoding="utf-8") as f:
        f.write("".join(out))
    return True


def _unix_shim_path():
    return os.path.join(UNIX_BIN_DIR, "jarvis")


def _win_path_edit(add=None, remove=None):
    import ctypes
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        try:
            value, kind = winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            value, kind = "", winreg.REG_EXPAND_SZ
        norm = lambda p: os.path.normcase(os.path.normpath(p))
        parts = [p for p in value.split(";") if p]
        if remove:
            parts = [p for p in parts if norm(p) != norm(remove)]
        if add and norm(add) not in [norm(p) for p in parts]:
            parts.append(add)
        winreg.SetValueEx(key, "Path", 0, kind, ";".join(parts))
    ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, None)


def cmd_install():
    if paths.IS_WIN:
        os.makedirs(paths.BIN_DIR, exist_ok=True)
        shim = os.path.join(paths.BIN_DIR, "jarvis.cmd")
        script = os.path.join(ROOT, "jarvis.py")
        with open(shim, "w", encoding="utf-8", newline="\r\n") as f:
            f.write(
                "@echo off\n"
                "rem %s\n"
                'if exist "%s" (\n  "%s" "%s" %%*\n) else (\n  py -3 "%s" %%*\n)\n'
                "exit /b %%errorlevel%%\n" % (SHIM_TAG, sys.executable, sys.executable, script, script)
            )
        _win_path_edit(add=paths.BIN_DIR)
        say("Installed. Open a new terminal window and type: jarvis")
        return
    os.makedirs(UNIX_BIN_DIR, exist_ok=True)
    shim = _unix_shim_path()
    with open(shim, "w", encoding="utf-8") as f:
        f.write(
            "#!/bin/sh\n"
            "# %s\n"
            'if [ -x %s ]; then PY=%s; else PY=python3; fi\n'
            'exec "$PY" %s "$@"\n'
            % (SHIM_TAG, shlex.quote(sys.executable), shlex.quote(sys.executable),
               shlex.quote(os.path.join(ROOT, "jarvis.py")))
        )
    os.chmod(shim, 0o755)
    on_path = UNIX_BIN_DIR in os.environ.get("PATH", "").split(os.pathsep)
    if on_path:
        say("Installed. Type: jarvis")
        return
    shell = os.path.basename(os.environ.get("SHELL", ""))
    home = os.path.expanduser("~")
    if shell == "zsh":
        rc = os.path.join(home, ".zshrc")
    elif shell == "bash":
        rc = os.path.join(home, ".bash_profile" if paths.IS_MAC else ".bashrc")
    else:
        rc = os.path.join(home, ".profile")
    say("%s is not on your PATH yet." % UNIX_BIN_DIR)
    if confirm("Add it to %s?" % rc):
        with open(rc, "a", encoding="utf-8") as f:
            f.write('\n%s\nexport PATH="$HOME/.local/bin:$PATH"\n%s\n' % (RC_START, RC_END))
        say("Done. Open a new terminal window and type: jarvis")
    else:
        say('Skipped. Add this line to your shell profile yourself: export PATH="$HOME/.local/bin:$PATH"')


def _stop_tts_server():
    from core import tts

    tts.stop_server(force=True)


def cmd_uninstall(args):
    brew = os.environ.get("JARVIS_INSTALL_METHOD") == "brew"
    shim = os.path.join(paths.BIN_DIR, "jarvis.cmd") if paths.IS_WIN else _unix_shim_path()
    shim_ours = SHIM_TAG in _read(shim)
    rc_files = [p for p in _shell_rc_files() if RC_START in _read(p)] if not paths.IS_WIN else []

    say("This will remove JARVIS from this computer:")
    if os.path.isdir(paths.DATA_DIR):
        say("  - %s (%s): settings, API key, memory, logs," % (paths.DATA_DIR, _fmt_size(_dir_size(paths.DATA_DIR))))
        say("    Python environment, TTS server, downloaded models")
    if shim_ours:
        say("  - the 'jarvis' command: %s" % shim)
    for rc in rc_files:
        say("  - the PATH entry JARVIS added to %s" % rc)
    if brew:
        say("  - the Homebrew package 'jarvis'")
    if os.path.isdir(paths.DEFAULT_ASSETS_DIR) and os.listdir(paths.DEFAULT_ASSETS_DIR):
        say("  ! Voice files in %s will be deleted too." % paths.DEFAULT_ASSETS_DIR)
    custom_assets = config.get("assets_dir")
    if custom_assets:
        say("  (Your voice assets folder %s is NOT touched.)" % custom_assets)
    if not brew:
        say("  (The source folder %s is NOT touched; delete it yourself.)" % ROOT)

    if "--yes" not in args and "-y" not in args and not confirm("Continue?"):
        say("Cancelled.")
        return

    _stop_tts_server()
    for rc in rc_files:
        _strip_rc_block(rc)
    if paths.IS_WIN:
        try:
            _win_path_edit(remove=paths.BIN_DIR)
        except OSError as e:
            say("Could not clean the PATH entry: %s" % e)
    elif shim_ours:
        os.remove(shim)
    if os.path.isdir(paths.DATA_DIR):
        _rmtree(paths.DATA_DIR)
    say("JARVIS data, TTS server and command removed.")
    if brew:
        subprocess.call(["brew", "uninstall", "jarvis"])


def cmd_tts(args):
    action = args[0] if args else "status"
    if action == "install":
        if ttsinstall.find_runtime() and ttsinstall.find_runtime().owned:
            say("The TTS server is already installed.")
            return
        say(ttsinstall.DOWNLOAD_NOTICE)
        if not confirm("Download and install the TTS server now?"):
            say("Cancelled.")
            return
        py = ensure_env()
        sys.exit(subprocess.call([py, "-m", "core.ttsinstall", "install"], cwd=ROOT))
    if action == "uninstall":
        if not os.path.isdir(paths.TTS_DIR):
            say("No JARVIS-managed TTS server is installed.")
            return
        if confirm("Remove the TTS server (%s)?" % _fmt_size(_dir_size(paths.TTS_DIR))):
            _stop_tts_server()
            ttsinstall.uninstall()
            say("TTS server removed.")
        return
    if action == "assets":
        if len(args) > 1:
            folder = os.path.abspath(os.path.expanduser(args[1]))
            if not os.path.isdir(folder):
                fail("Folder not found: %s" % folder)
            config.set_value("assets_dir", folder)
            say("Assets folder set to %s" % folder)
        else:
            say(ttsinstall.assets_dir())
        return
    if action == "status":
        runtime = ttsinstall.find_runtime()
        if runtime is None:
            say("TTS server: not installed (run: jarvis tts install)")
        else:
            say("TTS server: %s (%s)" % (runtime.python, "managed by JARVIS" if runtime.owned else "external"))
        assets = ttsinstall.assets_dir()
        model = os.path.join(assets, "models", "tr_finetuned", "model.pth")
        say("Assets folder: %s" % assets)
        say("Custom voice model: %s" % ("found" if os.path.isfile(model) else "not found (default voice will be used)"))
        return
    fail(HELP)


def cmd_personal(args):
    action = args[0] if args else "status"
    try:
        if action == "set":
            if len(args) < 2:
                fail("Usage: jarvis personal set <git-url>")
            say(personal.set_repo(args[1]))
        elif action == "pull":
            say(personal.pull())
        elif action == "remove":
            say(personal.remove())
        elif action == "status":
            say(personal.status())
        else:
            fail(HELP)
    except RuntimeError as e:
        fail(str(e))
    if action in ("set", "pull") and personal.requirements_path():
        say("Extra packages from the personal repository are installed on the next launch.")


def main(argv):
    command = argv[0] if argv else ""
    rest = argv[1:]
    if command in ("-h", "--help", "help"):
        say(HELP)
    elif command in ("-V", "--version"):
        say(paths.VERSION)
    elif command == "install":
        cmd_install()
    elif command == "uninstall":
        cmd_uninstall(rest)
    elif command == "tts":
        cmd_tts(rest)
    elif command == "personal":
        cmd_personal(rest)
    elif command in ("", "run"):
        run_app(rest)
    else:
        fail("Unknown command: %s\n\n%s" % (command, HELP))


if __name__ == "__main__":
    main(sys.argv[1:])
