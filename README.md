# JARVIS

A personal AI assistant for the terminal, powered by Google Gemini. Text chat, web search and browsing, long-term memory, voice input (speech-to-text) and optional spoken replies (text-to-speech).

JARVIS runs straight from the source code: the first launch creates its own private Python environment and installs every dependency by itself. You never run `pip install` yourself.

> Status: developed and tested on macOS (Apple Silicon). The Windows and Linux code paths are written but have not been tested on real machines yet. Please report anything that fails (details are in `debug.log`, see "Where things are stored").

## Requirements

- Python 3.10 or newer (on Windows tick "Add python.exe to PATH" in the installer)
- A Gemini API key, free at <https://aistudio.google.com/apikey>
- Internet access on first launch
- Optional: a microphone (`/talk`, `/mictest`), `git` (personal repository)
- Linux only: `sudo apt install libportaudio2` for the microphone, `python3-venv` if your distribution splits it out, and one of `paplay`/`aplay`/`ffplay` for spoken replies

## Install

### macOS with Homebrew

```bash
brew tap TugraYaka/octo-jarvis
brew install jarvis
jarvis
```

The formula template is in [`packaging/homebrew/jarvis.rb`](packaging/homebrew/jarvis.rb); publish it in a tap repository named `homebrew-octo-jarvis` under `Formula/`.

### From source (macOS, Linux, Windows)

```bash
git clone https://github.com/TugraYaka/octo-jarvis.git
cd octo-jarvis
python3 jarvis.py install      # Windows: py -3 jarvis.py install
```

`install` makes the `jarvis` command work in every terminal. On macOS and Linux it creates `~/.local/bin/jarvis` and, only after asking, adds that folder to your shell profile. On Windows it creates a `jarvis.cmd` launcher and adds it to your user PATH. Open a new terminal and type:

```bash
jarvis
```

You can also skip `install` and start it directly with `python3 jarvis.py`.

## First launch

1. JARVIS installs its dependencies (a few minutes, once).
2. If there is no Gemini API key yet, the chat asks for it before anything else. The key is stored in `config.json` inside the data folder, readable only by you. The `GEMINI_API_KEY` environment variable also works.
3. Google checks the key. A wrong key is rejected right away; a key that stops working later makes JARVIS answer with a red error because it cannot respond without it.
4. Type `/logout` at any time to delete the saved key and enter a new one.

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

If you already have a compatible environment, set `JARVIS_TTS_PYTHON` to its Python executable and JARVIS uses it instead (a `venv_tts` folder next to the source folder is also detected).

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

- **`models/tr_finetuned/`** must be a Coqui **XTTS v2** GPT fine-tune in the format produced by `TTS.demos.xtts_ft_demo` (TTS 0.22.0): `config.json` + `model.pth` + `vocab.json` + `speaker_ref.wav`. All four files are required; if one is missing the server says which and falls back. It is loaded with `Xtts.init_from_config` / `load_checkpoint`, generates 24 kHz mono audio, and the speaker embedding file (`speakers_xtts.pth`) is taken from the base XTTS v2 model that the installer downloads. It is used for Turkish (`tr`).
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

- **`python` is not recognized (Windows):** reinstall Python with "Add to PATH", or use `py -3`.
- **Dependency install fails:** check your connection and run `jarvis` again; it resumes.
- **Microphone errors:** check the OS microphone permission and the default input device; on Linux install `libportaudio2`.
- **No sound:** run `/voice`; if the server is off, `/turnontts`. On Linux install `pulseaudio-utils`, `alsa-utils` or `ffmpeg`.
- **Web browsing fails on Linux:** Chromium needs system libraries; run `sudo $HOME/.local/share/jarvis/venv/bin/python -m playwright install-deps chromium`.
- **Other errors:** see `logs/debug.log` in the data folder. Yellow messages are Gemini or quota warnings, red ones are local errors.

## Project layout

```
jarvis.py            launcher: environment setup, install/uninstall, tts and personal commands
jarvis.cmd           Windows shim for running from the source folder
core/                Gemini client, memory, search, browser, speech, TTS client
terminal/main.py     the chat interface
tts_server/          local XTTS server and its pinned requirements
packaging/homebrew/  Homebrew formula template
```

## License

MIT, see [LICENSE](LICENSE). The XTTS v2 voice model that the TTS installer downloads is not part of this project and has its own license (Coqui Public Model License, non-commercial use only).
