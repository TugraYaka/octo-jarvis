# JARVIS

[![CI](https://github.com/TugraYaka/octo-jarvis/actions/workflows/ci.yml/badge.svg)](https://github.com/TugraYaka/octo-jarvis/actions/workflows/ci.yml)

A personal AI assistant for the terminal, powered by Gemini, Claude, ChatGPT or your own model server.

- Text chat with long-term memory
- Web search (Google or DuckDuckGo) and a hidden browser for reading pages
- Voice input (speech-to-text, offline)
- Optional spoken replies (local text-to-speech server, custom voices supported)
- Runs on macOS, Linux and Windows

> **Status:** Prototype. Developed and used daily on macOS (Apple Silicon). Automated tests (install, API key flow, setup, uninstall) run on macOS, Linux and Windows for every change. Microphone, spoken replies and web browsing on Linux and Windows have not been tried on real machines yet; please report anything that fails.

---

# For users

## Requirements

- An API key for one of the supported AI providers: Gemini, Claude, ChatGPT, or a custom OpenAI-compatible server (Ollama, LM Studio, OpenRouter, ...)
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

### Downloading a build by hand

The one-line installers above are the recommended way. If you download a build from the [releases](https://github.com/TugraYaka/octo-jarvis/releases) page in a browser instead, note that the builds are not signed by Apple yet. On macOS, Gatekeeper may then report that "Python.framework" is damaged. Nothing is wrong with the file; remove the download quarantine mark once and start it again:

```bash
xattr -dr com.apple.quarantine ~/Downloads/jarvis-macos-arm64
```

The `.sha256` files next to each build hold its checksum. Compare it with `shasum -a 256 <file>` to verify a download.

### Other systems

Intel Macs and other CPU types have no ready-made build yet. Use the developer instructions below to run from source.

## First start

1. Run `jarvis`. If no AI provider is set up yet, the chat first asks which one to use (Gemini, Claude, ChatGPT or Custom), then asks for its API key. The key is stored only on your computer, in a file only you can read. The `GEMINI_API_KEY`, `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` environment variables also work.
2. Google checks the key. A wrong key is rejected right away. If a saved key stops working later, JARVIS answers with a red error because it cannot respond without it.
3. Type `/logout` at any time to delete the saved key and enter a new one.

## Setup and health check

```bash
jarvis setup      # guided setup: command, API key, browser, speech model, TTS server
jarvis doctor     # checks everything and tells you what is wrong and how to fix it
```

`jarvis setup` asks before every large download. `jarvis setup --yes` accepts them all except the TTS server, which needs `--with-tts` because it is a large download (see below). `jarvis doctor` changes nothing.

## Chat commands

Type `/` to open the command list (arrow keys and Enter to pick).

| Command | What it does |
|---|---|
| `/logout` | Remove the saved API key and ask for a new one |
| `/think`, `/think high`, `/think low` | Show or set the thinking level |
| `/google`, `/duckduck` | Show search engine status |
| `/onlinegoogle`, `/offlinegoogle` | Enable or disable Google search |
| `/onlineduckduck`, `/offlineduckduck` | Enable or disable DuckDuckGo search |
| `/listmemory`, `/forgetmemory <id>`, `/resetmemory` | Inspect or clear long-term memory |
| `/resethistory` | Clear the current conversation |
| `/chats` | Browse and reopen past chats |
| `/newchat` | Start a new chat |
| `/deletechat` | Delete the current chat from chat history |
| `/voice`, `/voiceon`, `/voiceoff` | Show status of, enable or disable spoken replies |
| `/installtts` | Download and install the TTS server |
| `/turnontts`, `/turnofftts` | Start or stop the TTS server |
| `/startertts`, `/turnonstartertts`, `/turnoffstartertts` | Show or set TTS auto-start |
| `/speak <text>` | Speak text aloud |
| `/mictest`, `/talk` | Test the microphone / talk to JARVIS |
| `/turndefaults` | Reset the search and voice settings |

Only one search engine can be online at a time. Type `exit` to quit.

## Spoken replies (TTS server)

> **Intel Macs:** spoken replies do not work on Intel Macs. Chatterbox pins PyTorch 2.6, which has no build for Intel macOS, so the TTS server cannot be installed there. Everything else in JARVIS works without it.

Spoken replies come from a separate local server ([Chatterbox Multilingual](https://github.com/resemble-ai/chatterbox), MIT license). It is large, so it is not installed with JARVIS. On first launch, if it is missing, JARVIS tells you what will be downloaded and asks for permission. Nothing is downloaded without your yes. You can also do it later:

- in the chat: `/installtts`
- in a terminal: `jarvis tts install`

The installer downloads a private Python 3.11 runtime, PyTorch and the Chatterbox Multilingual model (about 3-5 GB in total) into JARVIS' data folder. Chatterbox is open source under the MIT license, so there is no non-commercial restriction. It speaks 23 languages: Arabic, Chinese, Danish, Dutch, English, Finnish, French, German, Greek, Hebrew, Hindi, Italian, Japanese, Korean, Malay, Norwegian, Polish, Portuguese, Russian, Spanish, Swahili, Swedish and Turkish. Generated audio carries Resemble AI's inaudible Perth watermark. It uses CUDA, Apple MPS or the CPU automatically (override with `JARVIS_TTS_DEVICE`).

If you already have a compatible environment, set `JARVIS_TTS_PYTHON` to its Python executable and JARVIS uses it instead.

To run the voice server on another machine, start `tts_server/server.py` there with `JARVIS_TTS_HOST=0.0.0.0` (and optionally `JARVIS_TTS_PORT`).

```bash
jarvis tts status              # what was found
jarvis tts uninstall           # remove only the TTS server
```

### Voice pack (you must add this for the JARVIS voice)

Without voice files, the server speaks with Chatterbox's built-in default voice. The JARVIS voice comes from reference clips that are **not part of this repository**. Chatterbox clones the voice from a clip in any of its languages, so one English JARVIS pack is enough for every language. Put the clips in your [personal repository](#personal-repository) (preferred) or in an assets folder:

```
<personal repo or assets folder>/
  voices/
    en/*.wav             main English JARVIS voice, used for every language without its own folder
    tr/*.wav             optional: a clip for one language only
```

Run `/addvoice` in the terminal app to open the personal `voices/` folder with `en/` and `tr/` ready; drop the clips in by hand. Loose `.wav` files directly inside `voices/` are ignored.

What the server looks for, per language: `voices/<lang>/`, then `voices/en/`, first in the personal repository and then in the assets folder. The first `.wav` in alphabetical order is used; a clean clip of about 10 seconds works best. If nothing is found, the built-in default voice is used.

Coming from the old XTTS setup: the English clips in `voices/en/` stay the main JARVIS voice as they are. The fine-tuned Turkish model (`models/tr_finetuned/`) is no longer used and can be deleted; Turkish is spoken with the English JARVIS voice.

Tell JARVIS where the assets folder is (the default is `assets/` inside the data folder):

```bash
jarvis tts assets /path/to/assets
```

## Personal repository

Anything that is yours alone (persona, extra code, extra packages) can live in a separate, private git repository that JARVIS pulls in, so it never ends up in the public source.

```bash
jarvis personal set git@github.com:YOU/jarvis-personal.git
jarvis personal pull           # update later
jarvis personal trust          # review and approve the current version
jarvis personal remove
```

Plugins and packages run code on your machine, and the persona changes how JARVIS behaves, so they only load for a version you approved. `set` and `pull` show which of those files changed and ask first. If the repository is new or changed, `jarvis` asks "Do you trust this computer and this folder?" before it starts; until you approve, it runs without them.

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
- **Other errors:** see `logs/debug.log` in the data folder. Yellow messages are AI provider or quota warnings, red ones are local errors.

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
pip install --require-hashes -r requirements.lock
pip install pyinstaller
python packaging/pyinstaller/build.py
```

Release builds install from `requirements.lock`, which pins every package to an exact version and hash. After changing `requirements.txt`, regenerate it:

```bash
uv pip compile requirements.txt --universal --generate-hashes --python-version 3.10 -o requirements.lock
```

This produces `dist/jarvis-<system>-<cpu>.tar.gz` (`.zip` on Windows) and a `.sha256` file. The `Build` workflow does this on all three systems, tests the result and the installer scripts, and the `Release` workflow attaches them to the release.

## Project layout

```
jarvis.py               launcher: setup, doctor, install/uninstall, tts and personal commands
jarvis.cmd              Windows shim for running from the source folder
core/                   AI provider clients, memory, search, browser, speech, TTS client, doctor
terminal/main.py        the chat interface
tts_server/             local Chatterbox TTS server and its pinned requirements
tests/                  smoke tests
.github/workflows/      CI, Build and Release pipelines
packaging/homebrew/     Homebrew formula
packaging/pyinstaller/  builds the standalone packages
install.sh, install.ps1 one-line installers
```

## License

MIT, see [LICENSE](LICENSE). The Chatterbox model that the TTS installer downloads is not part of this project; it is published by Resemble AI under the MIT license.
