# JARVIS

[![CI](https://github.com/TugraYaka/octo-jarvis/actions/workflows/ci.yml/badge.svg)](https://github.com/TugraYaka/octo-jarvis/actions/workflows/ci.yml)

A personal AI assistant for the terminal, powered by Google Gemini.

- Text chat with long-term memory
- Web search (Google or DuckDuckGo) and a hidden browser for reading pages
- Voice input (speech-to-text, offline)
- Optional spoken replies (local text-to-speech server, custom voices supported)
- Runs on macOS, Linux and Windows

> **Status:** Prototype. Developed and used daily on macOS (Apple Silicon). Automated tests (install, API key flow, setup, uninstall) run on macOS, Linux and Windows for every change. Microphone, spoken replies and web browsing on Linux and Windows have not been tried on real machines yet; please report anything that fails.

---

# For users

## Requirements

- A Gemini API key, free at <https://aistudio.google.com/apikey>
- Internet access
- Optional: a microphone for `/talk`
- Linux only: `libportaudio2` for the microphone (`sudo apt install libportaudio2`) and one of `paplay`, `aplay` or `ffplay` for spoken replies

You do **not** need Python for the one-line install.

## Install

### One line (macOS Apple Silicon, Linux x64, Windows x64)

Downloads the ready-made app for your system, verifies its checksum and adds the `jarvis` command.

```bash
# macOS and Linux
curl -fsSL https://raw.githubusercontent.com/TugraYaka/octo-jarvis/main/install.sh | sh
```

```powershell
# Windows (PowerShell)
irm https://raw.githubusercontent.com/TugraYaka/octo-jarvis/main/install.ps1 | iex
```

Open a new terminal and run `jarvis setup` for a guided setup, or just `jarvis`. To install a specific version, set `JARVIS_VERSION` (for example `v0.3.0`) first. All builds are attached to the [releases](https://github.com/TugraYaka/octo-jarvis/releases).

### Homebrew (macOS)

```bash
brew tap TugraYaka/octo-jarvis
brew trust TugraYaka/octo-jarvis
brew install octo-jarvis
```

Recent Homebrew versions refuse formulas from third-party taps until you trust them, which is what `brew trust` does. This route needs Homebrew's Python and installs from source; the first launch sets up its own environment. Afterwards `brew upgrade octo-jarvis` and `brew uninstall octo-jarvis` work with the short name. Run `jarvis uninstall` before `brew uninstall` to also remove JARVIS' data.

### Other systems

Intel Macs and other CPU types have no ready-made build yet. Use the developer instructions below to run from source.

## First start

1. Run `jarvis`. If there is no Gemini API key yet, the chat asks for it before anything else. The key is stored only on your computer, in a file only you can read. The `GEMINI_API_KEY` environment variable also works.
2. Google checks the key. A wrong key is rejected right away. If a saved key stops working later, JARVIS answers with a red error because it cannot respond without it.
3. Type `/logout` at any time to delete the saved key and enter a new one.

## Setup and health check

```bash
jarvis setup      # guided setup: command, API key, browser, speech model, TTS server
jarvis doctor     # checks everything and tells you what is wrong and how to fix it
```

`jarvis setup` asks before every large download. `jarvis setup --yes` accepts them all except the TTS server, which needs `--with-tts` because it comes with a license (see below). `jarvis doctor` changes nothing.

## Chat commands

Type `/` to open the command list (arrow keys and Enter to pick).

| Command | What it does |
|---|---|
| `/logout` | Remove the saved Gemini API key and ask for a new one |
| `/think`, `/think high`, `/think low` | Show or set the thinking level |
| `/google`, `/duckduck` | Show search engine status |
| `/onlinegoogle`, `/offlinegoogle` | Enable or disable Google search |
| `/onlineduckduck`, `/offlineduckduck` | Enable or disable DuckDuckGo search |
| `/listmemory`, `/forgetmemory <id>`, `/resetmemory` | Inspect or clear long-term memory |
| `/resethistory` | Clear the current conversation |
| `/voice`, `/voiceon`, `/voiceoff` | Show status of, enable or disable spoken replies |
| `/installtts` | Download and install the TTS server |
| `/turnontts`, `/turnofftts` | Start or stop the TTS server |
| `/startertts`, `/turnonstartertts`, `/turnoffstartertts` | Show or set TTS auto-start |
| `/speak <text>` | Speak text aloud |
| `/mictest`, `/talk` | Test the microphone / talk to JARVIS |
| `/turndefaults` | Reset the search and voice settings |

Only one search engine can be online at a time. Type `exit` to quit.

## Spoken replies (TTS server)

Spoken replies come from a separate local server (Coqui XTTS v2). It is large, so it is not installed with JARVIS. On first launch, if it is missing, JARVIS tells you what will be downloaded and asks for permission. Nothing is downloaded without your yes. You can also do it later:

- in the chat: `/installtts`
- in a terminal: `jarvis tts install`

The installer downloads a private Python 3.11 runtime, PyTorch (about 3-5 GB in total) and the XTTS v2 base model into JARVIS' data folder. XTTS v2 is published under the [Coqui Public Model License](https://coqui.ai/cpml), which allows non-commercial use only; installing it means you accept that license. Intel Macs are not supported by the pinned PyTorch version.

If you already have a compatible environment, set `JARVIS_TTS_PYTHON` to its Python executable and JARVIS uses it instead.

```bash
jarvis tts status              # what was found
jarvis tts uninstall           # remove only the TTS server
```

### Voice model (you must add this for a custom voice)

Without any model, the server speaks with a built-in default XTTS voice. The custom JARVIS voice comes from model and voice files that are **not part of this repository** (they are listed in `.gitignore`). To use one, put them in an assets folder with this layout:

```
<assets folder>/
  models/
    tr_finetuned/
      config.json        XTTS v2 config of the fine-tuned model (XttsConfig JSON)
      model.pth          fine-tuned XTTS v2 checkpoint
      vocab.json         XTTS v2 tokenizer vocabulary
      speaker_ref.wav    clean reference clip (about 6-30 s) of the target voice
  voices/
    en/*.wav             reference clips used for voice cloning in English
    tr/*.wav             same for Turkish (only used when no tr_finetuned model exists)
```

What the server looks for:

- **`models/tr_finetuned/`** must be a Coqui **XTTS v2** GPT fine-tune in the format produced by Coqui's XTTS fine-tuning (`TTS.demos.xtts_ft_demo`): `config.json` + `model.pth` + `vocab.json` + `speaker_ref.wav`. All four files are required; if one is missing the server says which and falls back. It is loaded with `Xtts.init_from_config` / `load_checkpoint`, generates 24 kHz mono audio, and the speaker embedding file (`speakers_xtts.pth`) is taken from the base XTTS v2 model that the installer downloads. It is used for Turkish (`tr`).
- **`voices/<lang>/*.wav`** are cloning references for the base model, used for any language that has no fine-tuned model.
- If neither exists, the built-in default speaker is used.

Tell JARVIS where the assets folder is (the default is `assets/` inside the data folder):

```bash
jarvis tts assets /path/to/assets
```

## Personal repository

Anything that is yours alone (persona, extra code, extra packages) can live in a separate, private git repository that JARVIS pulls in, so it never ends up in the public source.

```bash
jarvis personal set git@github.com:YOU/jarvis-personal.git
jarvis personal pull           # update later
jarvis personal remove
```

Layout of that repository (all parts are optional):

| Path | Used for |
|---|---|
| `persona.md` | Added to JARVIS' system instruction (who you are, how to address you) |
| `requirements.txt` | Extra Python packages, installed automatically on the next launch |
| `plugins/*.py` | Python modules imported at startup; an optional `setup(app)` function receives the app. Files starting with `_` are skipped |

JARVIS uses your own git credentials; it never asks for tokens. Only add repositories you trust, because plugins run with your permissions.

## Uninstall

```bash
jarvis uninstall
```

After a confirmation this removes everything JARVIS put on your computer: the Python environment, the TTS server and its models, the speech model, the browser JARVIS downloaded, your key, memory, logs, and the `jarvis` command with its PATH entry (and the Homebrew package when installed through brew). Your source folder and any assets folder you pointed to with `jarvis tts assets` are never touched.

## Where things are stored

| OS | Data folder |
|---|---|
| macOS | `~/Library/Application Support/JARVIS` |
| Windows | `%LOCALAPPDATA%\JARVIS` |
| Linux | `~/.local/share/jarvis` |

Set `JARVIS_HOME` to use another folder. Inside: `config.json` (key and settings), `memory.json`, `venv/`, `tts/`, `logs/debug.log`, `logs/search.log`, `logs/tts_server.log`.

## Troubleshooting

- **Run `jarvis doctor` first.** It names the problem and the fix.
- **Microphone errors:** check the OS microphone permission and the default input device; on Linux install `libportaudio2`.
- **No sound:** run `/voice`; if the server is off, `/turnontts`. On Linux install `pulseaudio-utils`, `alsa-utils` or `ffmpeg`.
- **Web browsing fails on Linux:** Chromium needs its usual system libraries (nss, atk, gbm, alsa). On a from-source install `sudo <data folder>/venv/bin/python -m playwright install-deps chromium` installs them.
- **Downloads are slow or stuck:** run `jarvis setup` again, it continues where it stopped.
- **Other errors:** see `logs/debug.log` in the data folder. Yellow messages are Gemini or quota warnings, red ones are local errors.

---

# For developers

## Run from source

Needs Python 3.10 or newer (on Windows tick "Add python.exe to PATH" in the installer) and `git`.

```bash
git clone https://github.com/TugraYaka/octo-jarvis.git
cd octo-jarvis
python3 jarvis.py setup        # Windows: py -3 jarvis.py setup
python3 jarvis.py              # start the assistant
```

You never run `pip install` yourself: the launcher creates a private virtual environment in the data folder and installs `requirements.txt` into it (again whenever that file changes). `python3 jarvis.py install` additionally makes the `jarvis` command available in every terminal.

`jarvis doctor` shows the state of your environment. Set `JARVIS_HOME` to a scratch folder to keep experiments away from your real data.

## Branches and releases

| Branch | Purpose |
|---|---|
| `main` | The released Prototype. Fixes go here; every release is tagged from it |
| `jarvis1` | Development of the next version (1.0) |

Releasing: bump `VERSION` in `core/paths.py`, push, then push a tag `vX.Y.Z` that matches it. The `Release` workflow runs the tests, builds the packages for macOS, Linux and Windows, and publishes a GitHub release with the packages and their checksums.

## Tests

```bash
python3 tests/smoke.py         # install, setup, key flow, personal repo, uninstall (downloads ~600 MB)
python3 tests/tts_smoke.py     # full TTS server install and a test synthesis (several GB)
```

GitHub Actions runs the smoke test on macOS, Linux and Windows with Python 3.10 and 3.13 for every push. The TTS test is started by hand: Actions, CI, Run workflow, tick the TTS box.

## Building the standalone packages

```bash
pip install -r requirements.txt pyinstaller
python packaging/pyinstaller/build.py
```

This produces `dist/jarvis-<system>-<cpu>.tar.gz` (`.zip` on Windows) and a `.sha256` file. The `Build` workflow does this on all three systems, tests the result and the installer scripts, and the `Release` workflow attaches them to the release.

## Project layout

```
jarvis.py               launcher: setup, doctor, install/uninstall, tts and personal commands
jarvis.cmd              Windows shim for running from the source folder
core/                   Gemini client, memory, search, browser, speech, TTS client, doctor
terminal/main.py        the chat interface
tts_server/             local XTTS server and its pinned requirements
tests/                  smoke tests
.github/workflows/      CI, Build and Release pipelines
packaging/homebrew/     Homebrew formula
packaging/pyinstaller/  builds the standalone packages
install.sh, install.ps1 one-line installers
```

## License

MIT, see [LICENSE](LICENSE). The XTTS v2 voice model that the TTS installer downloads is not part of this project and has its own license (Coqui Public Model License, non-commercial use only).
