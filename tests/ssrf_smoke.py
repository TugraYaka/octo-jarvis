import sys, threading, http.server, socket, time
import os, tempfile
os.environ["JARVIS_HOME"] = tempfile.mkdtemp(prefix="jarvis-ssrf-")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import browser, safe_proxy

hits = []
class B(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(self.path)
        self.send_response(200); self.send_header("Content-Type","text/plain"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers(); self.wfile.write(b"SECRET")
    def log_message(self, *a): pass
class A(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/shop":
            body = b"<html><body><p>Your cart has one item, a very nice lamp, ready to ship today with free delivery.</p><button id=b><span>Continue</span> - Place order</button><a href='/reviews'>Reviews</a></body></html>"
            self.send_response(200); self.send_header("Content-Type","text/html"); self.end_headers(); self.wfile.write(body); return
        if self.path == "/rtc":
            body = f"""<html><body><p>webrtc probe page with some text</p><script>
const pc = new RTCPeerConnection({{iceServers: [{{urls: 'stun:{lan_ip}:{pu}'}}]}});
pc.createDataChannel('x');
pc.onicecandidate = e => {{ if (e.candidate) document.title += e.candidate.type + ' '; }};
pc.createOffer().then(o => pc.setLocalDescription(o));
</script></body></html>""".encode()
            self.send_response(200); self.send_header("Content-Type","text/html"); self.end_headers(); self.wfile.write(body); return
        if self.path == "/redir":
            self.send_response(302); self.send_header("Location", f"http://127.0.0.1:{pb}/nav-redirect"); self.end_headers(); return
        if self.path == "/imgredir":
            self.send_response(302); self.send_header("Location", f"http://127.0.0.1:{pb}/img-redirect"); self.end_headers(); return
        if self.path == "/xhrredir":
            self.send_response(302); self.send_header("Location", f"http://127.0.0.1:{pb}/xhr-redirect"); self.send_header("Access-Control-Allow-Origin","*"); self.end_headers(); return
        body = f"""<html><body><h1>hello page with enough text to be settled and not retried by the snapshot logic, really enough text here to pass the threshold of one hundred and fifty characters.</h1>
<img src="http://pub.test:{pa}/imgredir"><script>
fetch('http://127.0.0.1:{pb}/direct-xhr').catch(()=>{{}});
fetch('http://pub.test:{pa}/xhrredir').catch(()=>{{}});
</script></body></html>""".encode()
        self.send_response(200); self.send_header("Content-Type","text/html"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
sb = http.server.ThreadingHTTPServer(("127.0.0.1", 0), B); pb = sb.server_port
sa = http.server.ThreadingHTTPServer(("127.0.0.1", 0), A); pa = sa.server_port
su = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); su.bind(("0.0.0.0", 0)); pu = su.getsockname()[1]
udp_hits = []
def udp_listen():
    while True:
        data, addr = su.recvfrom(2048); udp_hits.append(addr)
threading.Thread(target=udp_listen, daemon=True).start()
probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); probe.connect(("8.8.8.8", 80)); lan_ip = probe.getsockname()[0]; probe.close()
for s in (sa, sb): threading.Thread(target=s.serve_forever, daemon=True).start()

resolved = []
calls = {"rebind.test": 0}
def fake_resolve(host):
    resolved.append(host)
    if host == "pub.test": return ["93.184.216.34"]
    if host == "rebind.test":
        calls["rebind.test"] += 1
        return ["93.184.216.34"] if calls["rebind.test"] == 1 else ["127.0.0.1"]
    return [host] if host[0].isdigit() else ["127.0.0.1"]
def fake_connect(ip, port):
    return socket.create_connection(("127.0.0.1", port), timeout=5)
safe_proxy._resolve = fake_resolve
safe_proxy._connect = fake_connect
safe_proxy.ALLOWED_PORTS = frozenset({80, 443, pa, pb})

failures = []

def check(label, ok, detail=""):
    print("OK" if ok else "FAIL", label, detail)
    if not ok:
        failures.append(label)

def expect_blocked(label, url):
    try:
        browser.browser_open(url); check(label, False, "not blocked")
    except browser.BlockedURLError as e:
        check(label, True, f"-> {e}")
    except Exception as e:
        check(label, False, "wrong error " + str(e)[:100])

expect_blocked("literal loopback", f"http://127.0.0.1:{pa}/")
expect_blocked("nav redirect", f"http://pub.test:{pa}/redir")
expect_blocked("dns rebinding", f"http://rebind.test:{pa}/")
expect_blocked("port not allowed", f"http://pub.test:{pa + 1 if pa + 1 != pb else pa + 2}/")
snap = browser.browser_open(f"http://pub.test:{pa}/")
check("public page via proxy", snap["text"].startswith("hello page"))
time.sleep(1.5)
check("internal server never reached", not hits, str(hits))
proxy = browser._session._proxy
check("sub-request blocks recorded", proxy.block_count >= 4, str(proxy.block_count))

raw = socket.create_connection(("127.0.0.1", int(proxy.url.rsplit(":", 1)[1])), timeout=5)
raw.sendall(f"GET http://pub.test:{pa}/ HTTP/1.1\r\nHost: pub.test\r\n\r\n".encode())
check("proxy rejects clients without password", raw.recv(64).startswith(b"HTTP/1.1 407"))
raw.close()

browser.browser_open(f"http://pub.test:{pa}/shop")
described = browser._run(lambda: browser._session.describe("Continue"))
check("click target resolves to the real button", "Place order" in described and "BUTTON" in described, described)
from core import assistant
check("hidden 'Continue' that places an order is flagged", assistant._sensitive_click("Continue", described, "pub.test") is not None)

snap = browser.browser_open(f"http://pub.test:{pa}/rtc")
time.sleep(3)
check("webrtc sends no UDP outside the proxy", not udp_hits, str(udp_hits[:3]))
browser.browser_close()

upstream = safe_proxy.SafeProxy()
os.environ["JARVIS_UPSTREAM_PROXY"] = f"http://{upstream.username}:{upstream.password}@127.0.0.1:{upstream.url.rsplit(':', 1)[1]}"
resolved.clear()
snap = browser.browser_open(f"http://pub.test:{pa}/")
check("works through upstream proxy", snap["text"].startswith("hello page"))
check("upstream only sees the pinned IP", "93.184.216.34" in resolved and resolved.count("pub.test") >= 1, str(resolved[:6]))
expect_blocked("upstream path still blocks redirects", f"http://pub.test:{pa}/redir")
browser.browser_close()
upstream.stop()
del os.environ["JARVIS_UPSTREAM_PROXY"]

print(f"{len(failures)} failure(s)")
sys.exit(1 if failures else 0)
