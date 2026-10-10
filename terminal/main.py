import os
import subprocess
import sys
import threading
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import assistant, chats, config, paths, personal, ttsinstall

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
from textual.theme import Theme
from textual.widgets import Input, OptionList, Rule, RichLog, Static
from textual.widgets.option_list import Option

from core import stt
from core import tts
from core import llm
from core.llm import ask, get_reply_lang, get_thinking_level, is_auth_error, set_thinking_level, validate_key, warmup
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

TAGLINE = "Just A Rather Very Intelligent System"

JARVIS_THEMES = [
    Theme(
        name="jarvis-dark",
        primary="#38D9F5",
        secondary="#1E88B4",
        accent="#7FE7FF",
        warning="#F5C542",
        error="#FF5A5F",
        success="#3DDC97",
        foreground="#D6F4FF",
        background="#0A1420",
        surface="#0F1C2B",
        panel="#132538",
        dark=True,
    ),
    Theme(
        name="jarvis-light",
        primary="#0B6FA4",
        secondary="#2C4A63",
        accent="#0095C8",
        warning="#B7791F",
        error="#C53030",
        success="#2F855A",
        foreground="#13202B",
        background="#F4F8FB",
        surface="#E8F0F6",
        panel="#DCE7EF",
        dark=False,
    ),
]

DIFF_COLORS = {
    ("standard", True): ("#4a1014", "#123f22", "#ff9b9b", "#8af0ae"),
    ("standard", False): ("#ffd7d7", "#d4f5dc", "#b42318", "#1e7a3c"),
    ("colorblind", True): ("#4a3300", "#0c3256", "#ffb347", "#7cc0ff"),
    ("colorblind", False): ("#ffe2b8", "#cfe6ff", "#a85a00", "#0b5cad"),
}

THEME_CHOICES = [
    ("auto", "Auto (match terminal)", None, "standard"),
    ("dark", "Dark mode", "jarvis-dark", "standard"),
    ("light", "Light mode", "jarvis-light", "standard"),
    ("dark-cb", "Dark mode (colorblind-friendly)", "jarvis-dark", "colorblind"),
    ("light-cb", "Light mode (colorblind-friendly)", "jarvis-light", "colorblind"),
    ("ansi-dark", "Dark mode (ANSI colors only)", "ansi-dark", "standard"),
    ("ansi-light", "Light mode (ANSI colors only)", "ansi-light", "standard"),
]

COMMANDS = [
    ("/turndefaults", "", "Reset to default settings"),
    ("/resetmemory", "", "Clear stored memory"),
    ("/listmemory", "", "List stored memory entries"),
    ("/forgetmemory", "<id>", "Remove one memory entry"),
    ("/resethistory", "", "Clear conversation history"),
    ("/chats", "", "Browse and reopen past chats"),
    ("/newchat", "", "Start a new chat"),
    ("/deletechat", "", "Delete the current chat from chat history"),
    ("/think", "", "Choose the thinking level"),
    ("/search", "", "Choose the search engine (provider's own, DuckDuckGo or off)"),
    ("/voice", "", "Show voice and TTS server status"),
    ("/addvoice", "", "Open your personal voice folder to add a custom voice"),
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
    ("/theme", "", "Change the display theme"),
    ("/provider", "", "Choose the AI: Gemini, Claude, ChatGPT or a custom server"),
    ("/model", "", "Choose the model of the active AI"),
    ("/baseurl", "<url>", "Change the custom server URL"),
    ("/setkey", "", "Enter an API key for the active provider"),
    ("/logout", "", "Remove the saved API key of the active provider"),
]


PROVIDER_HINTS = {
    "gemini": "Google",
    "claude": "Anthropic",
    "openai": "OpenAI",
    "custom": "local or third-party server",
}
CUSTOM_PRESETS = [
    ("http://localhost:11434/v1", "Ollama  ·  http://localhost:11434/v1"),
    ("http://localhost:1234/v1", "LM Studio  ·  http://localhost:1234/v1"),
    ("other", "Other server  ·  type its URL (OpenRouter, Groq, ...)"),
]
MENU_PLACEHOLDER = "Use up/down and Enter to choose, Esc to cancel..."


KEY_URLS = {
    "gemini": "https://aistudio.google.com/apikey",
    "claude": "https://console.anthropic.com/settings/keys",
    "openai": "https://platform.openai.com/api-keys",
}


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


CONFIRM_TIMEOUT_S = 120


class JarvisApp(App):
    CSS = """
    Screen {
        align: center middle;
    }

    #themepreview {
        margin: 0 2;
        padding: 0 1;
        height: auto;
        border: round $primary;
        display: none;
    }

    #splash {
        color: $primary;
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
        background: $primary;
        color: auto;
        text-style: bold;
    }

    #cmdlist:focus > .option-list--option-highlighted {
        background: $primary;
        color: auto;
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
        self._confirm = None
        self._menu = None
        self._chat_id = chats.new_id()
        self._theme_first_run = False
        for theme in JARVIS_THEMES:
            self.register_theme(theme)
        self._apply_theme(config.get("theme") or "auto")

    def compose(self) -> ComposeResult:
        yield Static(f"{BANNER}\n\n[dim]{TAGLINE}[/dim]", id="splash")
        with Vertical(id="chat"):
            yield Static(
                self._header_text(),
                id="header",
            )
            yield RichLog(id="log", wrap=True, markup=True, highlight=False)
            with Vertical(id="bottom"):
                yield Rule()
                yield Static(id="themepreview")
                yield OptionList(id="cmdlist")
                yield Input(placeholder="Type a message...", id="input")
                yield Rule()
                yield Static(
                    "[dim]Type 'exit' to quit  ·  /provider /model /search /think /theme /talk[/dim]",
                    id="footer",
                )

    def _header_text(self) -> str:
        return "[bold $primary]◆ J.A.R.V.I.S.[/] [bold]{version}[/bold]\n[dim]{model} · thinking: {level}[/dim]\n[dim]{cwd}[/dim]".format(
            version=paths.VERSION, model=escape(llm.label()), level=llm.thinking_label(), cwd=os.getcwd()
        )

    def _enable_native_search(self) -> None:
        if llm.provider() == "custom" or is_google_online():
            self._use_search("native")
            return
        self._mode = "search_consent"
        self.query_one("#log", RichLog).write(
            f"[yellow]●[/yellow] {self._native_search_label()} may be limited by quotas or billed per search. "
            "Do you want to continue? (yes/no)"
        )

    def _use_search(self, engine: str) -> None:
        set_google_online(engine == "native")
        set_duck_online(engine == "duck")
        name = {"native": self._native_search_label(), "duck": "DuckDuckGo (free)", "off": "off, no internet"}[engine]
        self.query_one("#log", RichLog).write(f"[green]●[/green] Search: {name}.")

    def _show_menu(self, title: str, options: list, on_choose, current=None) -> None:
        self._menu = on_choose
        self._mode = "menu"
        self.query_one("#log", RichLog).write(f"[bold]{escape(title)}[/bold]")
        cmdlist = self.query_one("#cmdlist", OptionList)
        cmdlist.clear_options()
        for key, label in options:
            cmdlist.add_option(Option(f"{'✔ ' if key == current else '  '}{label}", id=key))
        cmdlist.highlighted = next((i for i, (key, _) in enumerate(options) if key == current), 0)
        cmdlist.display = True
        inp = self.query_one("#input", Input)
        inp.value = ""
        inp.placeholder = MENU_PLACEHOLDER
        inp.focus()

    def _close_menu(self, choice: str | None) -> None:
        on_choose, self._menu = self._menu, None
        self._mode = None
        self.query_one("#cmdlist", OptionList).display = False
        self.query_one("#input", Input).placeholder = "Type a message..."
        if choice is None or on_choose is None:
            self.query_one("#log", RichLog).write("[dim]Unchanged.[/dim]")
            return
        on_choose(choice)

    def _prefill(self, value: str) -> None:
        inp = self.query_one("#input", Input)
        inp.value = value
        inp.cursor_position = len(value)
        inp.focus()

    def _provider_menu(self) -> None:
        options = []
        for name, info in config.PROVIDERS.items():
            state = escape(config.provider_model(name) or "") if config.provider_ready(name) else "needs setup"
            options.append((name, f"{info['label']}  ·  {PROVIDER_HINTS[name]}  ·  {state}"))
        self._show_menu("Which AI should JARVIS use? Memory is shared by all of them.",
                        options, self._switch_provider, current=llm.provider())

    def _switch_provider(self, name: str) -> None:
        log = self.query_one("#log", RichLog)
        config.set_provider(name)
        self._refresh_header()
        log.write(f"[green]●[/green] Now using {escape(llm.label())}. Memory and history are kept.")
        if name != "custom" and is_google_online():
            log.write(
                f"[yellow]●[/yellow] {self._native_search_label()} is on and may be limited by quotas "
                "or billed. Use /search to switch to free DuckDuckGo."
            )
        if config.provider_ready(name):
            self._start_services()
        elif name == "custom":
            self._custom_setup()
        else:
            self._prompt_for_key()

    def _custom_setup(self) -> None:
        def choose(url: str) -> None:
            if url == "other":
                self.query_one("#log", RichLog).write(
                    "[dim]Type the server URL after /baseurl, e.g. /baseurl https://openrouter.ai/api/v1[/dim]"
                )
                self._prefill("/baseurl ")
                return
            config.set_provider_value("custom", "base_url", url)
            self._model_menu()

        self._show_menu("Where is the custom server running?", CUSTOM_PRESETS, choose,
                        current=config.provider_base_url("custom"))

    def _model_menu(self) -> None:
        self._write_status("Looking up available models...")
        self.run_worker(self._load_models, thread=True)

    def _load_models(self) -> None:
        name = llm.provider()
        try:
            models = llm.list_models(name)
        except Exception as e:
            _log_exception("list-models")
            models = []
            if is_auth_error(e) and name != "gemini":
                self.call_from_thread(
                    self.query_one("#log", RichLog).write,
                    "[yellow]●[/yellow] The server needs an API key. Use /setkey, then /model.",
                )
        self.call_from_thread(self._show_model_menu, models)

    def _show_model_menu(self, models: list[str]) -> None:
        current = config.provider_model(llm.provider())
        if current and current not in models:
            models = [current] + models
        if not models:
            self.query_one("#log", RichLog).write(
                "[dim]Couldn't list the models. Type the model name after /model.[/dim]"
            )
            self._prefill("/model ")
            return

        def choose(model: str) -> None:
            if model == "__other__":
                self._prefill("/model ")
                return
            self._set_model(model)

        options = [(m, escape(m)) for m in models] + [("__other__", "Other  ·  type a model name")]
        self._show_menu(f"Choose the {config.PROVIDERS[llm.provider()]['label']} model:", options, choose, current=current)

    def _set_model(self, model: str) -> None:
        log = self.query_one("#log", RichLog)
        name = llm.provider()
        if not model:
            self._model_menu()
            return
        config.set_provider_value(name, "model", model)
        self._refresh_header()
        log.write(f"[green]●[/green] Model set to {escape(llm.label())}.")
        if config.provider_ready(name):
            self._start_services()

    def _search_menu(self) -> None:
        native_hint = (
            "uses the model's own search if it has one" if llm.provider() == "custom"
            else "may be limited by quotas or billed per search"
        )
        options = [
            ("native", f"{self._native_search_label()}  ·  {native_hint}"),
            ("duck", "DuckDuckGo  ·  free, with web page browsing"),
            ("off", "Off  ·  no internet"),
        ]
        current = "native" if is_google_online() else "duck" if is_duck_online() else "off"

        def choose(engine: str) -> None:
            if engine == "native":
                self._enable_native_search()
            else:
                self._use_search(engine)

        self._show_menu("How should JARVIS search the web?", options, choose, current=current)

    def _think_menu(self) -> None:
        if not llm.thinking_supported():
            self.query_one("#log", RichLog).write(
                f"[yellow]●[/yellow] {escape(llm.label())} manages its own thinking; there is nothing to set."
            )
            return

        def choose(level: str) -> None:
            set_thinking_level(level)
            self._refresh_header()
            self.query_one("#log", RichLog).write(f"[green]●[/green] Thinking level set to {level}.")

        self._show_menu("How hard should JARVIS think?", [
            ("low", "Low  ·  fast, short answers"),
            ("high", "High  ·  deeper reasoning, slower"),
        ], choose, current=get_thinking_level())

    def _native_search_label(self) -> str:
        return config.PROVIDERS[llm.provider()]["search"]

    def _refresh_header(self) -> None:
        self.query_one("#header", Static).update(self._header_text())

    def on_mount(self) -> None:
        self.on_mount_tts_errors()
        assistant.set_confirm_handler(self._confirm_from_worker)
        personal.load_plugins(
            self,
            lambda message: self.query_one("#log", RichLog).write(f"[yellow]{escape(message)}[/yellow]"),
        )
        if config.provider_ready(llm.provider()):
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
        if config.get("theme") is None:
            self._show_theme_picker(first_run=True)
            return
        self._after_theme_setup()

    def _after_theme_setup(self) -> None:
        if config.provider_ready(llm.provider()):
            self._continue_setup()
        else:
            self._prompt_for_key()

    def _detect_dark_terminal(self) -> bool:
        fgbg = os.environ.get("COLORFGBG", "")
        if fgbg:
            return fgbg.rsplit(";", 1)[-1] not in ("7", "15")
        if sys.platform == "darwin":
            try:
                out = subprocess.run(
                    ["defaults", "read", "-g", "AppleInterfaceStyle"],
                    capture_output=True, text=True, timeout=2,
                )
            except (OSError, subprocess.SubprocessError):
                return True
            return "dark" in out.stdout.lower()
        return True

    def _theme_choice(self, key: str) -> tuple:
        return next((c for c in THEME_CHOICES if c[0] == key), THEME_CHOICES[0])

    def _apply_theme(self, key: str) -> None:
        _, _, theme, palette = self._theme_choice(key)
        if theme is None:
            theme = "jarvis-dark" if self._detect_dark_terminal() else "jarvis-light"
        self.theme = theme
        self._diff_palette = palette

    def _theme_preview(self) -> Text:
        dark = self.current_theme.dark
        del_bg, add_bg, del_fg, add_fg = DIFF_COLORS[(self._diff_palette, dark)]
        keyword = f"bold {self.current_theme.primary}"
        out = Text()
        out.append("◆ Display calibration preview\n\n", style="bold")
        out.append(" 1   ", style="dim")
        out.append("def ", style=keyword)
        out.append("greet():\n")
        for sign, word, fg, bg in (("-", "World", del_fg, del_bg), ("+", "Jarvis", add_fg, add_bg)):
            row = Text(f" 2 {sign}     ", style=fg)
            row.append("print")
            row.append('("Hello ')
            row.append(word, style="bold")
            row.append('")')
            row.append(" " * max(0, 44 - len(row.plain)))
            row.stylize(f"on {bg}")
            out.append_text(row)
            out.append("\n")
        out.append(" 3   ", style="dim")
        out.append("greet()")
        return out

    def _show_theme_picker(self, first_run: bool = False) -> None:
        self._theme_first_run = first_run
        self._mode = "theme"
        log = self.query_one("#log", RichLog)
        if first_run:
            log.write("[bold]◆ Good day, sir. Let's calibrate the display first.[/bold]")
        log.write("[dim]Pick the look that suits your terminal. Up/down to preview, Enter to confirm, Esc to cancel.[/dim]")
        current = config.get("theme") or "auto"
        cmdlist = self.query_one("#cmdlist", OptionList)
        cmdlist.clear_options()
        for key, label, _, _ in THEME_CHOICES:
            mark = "✔ " if key == current else "  "
            cmdlist.add_option(Option(f"{mark}{label}", id=key))
        cmdlist.highlighted = next(i for i, c in enumerate(THEME_CHOICES) if c[0] == current)
        cmdlist.display = True
        preview = self.query_one("#themepreview", Static)
        preview.update(self._theme_preview())
        preview.display = True
        inp = self.query_one("#input", Input)
        inp.value = ""
        inp.placeholder = "Use up/down to preview, Enter to choose..."
        inp.focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if self._mode != "theme" or event.option.id is None:
            return
        self._apply_theme(event.option.id)
        self.query_one("#themepreview", Static).update(self._theme_preview())

    def _close_theme_picker(self, key: str | None) -> None:
        first_run = self._theme_first_run
        if key is None and first_run:
            key = "auto"
        if key is not None:
            config.set_value("theme", key)
        self._apply_theme(config.get("theme") or "auto")
        self._mode = None
        self.query_one("#cmdlist", OptionList).display = False
        self.query_one("#themepreview", Static).display = False
        self.query_one("#input", Input).placeholder = "Type a message..."
        log = self.query_one("#log", RichLog)
        if key is None:
            log.write("[dim]Theme unchanged.[/dim]")
        else:
            log.write(
                f"[green]●[/green] Display set to {escape(self._theme_choice(key)[1])}. "
                "Change it any time with /theme."
            )
        if first_run:
            self._theme_first_run = False
            self._after_theme_setup()

    def _prompt_for_key(self) -> None:
        log = self.query_one("#log", RichLog)
        name = llm.provider()
        label = config.PROVIDERS[name]["label"]
        if name == "custom" and not config.provider_ready(name):
            self._custom_setup()
            return
        self._mode = "key"
        inp = self.query_one("#input", Input)
        inp.password = True
        inp.placeholder = f"Paste your {label} API key..."
        self.query_one("#cmdlist", OptionList).display = False
        log.write("[yellow]●[/yellow] Enter the API key.")
        log.write(
            f"[dim]Get a key at {KEY_URLS.get(name, 'your provider')} and paste it below. "
            "It is stored only on this computer. Use /logout later to remove it, "
            "or type 'cancel' to switch provider instead.[/dim]"
        )

    def _verify_key(self) -> None:
        try:
            validate_key()
        except Exception as e:
            if is_auth_error(e):
                config.set_provider_api_key(llm.provider(), None)
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
            f"[red]●[/red] [red]{config.PROVIDERS[llm.provider()]['label']} rejected that API key. "
            "Check it and paste it again.[/red]"
        )

    def _end_key_mode(self) -> None:
        self._mode = None
        inp = self.query_one("#input", Input)
        inp.password = False
        inp.placeholder = "Type a message..."

    def _key_accepted(self, warning: str | None) -> None:
        log = self.query_one("#log", RichLog)
        self._end_key_mode()
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
        voice = ttsinstall.custom_voice()
        if not voice:
            self.call_from_thread(
                log.write,
                "[dim]Using the built-in default voice. For a custom voice model see the README.[/dim]",
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        cmdlist = self.query_one("#cmdlist", OptionList)
        value = event.value
        if (self._mode == "profile" and self._profile_sub == "choice") or self._mode in ("chats", "theme", "menu"):
            if value:
                event.input.value = ""
            return
        self._navigated = False

        if self._mode == "key":
            # API keys never start with "/", so show typed commands in clear text.
            event.input.password = not value.startswith("/")
        if self._mode not in (None, "key") or not value.startswith("/"):
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
        if self._mode == "chats":
            self._open_chat(event.option.id)
            return
        if self._mode == "theme":
            self._close_theme_picker(event.option.id)
            return
        if self._mode == "menu":
            self._close_menu(event.option.id)
            return
        self._select_command(event.option.id)

    def on_key(self, event) -> None:
        if event.key == "escape" and self._mode == "chats":
            self._close_chat_picker()
            return
        if event.key == "escape" and self._mode == "theme":
            self._close_theme_picker(None)
            return
        if event.key == "escape" and self._mode == "menu":
            self._close_menu(None)
            return
        if event.key not in ("tab", "down", "up"):
            return
        cmdlist = self.query_one("#cmdlist", OptionList)
        if not cmdlist.display or not cmdlist.option_count:
            return

        event.stop()
        event.prevent_default()

        if self._mode in ("profile", "chats", "theme", "menu") and event.key == "tab":
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
        bg = "grey19" if self.current_theme.dark else "grey85"
        fg = "white" if self.current_theme.dark else "black"
        line = Text(f" › {text} ", style=f"{fg} on {bg}")
        if len(line.plain) < width:
            line.append(" " * (width - len(line.plain)), style=f"on {bg}")
        log.write(line)

    def _write_status(self, message: str) -> None:
        log = self.query_one("#log", RichLog)
        log.write(f"[dim]✳ {message}[/dim]")

    def _write_reply(self, reply: str, elapsed: float) -> None:
        log = self.query_one("#log", RichLog)
        if isinstance(reply, assistant.Notice):
            dot = "red" if reply.startswith("[red]") else "yellow"
            body = reply
        else:
            dot, body = "green", escape(reply)
        log.write(f"[{dot}]●[/{dot}] {body}")
        stamp = time.strftime("%I:%M %p")
        log.write(f"[dim]✳ Replied in {elapsed:.1f}s · {stamp}[/dim]")
        log.write("")

    def _show_chat_picker(self) -> None:
        log = self.query_one("#log", RichLog)
        past = chats.list_chats()
        if not past:
            log.write("[green]●[/green] No saved chats yet.")
            return
        cmdlist = self.query_one("#cmdlist", OptionList)
        cmdlist.clear_options()
        for chat in past:
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(chat.get("updated", 0)))
            count = len(chat["messages"]) // 2
            current = "  (current)" if chat.get("id") == self._chat_id else ""
            cmdlist.add_option(
                Option(Text(f"{stamp}  {chat.get('title', '')}  · {count} msg{current}"), id=chat["id"])
            )
        cmdlist.highlighted = 0
        cmdlist.display = True
        self._mode = "chats"
        inp = self.query_one("#input", Input)
        inp.value = ""
        inp.placeholder = "Use up/down and Enter to open a chat, Esc to cancel..."
        inp.focus()
        log.write("[dim]Choose a chat to reopen.[/dim]")

    def _close_chat_picker(self) -> None:
        self._mode = None
        self.query_one("#cmdlist", OptionList).display = False
        self.query_one("#input", Input).placeholder = "Type a message..."

    def _open_chat(self, chat_id: str) -> None:
        self._close_chat_picker()
        log = self.query_one("#log", RichLog)
        chat = chats.load(chat_id)
        if chat is None:
            log.write("[yellow]●[/yellow] That chat could not be loaded.")
            return
        log.clear()
        log.write(f"[dim]✳ Reopened chat: {escape(chat.get('title', ''))}[/dim]")
        log.write("")
        for msg in chat["messages"]:
            if msg.get("role") == "user":
                self._write_user_line(msg.get("text", ""))
                continue
            log.write(f"[green]●[/green] {escape(msg.get('text', ''))}")
            stamp = time.strftime("%Y-%m-%d %I:%M %p", time.localtime(msg.get("time", 0)))
            log.write(f"[dim]✳ {stamp}[/dim]")
            log.write("")
        self._chat_id = chat_id
        self.history = assistant.trim_history(
            [{"role": m["role"], "text": m["text"]} for m in chat["messages"] if m.get("role") and "text" in m]
        )

    def _start_new_chat(self) -> None:
        self._chat_id = chats.new_id()
        self.history = []
        log = self.query_one("#log", RichLog)
        log.clear()
        log.write("[green]●[/green] New chat started.")

    def _quit(self) -> None:
        tts.stop_server()
        self.exit()

    def _confirm_from_worker(self, question: str) -> bool:
        state = {"event": threading.Event(), "answer": False, "prev_mode": None}
        self.call_from_thread(self._begin_confirm, question, state)
        if not state["event"].wait(CONFIRM_TIMEOUT_S):
            self.call_from_thread(self._finish_confirm, False, timed_out=True)
        return state["answer"]

    def _begin_confirm(self, question: str, state: dict) -> None:
        state["prev_mode"] = self._mode
        self._confirm = state
        self._mode = "confirm"
        self.query_one("#log", RichLog).write(f"[bold yellow]?[/bold yellow] {escape(question)} [dim](y/n)[/dim]")
        self._write_status("Waiting for your answer (y/n)...")

    def _finish_confirm(self, answer: bool, timed_out: bool = False) -> None:
        state = self._confirm
        if state is None:
            return
        self._confirm = None
        self._mode = state["prev_mode"]
        state["answer"] = answer
        note = "No answer, denied." if timed_out else ("Allowed." if answer else "Denied.")
        self.query_one("#log", RichLog).write(f"[dim]{note}[/dim]")
        state["event"].set()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if self._mode == "confirm":
            event.input.value = ""
            self._finish_confirm(text.lower() in ("y", "yes", "e", "evet"))
            return
        if self._mode == "theme":
            cmdlist = self.query_one("#cmdlist", OptionList)
            if cmdlist.highlighted is not None:
                self._close_theme_picker(cmdlist.get_option_at_index(cmdlist.highlighted).id)
            return
        if self._mode == "chats":
            cmdlist = self.query_one("#cmdlist", OptionList)
            if cmdlist.highlighted is not None:
                self._open_chat(cmdlist.get_option_at_index(cmdlist.highlighted).id)
            return
        if self._mode == "menu":
            cmdlist = self.query_one("#cmdlist", OptionList)
            if cmdlist.highlighted is not None:
                self._close_menu(cmdlist.get_option_at_index(cmdlist.highlighted).id)
            return
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
        if self._mode == "key" and text.startswith("/"):
            self._end_key_mode()
        if self._mode in ("key", "verifying"):
            event.input.value = ""
            if self._mode == "verifying" or not text:
                return
            if text.lower() in ("exit", "quit"):
                self._quit()
                return
            if text.lower() == "cancel":
                self._end_key_mode()
                self.query_one("#log", RichLog).write(
                    "[dim]Key entry cancelled. Use /provider to pick another AI.[/dim]"
                )
                return
            config.set_provider_api_key(llm.provider(), text)
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

        if self._mode == "search_consent":
            self._mode = None
            if lowered in ("yes", "y"):
                self._use_search("native")
                return
            log.write(f"[dim]{self._native_search_label()} left unchanged.[/dim]")
            return

        if lowered == "/logout":
            name = llm.provider()
            config.set_provider_api_key(name, None)
            if config.provider_env_key(name):
                log.write(
                    f"[yellow]●[/yellow] Saved key removed, but the {config.PROVIDERS[name]['env']} "
                    "environment variable is still set and will keep being used. Unset it to log out fully."
                )
            else:
                log.write("[green]●[/green] Logged out. The saved API key was removed.")
                if not config.provider_ready(name):
                    self._prompt_for_key()
            return

        if lowered == "/theme":
            self._show_theme_picker()
            return

        if lowered == "/provider":
            self._provider_menu()
            return

        if lowered.startswith("/provider "):
            name = lowered.split(None, 1)[1].strip()
            if name not in config.PROVIDERS:
                log.write("[red]●[/red] [red]Unknown provider. Use gemini, claude, openai or custom.[/red]")
                return
            self._switch_provider(name)
            return

        if lowered == "/model":
            self._model_menu()
            return

        if lowered.startswith("/model "):
            self._set_model(text[len("/model"):].strip())
            return

        if lowered == "/baseurl" or lowered.startswith("/baseurl "):
            url = text[len("/baseurl"):].strip()
            if url.endswith(" --allow-lan-http"):
                url = url[: -len(" --allow-lan-http")].strip()
                config.set_value("allow_lan_http", True)
            if not url.startswith(("http://", "https://")):
                log.write("[red]●[/red] [red]Usage: /baseurl http://localhost:11434/v1[/red]")
                return
            problem = config.base_url_problem(url)
            if problem:
                log.write(f"[red]●[/red] [red]{escape(problem)}[/red]")
                return
            config.set_provider_value("custom", "base_url", url)
            log.write(f"[green]●[/green] Custom server URL set to {escape(url)}.")
            if llm.provider() == "custom":
                self._model_menu()
            return

        if lowered == "/setkey":
            name = llm.provider()
            if name == "custom" and not config.provider_ready(name):
                self._prompt_for_key()
                return
            self._mode = "key"
            inp = self.query_one("#input", Input)
            inp.password = True
            inp.placeholder = f"Paste your {config.PROVIDERS[name]['label']} API key..."
            self.query_one("#cmdlist", OptionList).display = False
            log.write("[dim]Paste the API key below, or type 'cancel'.[/dim]")
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

        if lowered == "/addvoice":
            folder = ttsinstall.open_voice_folder()
            log.write(
                f"[green]●[/green] Opened {escape(folder)}. Put .wav clips into the language folders "
                "(en/, tr/, or any other language code). Loose .wav files in the root are ignored."
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
            set_duck_online(False)
            tts.set_autostart(True)
            tts.set_voice(True)
            log.write("[green]●[/green] Defaults applied: DuckDuckGo off, TTS auto-start on, voice on.")
            self._enable_native_search()
            return

        if lowered == "/resetmemory":
            def reset() -> None:
                reset_memory()
                self.call_from_thread(log.write, "[green]●[/green] Memory cleared.")

            self.run_worker(reset, thread=True)
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
            entry_id = int(parts[1])

            def forget() -> None:
                removed = forget_memory(entry_id)
                self.call_from_thread(
                    log.write, f"[green]●[/green] {'Removed.' if removed else 'No memory with that id.'}"
                )

            self.run_worker(forget, thread=True)
            return

        if lowered == "/resethistory":
            self.history = []
            self._chat_id = chats.new_id()
            log.write("[green]●[/green] Conversation history cleared.")
            return

        if lowered == "/chats":
            self._show_chat_picker()
            return

        if lowered == "/newchat":
            self._start_new_chat()
            return

        if lowered == "/deletechat":
            if chats.delete(self._chat_id):
                self._start_new_chat()
                log.write("[green]●[/green] The previous chat was deleted from chat history.")
            else:
                log.write("[green]●[/green] The current chat has not been saved yet.")
            return

        if lowered == "/think":
            self._think_menu()
            return

        if lowered in ("/think high", "/think low"):
            if not llm.thinking_supported():
                log.write(
                    f"[yellow]●[/yellow] {escape(llm.label())} manages its own thinking; "
                    "/think has no effect on this model."
                )
                return
            level = lowered.split()[1]
            set_thinking_level(level)
            self._refresh_header()
            log.write(f"[green]●[/green] Thinking level set to {level}.")
            return


        if lowered == "/search":
            self._search_menu()
            return

        if lowered in ("/google", "/duckduck"):
            log.write(
                f"[green]●[/green] {self._native_search_label()}: "
                f"{'online' if is_google_online() else 'offline'}  ·  "
                f"DuckDuckGo: {'online' if is_duck_online() else 'offline'}."
            )
            return

        if lowered in ("/onlinenative", "/onlinegoogle"):
            self._enable_native_search()
            return

        if lowered == "/offlinenative":
            log.write(f"[green]●[/green] {set_google_online(False, self._native_search_label())}")
            return

        if lowered == "/offlinegoogle":
            log.write(f"[green]●[/green] {set_google_online(False, self._native_search_label())}")
            return

        if lowered == "/onlineduckduck":
            self._use_search("duck")
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
            tts.speak(speech_text, lang=tts.resolve_lang(None, speech_text))
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
            tts.speak(speech_text, lang=tts.resolve_lang(None, speech_text))
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
        if tts.voice_enabled and not tts.server_disabled:
            if not tts._started_by_us and not tts.server_running():
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
        chat_id = self._chat_id

        searched = False

        def on_status(message: str) -> None:
            nonlocal searched
            if message.startswith("Searching about"):
                if searched:
                    return
                searched = True
            self.call_from_thread(self._write_status, message)

        try:
            reply, history = ask(prompt, self.history, on_status=on_status)
            if self._chat_id == chat_id:
                self.history = history
        except Exception as e:
            reply = assistant.Notice(f"[yellow](Something went wrong: {escape(str(e))})[/yellow]")
        elapsed = time.monotonic() - start
        self.call_from_thread(self._write_reply, reply, elapsed)
        is_notice = isinstance(reply, assistant.Notice)
        if not is_notice:
            try:
                chats.append(chat_id, prompt, reply)
            except OSError:
                _log_exception("chat-save")
        try:
            spoken = Text.from_markup(reply).plain if is_notice else reply
            tts.speak(spoken, lang=tts.resolve_lang(None if is_notice else get_reply_lang(), spoken))
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
