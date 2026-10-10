import base64
import hmac
import ipaddress
import os
import secrets
import select
import socket
import socketserver
import threading
from urllib.parse import unquote, urlsplit

CONNECT_TIMEOUT = 15
IDLE_TIMEOUT = 60
MAX_HEADER_BYTES = 65536
ALLOWED_PORTS = frozenset({80, 443, 8080, 8443})
UPSTREAM_ENV = ("JARVIS_UPSTREAM_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


class BlockedURLError(Exception):
    pass


def _resolve(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise BlockedURLError(f"Could not resolve host: {e}")
    return [info[4][0].split("%")[0] for info in infos]


def _connect(ip: str, port: int) -> socket.socket:
    return socket.create_connection((ip, port), timeout=CONNECT_TIMEOUT)


def ip_block_reason(ip: str) -> str | None:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if not addr.is_global or addr.is_private or addr.is_loopback or addr.is_link_local \
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified:
        return f"Blocked internal address: {addr}"
    return None


def port_block_reason(port: int) -> str | None:
    if port not in ALLOWED_PORTS:
        return f"Blocked port: {port}"
    return None


def resolve_public(host: str) -> list[str]:
    ips = _resolve(host)
    if not ips:
        raise BlockedURLError("Could not resolve host")
    for ip in ips:
        reason = ip_block_reason(ip)
        if reason:
            raise BlockedURLError(reason)
    return ips


def _upstream_from_env() -> tuple[str, int, str | None] | None:
    for name in UPSTREAM_ENV:
        value = os.environ.get(name, "").strip()
        if not value:
            continue
        parts = urlsplit(value if "://" in value else f"http://{value}")
        if parts.scheme != "http" or not parts.hostname:
            continue
        auth = None
        if parts.username:
            raw = f"{unquote(parts.username)}:{unquote(parts.password or '')}"
            auth = "Basic " + base64.b64encode(raw.encode()).decode()
        return parts.hostname, parts.port or 8080, auth
    return None


def _tunnel_via(upstream: tuple[str, int, str | None], ip: str, port: int) -> socket.socket:
    """Open a CONNECT tunnel to the already-checked IP, so the upstream proxy never resolves the name."""
    host, upstream_port, auth = upstream
    sock = socket.create_connection((host, upstream_port), timeout=CONNECT_TIMEOUT)
    target = f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}"
    request = f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n"
    if auth:
        request += f"Proxy-Authorization: {auth}\r\n"
    sock.sendall((request + "\r\n").encode("latin-1"))
    head, rest = _read_head(sock)
    status_line = head.split(b"\r\n", 1)[0]
    status = status_line.split(b" ")
    if len(status) < 2 or status[1] != b"200" or rest:
        sock.close()
        raise OSError(f"Upstream proxy refused: {status_line.decode('latin-1')}")
    return sock


def connect_public(host: str, port: int, upstream=None) -> socket.socket:
    """Resolve once, validate every address, then connect to that exact address (no re-resolve)."""
    reason = port_block_reason(port)
    if reason:
        raise BlockedURLError(reason)
    last_error = None
    for ip in resolve_public(host):
        try:
            return _tunnel_via(upstream, ip, port) if upstream else _connect(ip, port)
        except OSError as e:
            last_error = e
    raise BlockedURLError(f"Could not connect: {last_error}")


def _pipe(a: socket.socket, b: socket.socket) -> None:
    pair = (a, b)
    try:
        while True:
            ready, _, _ = select.select(pair, [], [], IDLE_TIMEOUT)
            if not ready:
                return
            for src in ready:
                data = src.recv(65536)
                if not data:
                    return
                (b if src is a else a).sendall(data)
    except OSError:
        return


def _read_head(sock: socket.socket) -> tuple[bytes, bytes]:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(8192)
        if not chunk or len(buf) > MAX_HEADER_BYTES:
            raise ValueError("bad request")
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    return head, rest


def _header(lines: list[bytes], name: bytes) -> bytes | None:
    for line in lines:
        key, _, value = line.partition(b":")
        if key.strip().lower() == name:
            return value.strip()
    return None


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        client = self.request
        client.settimeout(IDLE_TIMEOUT)
        proxy = self.server.owner
        try:
            head, rest = _read_head(client)
            lines = head.split(b"\r\n")
            method, target, version = lines[0].decode("latin-1").split(" ", 2)
            if not proxy.authorized(_header(lines[1:], b"proxy-authorization")):
                client.sendall(
                    b"HTTP/1.1 407 Proxy Authentication Required\r\n"
                    b"Proxy-Authenticate: Basic realm=\"jarvis\"\r\n"
                    b"Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
                return
            if method.upper() == "CONNECT":
                host, _, port = target.rpartition(":")
                upstream = self._open(proxy, host.strip("[]"), int(port or 443))
                if upstream is None:
                    return
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                if rest:
                    upstream.sendall(rest)
            else:
                parts = urlsplit(target)
                if parts.scheme != "http" or not parts.hostname:
                    client.sendall(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                    return
                upstream = self._open(proxy, parts.hostname, parts.port or 80)
                if upstream is None:
                    return
                path = parts.path or "/"
                if parts.query:
                    path += "?" + parts.query
                kept = [
                    line for line in lines[1:]
                    if line.split(b":", 1)[0].strip().lower()
                    not in (b"proxy-connection", b"connection", b"proxy-authorization")
                ]
                request = [f"{method} {path} {version}".encode("latin-1")] + kept + [b"Connection: close"]
                upstream.sendall(b"\r\n".join(request) + b"\r\n\r\n" + rest)
            try:
                _pipe(client, upstream)
            finally:
                upstream.close()
        except (OSError, ValueError):
            return

    def _open(self, proxy, host: str, port: int):
        try:
            return connect_public(host, port, proxy.upstream)
        except BlockedURLError as e:
            proxy.record_block(f"{host}:{port}", str(e))
            try:
                self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            return None


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class SafeProxy:
    """Local forward proxy that only connects to public addresses.

    The browser sends every request (navigations, redirects, images, XHR) through
    it. Each hop is resolved once, checked, and connected to by that same IP, so a
    redirect or DNS rebinding cannot reach loopback, private or link-local hosts.
    It requires a per-instance password, so other local processes cannot use it,
    and it chains through an upstream HTTP proxy from the environment when set.
    """

    def __init__(self) -> None:
        self.username = "jarvis"
        self.password = secrets.token_urlsafe(24)
        self._expected = ("Basic " + base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()).encode()
        self.upstream = _upstream_from_env()
        self._server = _Server(("127.0.0.1", 0), _Handler)
        self._server.owner = self
        self._lock = threading.Lock()
        self.block_count = 0
        self.last_block: str | None = None
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="safe-proxy")
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def playwright_config(self) -> dict:
        return {"server": self.url, "bypass": "<-loopback>", "username": self.username, "password": self.password}

    def authorized(self, header: bytes | None) -> bool:
        return header is not None and hmac.compare_digest(header, self._expected)

    def record_block(self, target: str, reason: str) -> None:
        with self._lock:
            self.block_count += 1
            self.last_block = f"{reason} ({target})"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
