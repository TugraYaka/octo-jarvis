import os
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import config, paths, personal, ttsinstall

paths.ensure_dirs()
paths.apply_cache_env()


def _log_exception(context: str) -> None:
    try:
        with open(paths.DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n--- {context} ---\n")
            f.write(traceback.format_exc())
    except OSError:
        pass


from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, OptionList, Rule, RichLog, Static
from textual.widgets.option_list import Option

from core import stt
from core import tts
from core.client import is_auth_error, validate_key
from core.gemini_client import ask, get_thinking_level, set_thinking_level, warmup
from core.memory import reset_memory, list_memory, forget_memory
from core.search_mode import set_google_online, set_duck_online, is_google_online, is_duck_online
from core.stt import listen, listen_stream

BANNER = r"""
     ██╗  █████╗  ██████╗  ██╗   ██╗ ██╗ ███████╗
     ██║ ██╔══██╗ ██╔══██╗ ██║   ██║ ██║ ██╔════╝
     ██║ ███████║ ██████╔╝ ██║   ██║ ██║ ███████╗
██   ██║ ██╔══██║ ██╔══██╗ ╚██╗ ██╔╝ ██║ ╚════██║
╚█████╔╝ ██║  ██║ ██║  ██║  ╚████╔╝  ██║ ███████║
 ╚════╝  ╚═╝  ╚═╝ ╚═╝  ╚═╝   ╚═══╝   ╚═╝ ╚══════╝
""".strip("\n")

VERSION = "Prototype v2"

COMMANDS = [
    ("/turndefaults", "", "Reset to default settings"),
    ("/resetmemory", "", "Clear stored memory"),
    ("/listmemory", "", "List stored memory entries"),
    ("/forgetmemory", "<id>", "Remove one memory entry"),
    ("/resethistory", "", "Clear conversation history"),
    ("/think", "", "Show current thinking level"),
    ("/think high", "", "Set thinking level to high"),
    ("/think low", "", "Set thinking level to low"),
    ("/google", "", "Show Google search status"),
    ("/duckduck", "", "Show DuckDuckGo search status"),
    ("/onlinegoogle", "", "Enable Google search"),
    ("/offlinegoogle", "", "Disable Google search"),
    ("/onlineduckduck", "", "Enable DuckDuckGo search"),
    ("/offlineduckduck", "", "Disable DuckDuckGo search"),
    ("/voice", "", "Show voice and TTS server status"),
    ("/startertts", "", "Show TTS auto-start status"),
    ("/voiceon", "", "Enable spoken replies"),
    ("/voiceoff", "", "Disable spoken replies"),
    ("/turnontts", "", "Start the TTS server"),
    ("/turnofftts", "", "Stop the TTS server"),
    ("/installtts", "", "Download and install the TTS server"),
    ("/turnonstartertts", "", "Auto-start TTS on launch"),
    ("/turnoffstartertts", "", "Do not auto-start TTS on launch"),
    ("/speak", "<text>", "Speak text aloud"),
    ("/mictest", "", "Test microphone once"),
    ("/talk", "", "Voice conversation"),
    ("/logout", "", "Remove the saved Gemini API key"),
]


PROFILE_STEPS = [
    {
        "field": "name",
        "title": "Name:",
        "prompt": "Type your name...",
        "options": [("input", "Enter my name"), ("skip", "Prefer not to say")],
    },
    {
        "field": "age",
        "title": "Age:",
        "prompt": "Type your age (numbers only)...",
        "restrict": r"[0-9]*",
        "max_length": 3,
        "options": [("input", "Enter my age"), ("skip", "Prefer not to say")],
    },
    {
        "field": "gender",
        "title": "Gender:",
        "prompt": "Type your gender...",
        "options": [
            ("male", "Male"),
            ("female", "Female"),
            ("input", "Other: type it in"),
            ("skip", "Prefer not to say"),
        ],
    },
]


class JarvisApp(App):
    CSS = """
    Screen {
        align: center middle;
    }

    #splash {
        color: cyan;
        text-align: center;
        width: auto;
    }

    #chat {
        width: 100%;
        height: 100%;
        display: none;
    }

    #header {
        padding: 1 2 0 2;
        height: auto;
    }

    #log {
        border: none;
        padding: 0 2;
        height: 1fr;
        overflow-y: auto;
    }

    #bottom {
        width: 100%;
        height: auto;
    }

    #cmdlist {
        border: none;
        height: auto;
        max-height: 8;
        margin: 0 2;
        display: none;
    }

    #cmdlist > .option-list--option-highlighted {
        background: cyan;
        color: black;
        text-style: bold;
    }

    #cmdlist:focus > .option-list--option-highlighted {
        background: cyan;
        color: black;
    }

    #input {
        border: none;
        height: 1;
        padding: 0 1;
        margin: 0 2;
    }

    #footer {
        color: $text-muted;
        padding: 0 2;
        height: auto;
    }

    Rule {
        margin: 0 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.history: list = []
        self._navigated = False
        self._mode = None
        self._services_started = False
        self._installing_tts = False
        self._ask_lock = threading.Lock()
        self._profile_step = 0
        self._profile_sub = "choice"
        self.theme = "ansi-dark"

    def compose(self) -> ComposeResult:
        yield Static(BANNER, id="splash")
        with Vertical(id="chat"):
            yield Static(
                "[bold]JARVIS {version}[/bold]\n"
                "[dim]Gemini · thinking: {level}[/dim]\n"
                "[dim]{cwd}[/dim]".format(
                    version=VERSION, level=get_thinking_level(), cwd=os.getcwd()
                ),
                id="header",
            )
            yield RichLog(id="log", wrap=True, markup=True, highlight=False)
            with Vertical(id="bottom"):
                yield Rule()
                yield OptionList(id="cmdlist")
                yield Input(placeholder="Type a message...", id="input")
                yield Rule()
                yield Static(
                    "[dim]Type 'exit' to quit  ·  /think /speak /mictest /talk[/dim]",
                    id="footer",
                )

    def on_mount(self) -> None:
        self.on_mount_tts_errors()
        personal.load_plugins(
            self,
            lambda message: self.query_one("#log", RichLog).write(f"[yellow]{escape(message)}[/yellow]"),
        )
        if config.get_api_key():
            self._start_services()
        self.set_timer(1.5, self._show_chat)

    def _start_services(self) -> None:
        if self._services_started:
            return
        self._services_started = True
        self.run_worker(self._warm_up, thread=True)

    def on_mount_tts_errors(self) -> None:
        def handler(e: Exception) -> None:
            _log_exception("tts")
            log = self.query_one("#log", RichLog)
            self.call_from_thread(log.write, f"[red]TTS error ({escape(str(e))}). See debug.log[/red]")

        tts.on_error = handler

    def _autostart_tts(self) -> None:
        if tts.get_autostart() and tts.is_installed():
            tts.start_server()

    def _warm_up(self) -> None:
        for task in (self._autostart_tts, warmup, stt.warmup):
            try:
                task()
            except Exception:
                pass

    def _show_chat(self) -> None:
        self.query_one("#splash", Static).display = False
        self.query_one("#chat", Vertical).display = True
        self.query_one("#input", Input).focus()
        if config.get_api_key():
            self._continue_setup()
        else:
            self._prompt_for_key()

    def _prompt_for_key(self) -> None:
        log = self.query_one("#log", RichLog)
        self._mode = "key"
        inp = self.query_one("#input", Input)
        inp.password = True
        inp.placeholder = "Paste your Gemini API key..."
        self.query_one("#cmdlist", OptionList).display = False
        log.write("[yellow]●[/yellow] No Gemini API key found.")
        log.write(
            "[dim]Create a free key at https://aistudio.google.com/apikey and paste it below. "
            "It is stored only on this computer. Use /logout later to remove it.[/dim]"
        )

    def _verify_key(self) -> None:
        try:
            validate_key()
        except Exception as e:
            if is_auth_error(e):
                config.clear_api_key()
                self.call_from_thread(self._key_rejected)
                return
            _log_exception("key-verify")
            self.call_from_thread(
                self._key_accepted,
                f"Could not verify the key right now ({escape(str(e))}). "
                "It will be checked when you send a message.",
            )
            return
        self.call_from_thread(self._key_accepted, None)

    def _key_rejected(self) -> None:
        self._mode = "key"
        self.query_one("#log", RichLog).write(
            "[red]●[/red] [red]Google rejected that API key. Check it and paste it again.[/red]"
        )

    def _key_accepted(self, warning: str | None) -> None:
        log = self.query_one("#log", RichLog)
        self._mode = None
        inp = self.query_one("#input", Input)
        inp.password = False
        inp.placeholder = "Type a message..."
        log.write("[green]●[/green] API key saved.")
        if warning:
            log.write(f"[yellow]●[/yellow] {warning}")
        self._start_services()
        self._continue_setup()

    def _continue_setup(self) -> None:
        if config.profile_complete():
            self._offer_tts_install()
        else:
            self._profile_step = next(
                (i for i, step in enumerate(PROFILE_STEPS) if step["field"] not in config.get_profile()), 0
            )
            self._show_profile_choices()

    def _show_profile_choices(self) -> None:
        step = PROFILE_STEPS[self._profile_step]
        log = self.query_one("#log", RichLog)
        if self._profile_step == 0:
            log.write("[yellow]●[/yellow] Let me get to know you, sir. Use up/down and Enter.")
        log.write(f"[bold]{step['title']}[/bold]")
        self._mode = "profile"
        self._profile_sub = "choice"
        inp = self.query_one("#input", Input)
        inp.value = ""
        inp.placeholder = "Use up/down and Enter to choose..."
        cmdlist = self.query_one("#cmdlist", OptionList)
        cmdlist.clear_options()
        for key, label in step["options"]:
            cmdlist.add_option(Option(label, id=key))
        cmdlist.highlighted = 0
        cmdlist.display = True
        inp.focus()

    def _choose_profile_option(self, key: str) -> None:
        step = PROFILE_STEPS[self._profile_step]
        cmdlist = self.query_one("#cmdlist", OptionList)
        if key == "input":
            self._profile_sub = "text"
            cmdlist.display = False
            inp = self.query_one("#input", Input)
            inp.value = ""
            inp.placeholder = step["prompt"]
            inp.restrict = step.get("restrict")
            inp.max_length = step.get("max_length", 0)
            inp.focus()
            return
        self._save_profile_value(config.UNSPECIFIED if key == "skip" else key)

    def _save_profile_value(self, value) -> None:
        step = PROFILE_STEPS[self._profile_step]
        config.set_profile_field(step["field"], value)
        inp = self.query_one("#input", Input)
        inp.restrict = None
        inp.max_length = 0
        self.query_one("#cmdlist", OptionList).display = False
        self._profile_step += 1
        if self._profile_step < len(PROFILE_STEPS):
            self._show_profile_choices()
            return
        self._mode = None
        inp.placeholder = "Type a message..."
        self.query_one("#log", RichLog).write("[green]●[/green] Thank you, sir. Profile saved.")
        self._offer_tts_install()

    def _offer_tts_install(self, force: bool = False) -> None:
        if tts.is_installed() or self._installing_tts:
            return
        if not force and config.get("tts_install_declined"):
            return
        log = self.query_one("#log", RichLog)
        log.write("[yellow]●[/yellow] Spoken replies need the TTS server, which is not installed yet.")
        log.write(f"[dim]{ttsinstall.DOWNLOAD_NOTICE}[/dim]")
        log.write("Download and install it now? Type yes or no. (Run /installtts to do it later.)")
        self._mode = "tts_consent"

    def _handle_tts_consent(self, answer: str) -> None:
        log = self.query_one("#log", RichLog)
        if answer in ("yes", "y"):
            self._installing_tts = True
            log.write("[green]●[/green] Installing the TTS server. You can keep chatting meanwhile.")
            self.run_worker(self._install_tts, thread=True)
        else:
            config.set_value("tts_install_declined", True)
            log.write("[green]●[/green] Skipped. Voice stays off. Run /installtts any time to change that.")

    def _start_tts(self) -> None:
        try:
            tts.start_server()
        except Exception as e:
            _log_exception("tts-start")
            self.call_from_thread(
                self.query_one("#log", RichLog).write,
                f"[red]● Could not start the TTS server: {escape(str(e))} See debug.log[/red]",
            )

    def _install_tts(self) -> None:
        log = self.query_one("#log", RichLog)

        def progress(line: str) -> None:
            self.call_from_thread(log.write, f"[dim]{escape(line)}[/dim]")

        try:
            ttsinstall.install(progress)
        except Exception as e:
            _log_exception("tts-install")
            self.call_from_thread(
                log.write, f"[red]● TTS install failed: {escape(str(e))} See debug.log[/red]"
            )
            return
        finally:
            self._installing_tts = False
        config.set_value("tts_install_declined", None)
        tts.set_voice(True)
        self.call_from_thread(log.write, "[green]●[/green] TTS server installed. Starting it...")
        self._start_tts()
        model = os.path.join(ttsinstall.assets_dir(), "models", "tr_finetuned", "model.pth")
        if not os.path.isfile(model):
            self.call_from_thread(
                log.write,
                "[dim]Using the built-in default voice. For a custom voice model see the README.[/dim]",
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        cmdlist = self.query_one("#cmdlist", OptionList)
        value = event.value
        if self._mode == "profile" and self._profile_sub == "choice":
            if value:
                event.input.value = ""
            return
        self._navigated = False

        if self._mode is not None or not value.startswith("/"):
            cmdlist.display = False
            return

        query = value.lower().lstrip("/")
        matches = sorted(
            (c for c in COMMANDS if query in c[0].lstrip("/") or query in c[2].lower()),
            key=lambda c: not c[0].lstrip("/").startswith(query),
        )
        if not matches:
            cmdlist.display = False
            return

        cmdlist.clear_options()
        for cmd, args, desc in matches:
            label = f"{cmd} {args}".strip()
            cmdlist.add_option(Option(f"{label}  {desc}", id=cmd))
        cmdlist.highlighted = 0
        cmdlist.display = True

    def _select_command(self, cmd: str) -> None:
        args = next((a for c, a, _ in COMMANDS if c == cmd), "")
        inp = self.query_one("#input", Input)
        inp.value = f"{cmd} " if args else cmd
        inp.cursor_position = len(inp.value)
        self.query_one("#cmdlist", OptionList).display = False
        inp.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self._mode == "profile" and self._profile_sub == "choice":
            self._choose_profile_option(event.option.id)
            return
        self._select_command(event.option.id)

    def on_key(self, event) -> None:
        if event.key not in ("tab", "down", "up"):
            return
        cmdlist = self.query_one("#cmdlist", OptionList)
        if not cmdlist.display or not cmdlist.option_count:
            return

        event.stop()
        event.prevent_default()

        if self._mode == "profile" and event.key == "tab":
            return
        if event.key in ("up", "down"):
            self._navigated = True
        if event.key == "down":
            cmdlist.action_cursor_down()
            return
        if event.key == "up":
            cmdlist.action_cursor_up()
            return

        index = cmdlist.highlighted if cmdlist.highlighted is not None else 0
        option = cmdlist.get_option_at_index(index)
        self._select_command(option.id)

    def _write_user_line(self, text: str) -> None:
        log = self.query_one("#log", RichLog)
        width = log.size.width or 80
        line = Text(f" › {text} ", style="white on grey19")
        if len(line.plain) < width:
            line.append(" " * (width - len(line.plain)), style="on grey19")
        log.write(line)

    def _write_status(self, message: str) -> None:
        log = self.query_one("#log", RichLog)
        log.write(f"[dim]✳ {message}[/dim]")

    def _write_reply(self, reply: str, elapsed: float) -> None:
        log = self.query_one("#log", RichLog)
        dot = "red" if reply.startswith("[red]") else "yellow" if reply.startswith("[yellow]") else "green"
        body = reply if dot != "green" else escape(reply)
        log.write(f"[{dot}]●[/{dot}] {body}")
        stamp = time.strftime("%I:%M %p")
        log.write(f"[dim]✳ Replied in {elapsed:.1f}s · {stamp}[/dim]")
        log.write("")

    def _quit(self) -> None:
        tts.stop_server()
        self.exit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if self._mode == "profile":
            if self._profile_sub == "choice":
                cmdlist = self.query_one("#cmdlist", OptionList)
                if cmdlist.highlighted is not None:
                    self._choose_profile_option(cmdlist.get_option_at_index(cmdlist.highlighted).id)
                return
            if not text:
                return
            event.input.value = ""
            step = PROFILE_STEPS[self._profile_step]
            self._save_profile_value(int(text) if step["field"] == "age" else text)
            return
        if self._mode in ("key", "verifying"):
            event.input.value = ""
            if self._mode == "verifying" or not text:
                return
            if text.lower() in ("exit", "quit"):
                self._quit()
                return
            config.set_api_key(text)
            self._mode = "verifying"
            self._write_status("Checking API key...")
            self.run_worker(self._verify_key, thread=True)
            return
        cmdlist = self.query_one("#cmdlist", OptionList)
        if cmdlist.display and cmdlist.highlighted is not None:
            cmd = cmdlist.get_option_at_index(cmdlist.highlighted).id
            if cmd != text and (self._navigated or text.lower() not in {c[0] for c in COMMANDS}):
                self._select_command(cmd)
                return
        event.input.value = ""
        cmdlist.display = False
        if not text:
            return

        self._write_user_line(text)
        log = self.query_one("#log", RichLog)
        lowered = text.lower()

        if lowered in ("exit", "quit"):
            self._quit()
            return

        if self._mode == "tts_consent":
            self._mode = None
            if lowered in ("yes", "y", "no", "n"):
                self._handle_tts_consent(lowered)
                return
            log.write("[dim]Skipped for now. Run /installtts to install the TTS server.[/dim]")

        if lowered == "/logout":
            config.clear_api_key()
            self.history = []
            if config.env_api_key():
                log.write(
                    "[yellow]●[/yellow] Saved key removed, but the GEMINI_API_KEY environment "
                    "variable is still set and will keep being used. Unset it to log out fully."
                )
            else:
                log.write("[green]●[/green] Logged out. The saved API key was removed.")
                self._prompt_for_key()
            return

        if lowered == "/installtts":
            if tts.is_installed():
                log.write("[green]●[/green] TTS server is already installed.")
            elif self._installing_tts:
                log.write("[green]●[/green] TTS install is already running.")
            else:
                config.set_value("tts_install_declined", None)
                self._offer_tts_install(force=True)
            return

        if lowered in ("/turnontts", "/voiceon") and not tts.is_installed():
            log.write(
                "[red]●[/red] [red]The TTS server is not installed. Run /installtts first.[/red]"
            )
            return

        if lowered == "/turnontts":
            if tts.server_running() or tts._started_by_us:
                tts.set_server_disabled(False)
                log.write("[green]●[/green] TTS server already on.")
            else:
                self.run_worker(self._start_tts, thread=True)
                log.write("[green]●[/green] Starting TTS server...")
            return

        if lowered == "/turnofftts":
            tts.set_server_disabled(True)
            self.run_worker(lambda: tts.stop_server(force=True), thread=True)
            log.write("[green]●[/green] TTS server stopped.")
            return

        if lowered in ("/turnonstartertts", "/turnoffstartertts"):
            on = lowered == "/turnonstartertts"
            tts.set_autostart(on)
            log.write(f"[green]●[/green] TTS auto-start {'on' if on else 'off'}.")
            return

        if lowered == "/voice":
            up = tts.server_running() or tts._started_by_us
            log.write(
                f"[green]●[/green] Voice {'on' if tts.voice_enabled else 'off'}, "
                f"TTS server {'on' if up else 'off'}."
            )
            return

        if lowered == "/startertts":
            log.write(
                f"[green]●[/green] TTS auto-start {'on' if tts.get_autostart() else 'off'}."
            )
            return

        if lowered in ("/voiceon", "/voiceoff"):
            tts.set_voice(lowered == "/voiceon")
            if lowered == "/voiceoff":
                tts.clear()
            log.write(f"[green]●[/green] Voice {'on' if lowered == '/voiceon' else 'off'}.")
            return

        if lowered == "/turndefaults":
            set_google_online(True)
            set_duck_online(False)
            tts.set_autostart(True)
            tts.set_voice(True)
            log.write(
                "[green]●[/green] Defaults applied: Google on, DuckDuckGo off, "
                "TTS auto-start on, voice on."
            )
            return

        if lowered == "/resetmemory":
            reset_memory()
            log.write("[green]●[/green] Memory cleared.")
            return

        if lowered == "/listmemory":
            entries = list_memory()
            if not entries:
                log.write("[green]●[/green] Memory is empty.")
            else:
                for e in entries:
                    date = (
                        time.strftime("%Y-%m-%d", time.localtime(e["ts"]))
                        if e.get("ts") else "?"
                    )
                    log.write(f"[dim][{e['id']}] ({date}) {e['text']}[/dim]")
            return

        if lowered.startswith("/forgetmemory"):
            parts = text.split()
            if len(parts) != 2 or not parts[1].isdigit():
                log.write("[red]●[/red] [red]Usage: /forgetmemory <id>[/red]")
                return
            removed = forget_memory(int(parts[1]))
            log.write(f"[green]●[/green] {'Removed.' if removed else 'No memory with that id.'}")
            return

        if lowered == "/resethistory":
            self.history = []
            log.write("[green]●[/green] Conversation history cleared.")
            return

        if lowered in ("/think high", "/think low"):
            level = lowered.split()[1]
            set_thinking_level(level)
            log.write(f"[green]●[/green] Thinking level set to {level}.")
            return

        if lowered == "/think":
            log.write(f"[green]●[/green] Current thinking level is {get_thinking_level()}.")
            return

        if lowered == "/google":
            log.write(f"[green]●[/green] Google search {'online' if is_google_online() else 'offline'}.")
            return

        if lowered == "/duckduck":
            log.write(f"[green]●[/green] DuckDuckGo search {'online' if is_duck_online() else 'offline'}.")
            return

        if lowered == "/onlinegoogle":
            log.write(f"[green]●[/green] {set_google_online(True)}")
            return

        if lowered == "/offlinegoogle":
            log.write(f"[green]●[/green] {set_google_online(False)}")
            return

        if lowered == "/onlineduckduck":
            log.write(f"[green]●[/green] {set_duck_online(True)}")
            return

        if lowered == "/offlineduckduck":
            log.write(f"[green]●[/green] {set_duck_online(False)}")
            return

        if lowered.startswith("/speak "):
            speech_text = text[len("/speak "):].strip()
            if not speech_text:
                log.write("[red]●[/red] [red]Usage: /speak <text>[/red]")
                return
            log.write("[dim]Speaking...[/dim]")
            tts.speak(speech_text, lang="tr")
            return

        if lowered == "/mictest":
            log.write("[dim]Listening... (speak now, pause when done)[/dim]")
            self.run_worker(self._mictest, thread=True)
            return

        if lowered == "/talk":
            log.write("[dim]Listening... (speak now, pause when done)[/dim]")
            self.run_worker(self._talk, thread=True)
            return

        self.run_worker(lambda: self._ask_and_reply(text), thread=True)

    def _speak(self, speech_text: str) -> None:
        log = self.query_one("#log", RichLog)
        try:
            tts.speak(speech_text, lang="tr")
        except Exception as e:
            self.call_from_thread(log.write, f"[green]●[/green] TTS error ({escape(str(e))}).")

    def _prepare_stt(self, log) -> None:
        if not stt.is_cached():
            self.call_from_thread(log.write, "[dim]Downloading the speech model (one time, about 460 MB)...[/dim]")
        stt.load()

    def _mictest(self) -> None:
        log = self.query_one("#log", RichLog)
        try:
            self._prepare_stt(log)
            text, language = listen()
        except Exception as e:
            _log_exception("mictest")
            self.call_from_thread(log.write, f"[red]● Microphone error ({escape(str(e))}). See debug.log[/red]")
            return
        if not text:
            self.call_from_thread(log.write, "[green]●[/green] No speech detected.")
        else:
            self.call_from_thread(log.write, f"[dim][{language}][/dim] {text}")

    def _talk(self) -> None:
        log = self.query_one("#log", RichLog)
        parts: list = []
        try:
            self._prepare_stt(log)
            for chunk, _ in listen_stream():
                parts.append(chunk)
                self.call_from_thread(log.write, f"[dim]· {chunk}[/dim]")
        except Exception as e:
            _log_exception("talk")
            self.call_from_thread(log.write, f"[red]● Microphone error ({escape(str(e))}). See debug.log[/red]")
            return
        full_text = " ".join(parts).strip()
        if not full_text:
            self.call_from_thread(log.write, "[green]●[/green] No speech detected.")
            return
        self._ask_and_reply(full_text)

    def _ask_and_reply(self, prompt: str) -> None:
        if not self._ask_lock.acquire(blocking=False):
            self.call_from_thread(self._write_status, "Waiting for the previous reply...")
            self._ask_lock.acquire()
        try:
            self._ask_and_reply_locked(prompt)
        finally:
            self._ask_lock.release()

    def _ask_and_reply_locked(self, prompt: str) -> None:
        log = self.query_one("#log", RichLog)
        if tts.voice_enabled:
            if tts.server_disabled or (not tts._started_by_us and not tts.server_running()):
                self.call_from_thread(
                    log.write,
                    "[red]●[/red] [red]TTS server is off. Run /turnontts to start it, or /voiceoff.[/red]",
                )
                return
            if not tts.is_ready():
                self.call_from_thread(log.write, "[dim]Waiting for TTS server...[/dim]")
                try:
                    tts.wait_until_ready()
                except Exception as e:
                    _log_exception("tts-wait")
                    self.call_from_thread(
                        log.write, f"[red]● TTS server error ({escape(str(e))}). See debug.log[/red]"
                    )
                    return
        start = time.monotonic()

        searched = False

        def on_status(message: str) -> None:
            nonlocal searched
            if message.startswith("Searching about"):
                if searched:
                    return
                searched = True
            self.call_from_thread(self._write_status, message)

        try:
            reply, self.history = ask(prompt, self.history, on_status=on_status)
        except Exception as e:
            reply = f"[yellow](Something went wrong: {escape(str(e))})[/yellow]"
        elapsed = time.monotonic() - start
        self.call_from_thread(self._write_reply, reply, elapsed)
        try:
            is_notice = reply.startswith(("[red]", "[yellow]"))
            tts.speak(Text.from_markup(reply).plain if is_notice else reply, lang="tr")
        except Exception as e:
            _log_exception("auto-speak")
            self.call_from_thread(
                self.query_one("#log", RichLog).write,
                f"[red]TTS error ({escape(str(e))}). See debug.log[/red]",
            )


def main() -> None:
    # Force tqdm's multiprocessing lock to be created now, in the normal
    # terminal, before Textual puts the terminal into raw mode. Creating it
    # later from a worker thread while Textual owns the terminal crashes
    # with "bad value(s) in fds_to_keep" (Python 3.14 + Textual's fd setup).
    from tqdm import tqdm

    os.environ["PYTHONWARNINGS"] = "ignore:resource_tracker:UserWarning"
    tqdm.get_lock()

    try:
        JarvisApp().run()
    finally:
        tts.stop_server()
        _shutdown()


def _shutdown() -> None:
    import threading

    from core import browser

    def _close_browsers() -> None:
        for fn in (browser.browser_close, browser.browser_close_live):
            try:
                fn()
            except Exception:
                pass

    closer = threading.Thread(target=_close_browsers, daemon=True)
    closer.start()
    closer.join(timeout=5)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
