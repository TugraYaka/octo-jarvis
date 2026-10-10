import sys, types, os, tempfile, threading, json, urllib.request, urllib.error, http.client
for name in ("soundfile", "torch", "chatterbox", "chatterbox.mtl_tts"):
    sys.modules[name] = types.ModuleType(name)
sys.modules["chatterbox.mtl_tts"].SUPPORTED_LANGUAGES = {"en": "English"}
sys.modules["chatterbox.mtl_tts"].ChatterboxMultilingualTTS = type("M", (), {"from_pretrained": staticmethod(lambda device: None)})
tok = tempfile.NamedTemporaryFile("w", delete=False); tok.write("secret-token"); tok.close()
os.environ["JARVIS_TTS_TOKEN_FILE"] = tok.name
os.environ["JARVIS_TTS_PORT"] = "0"; os.environ["JARVIS_TTS_DEVICE"] = "cpu"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tts_server"))
import server
def fake_synth(text, lang, out):
    open(out, "wb").write(b"WAV")
server.synthesize = fake_synth
srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
port = srv.server_address[1]; server.PORT = port
threading.Thread(target=srv.serve_forever, daemon=True).start()

def req(headers, body=b'{"text":"hi","lang":"en"}', method="POST"):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    c.request(method, "/", body=body if method == "POST" else None, headers=headers)
    r = c.getresponse(); return r.status
good = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json", "X-JARVIS-Token": "secret-token"}
fails = 0
for label, h, b, want in (
    ("valid request", good, None, 200),
    ("no token", {**good, "X-JARVIS-Token": ""}, None, 403),
    ("wrong token", {**good, "X-JARVIS-Token": "nope"}, None, 403),
    ("rebinding Host", {**good, "Host": f"evil.com:{port}"}, None, 403),
    ("text/plain CSRF", {**good, "Content-Type": "text/plain"}, None, 415),
    ("oversized body", good, b"x" * 70000, 413),
):
    status = req(h, b) if b else req(h)
    ok = status == want; fails += not ok
    print("OK" if ok else "FAIL", label, status)
print("GET ok host", req({"Host": f"localhost:{port}"}, method="GET"), "| GET evil host", req({"Host": "evil.com"}, method="GET"))
fails += req({"Host": "evil.com"}, method="GET") != 403
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
