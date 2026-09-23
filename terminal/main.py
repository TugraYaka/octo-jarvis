import sys
import os
import select
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import stt
from core import tts
from core.gemini_client import ask, get_thinking_level, set_thinking_level, warmup
from core.memory import reset_memory, list_memory, forget_memory
from core.search_mode import set_google_online, set_duck_online
from core.stt import listen, listen_stream

BLUE = "\033[94m"
RESET = "\033[0m"


def _read_input(prompt: str) -> str:
    line = input(prompt).strip()
    extra = []
    while select.select([sys.stdin], [], [], 0.05)[0]:
        pending = sys.stdin.readline()
        if not pending:
            break
        pending = pending.strip()
        if pending:
            extra.append(pending)
    if extra:
        line = " ".join([line, *extra]) if line else " ".join(extra)
        input(f"{prompt}[{line}] Onaylamak için Enter'a basın: ")
    return line


def _warm_up() -> None:
    for task in (warmup, stt.warmup):
        try:
            task()
        except Exception:
            pass


def stream_reply(prompt: str, history: list) -> list:
    try:
        reply, history = ask(prompt, history)
    except Exception as e:
        reply = f"(Something went wrong: {e})"
    print(f"JARVIS: {reply}")
    return history


BANNER = r"""
     ██╗  █████╗  ██████╗  ██╗   ██╗ ██╗ ███████╗
     ██║ ██╔══██╗ ██╔══██╗ ██║   ██║ ██║ ██╔════╝
     ██║ ███████║ ██████╔╝ ██║   ██║ ██║ ███████╗
██   ██║ ██╔══██║ ██╔══██╗ ╚██╗ ██╔╝ ██║ ╚════██║
╚█████╔╝ ██║  ██║ ██║  ██║  ╚████╔╝  ██║ ███████║
 ╚════╝  ╚═╝  ╚═╝ ╚═╝  ╚═╝   ╚═══╝   ╚═╝ ╚══════╝
"""


def main():
    print(f"{BLUE}{BANNER}{RESET}")
    threading.Thread(target=_warm_up, daemon=True).start()
    print("JARVIS ready. Type 'exit' to quit.")
    history: list = []
    while True:
        user_input = _read_input("You: ")
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue
        if user_input.lower() == "/resetmemory":
            reset_memory()
            print("JARVIS: Memory cleared.")
            continue
        if user_input.lower() == "/listmemory":
            entries = list_memory()
            if not entries:
                print("JARVIS: Memory is empty.")
            else:
                for e in entries:
                    date = (
                        time.strftime("%Y-%m-%d", time.localtime(e["ts"]))
                        if e.get("ts") else "?"
                    )
                    print(f"[{e['id']}] ({date}) {e['text']}")
            continue
        if user_input.lower().startswith("/forgetmemory"):
            parts = user_input.split()
            if len(parts) != 2 or not parts[1].isdigit():
                print("JARVIS: Usage: /forgetmemory <id>")
                continue
            removed = forget_memory(int(parts[1]))
            print(f"JARVIS: {'Removed.' if removed else 'No memory with that id.'}")
            continue
        if user_input.lower() == "/resethistory":
            history = []
            print("JARVIS: Conversation history cleared.")
            continue
        if user_input.lower() in ("/think high", "/think low"):
            level = user_input.lower().split()[1]
            set_thinking_level(level)
            print(f"JARVIS: Thinking level set to {level}.")
            continue
        if user_input.lower() == "/think":
            print(f"JARVIS: Current thinking level is {get_thinking_level()}.")
            continue
        if user_input.lower() == "/onlinegoogle":
            print(f"JARVIS: {set_google_online(True)}")
            continue
        if user_input.lower() == "/offlinegoogle":
            print(f"JARVIS: {set_google_online(False)}")
            continue
        if user_input.lower() == "/onlineduckduck":
            print(f"JARVIS: {set_duck_online(True)}")
            continue
        if user_input.lower() == "/offlineduckduck":
            print(f"JARVIS: {set_duck_online(False)}")
            continue
        if user_input.lower().startswith("/speak "):
            text = user_input[len("/speak "):].strip()
            if not text:
                print("JARVIS: Usage: /speak <text>")
                continue
            print("JARVIS: Speaking...")
            try:
                tts.speak(text, lang="en")
            except Exception as e:
                print(f"JARVIS: TTS error ({e}).")
            continue
        if user_input.lower() == "/mictest":
            print("Listening... (speak now, pause when done)")
            try:
                text, language = listen()
            except Exception as e:
                print(f"JARVIS: Microphone error ({e}).")
                continue
            if not text:
                print("JARVIS: No speech detected.")
            else:
                print(f"[{language}] {text}")
            continue
        if user_input.lower() == "/talk":
            print("Listening... (speak now, pause when done)")
            parts = []
            try:
                for text, _ in listen_stream():
                    if not parts:
                        print("You (spoken): ", end="", flush=True)
                    print(text, end=" ", flush=True)
                    parts.append(text)
            except Exception as e:
                print(f"\nJARVIS: Microphone error ({e}).")
                continue
            full_text = " ".join(parts).strip()
            if not full_text:
                print("JARVIS: No speech detected.")
                continue
            print()
            history = stream_reply(full_text, history)
            continue
        history = stream_reply(user_input, history)


if __name__ == "__main__":
    main()
