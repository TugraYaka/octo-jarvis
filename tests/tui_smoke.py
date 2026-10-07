import asyncio
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "terminal"))

from core import config
import main as m
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
        assert app._mode == "key", f"expected key prompt, mode={app._mode}"
        assert "No Gemini API key found" in log_text(app)
        assert app.query_one("#input", Input).password is True
        app.query_one("#input", Input).value = "not-a-real-key-for-tests"
        await pilot.press("enter")
        assert await wait_for(app, lambda: "rejected" in log_text(app), 30), "fake key was not rejected"
        assert app._mode == "key"
        assert config.stored_api_key() is None, "rejected key was kept"


asyncio.run(run())
print("tui ok")
