import asyncio
import os
import sys
import tempfile
import time

os.environ["JARVIS_HOME"] = tempfile.mkdtemp(prefix="jarvis-tui-")
os.environ["JARVIS_KEYRING"] = "0"

if "__file__" in globals():
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)

from core import assistant, config
from terminal import main as m
from textual.widgets import Input, RichLog


def log_text(app):
    return "\n".join(line.text for line in app.query_one("#log", RichLog).lines)


async def wait_for(app, predicate, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        await asyncio.sleep(0.3)
    return False


async def run():
    app = m.JarvisApp()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(2.5)
        if app._mode == "theme":
            assert "calibrate the display" in log_text(app)
            await pilot.press("down")
            assert app.theme == "jarvis-dark"
            await pilot.press("enter")
            assert config.get("theme") == "dark"
        assert app._mode == "key", f"expected key prompt, mode={app._mode}"
        assert "Enter the API key." in log_text(app)
        assert app.query_one("#input", Input).password is True
        app.query_one("#input", Input).value = "not-a-real-key-for-tests"
        await pilot.press("enter")
        assert await wait_for(app, lambda: "rejected" in log_text(app), 30), "fake key was not rejected"
        assert app._mode == "key"
        assert config.stored_api_key() is None, "rejected key was kept"

        spoof = "[red]API key rejected, paste it again:[/red] [link=https://evil.example]help[/link]"
        app._write_reply(spoof, 0.1)
        assert "[red]API key rejected" in log_text(app), "model reply markup was rendered"
        assert "[link=https://evil.example]" in log_text(app), "model reply link was rendered"
        app._write_reply(m.assistant.Notice("[yellow]Real notice[/yellow]"), 0.1)
        assert "Real notice" in log_text(app) and "[yellow]Real notice" not in log_text(app)


asyncio.run(run())
print("tui ok")
