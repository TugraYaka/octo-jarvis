import json
import multiprocessing
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _writer(worker, count, barrier):
    from core import memory

    def fake_embed(text, kind):
        vector = [0.0] * 768
        vector[int(text.split("-")[1]) * 10 + int(text.split("-")[2])] = 1.0
        return vector

    memory.embed = fake_embed
    barrier.wait()
    for i in range(count):
        memory._do_remember(f"fact-{worker}-{i}", None)


def main():
    from core import browser, memory, paths, tts
    from core.gemini_client import _strip_lang

    paths.ensure_dirs()
    failures = []

    def check(name, ok):
        print(("ok " if ok else "FAIL ") + name, flush=True)
        if not ok:
            failures.append(name)

    text, tag = _strip_lang("Hola senor. <lang>es</lang>")
    check("lang tag stripped", text.strip() == "Hola senor." and tag == "es")
    text, tag = _strip_lang("Hello sir. <lang>")
    check("partial lang tag stripped", "<lang" not in text and tag is None)
    text, tag = _strip_lang("No tag here.")
    check("no tag untouched", text == "No tag here." and tag is None)

    check("resolve supported", tts.resolve_lang("de", "") == "de")
    check("resolve region code", tts.resolve_lang("pt-BR", "") == "pt")
    check("resolve chinese", tts.resolve_lang("zh", "") == "zh-cn")
    check("resolve unsupported falls back to english", tts.resolve_lang("sv", "Hej") == "en")
    check("fallback devanagari", tts.resolve_lang(None, "नमस्ते") == "hi")
    check("fallback cyrillic", tts.resolve_lang(None, "Доброе утро") == "ru")
    check("fallback japanese", tts.resolve_lang(None, "おはよう") == "ja")
    check("fallback korean", tts.resolve_lang(None, "안녕하세요") == "ko")
    check("fallback arabic", tts.resolve_lang(None, "صباح الخير") == "ar")
    check("resolve fallback english", tts.resolve_lang(None, "Good morning sir") == "en")

    check("browser locale format", "-" in browser._browser_locale())
    check("browser user agent", browser._user_agent().startswith("Mozilla/5.0 ("))

    if os.path.exists(memory.MEMORY_PATH):
        os.remove(memory.MEMORY_PATH)
    ctx = multiprocessing.get_context("spawn")
    workers, per_worker = 4, 5
    barrier = ctx.Barrier(workers)
    procs = [ctx.Process(target=_writer, args=(w, per_worker, barrier)) for w in range(workers)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(120)
    saved = len(memory._load_entries())
    check(f"concurrent memory writes keep every fact ({saved}/{workers * per_worker})", saved == workers * per_worker)

    with open(memory.MEMORY_PATH, "w", encoding="utf-8") as f:
        f.write("{broken")
    check("corrupt memory reads as empty", memory._load_entries() == [])
    check("corrupt memory is kept as backup", os.path.isfile(memory.MEMORY_PATH + ".corrupt"))

    print(f"{len(failures)} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
