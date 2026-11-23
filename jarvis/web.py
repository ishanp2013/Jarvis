"""Jarvis's local web server: the dashboard, the floating orb and the phone app all talk to it.

The dashboard calls POST /api/<method> and receives events from GET /events (Server-Sent Events).

Safety:
- It listens on 127.0.0.1 only. Your phone reaches it through Tailscale ("tailscale serve"), which
  forwards only traffic from your own private Tailscale network; nothing is opened to the internet.
- Requests must carry a known Host header (blocks DNS-rebinding tricks).
- Pages on this PC use a random per-run token that only the served page knows, so other websites
  can't drive Jarvis.
- A phone must be paired first (a one-time code shown on the laptop). It then holds its own device
  key, stored only as a hash and removable at any time, and may call only the phone methods below."""
import json
import logging
import mimetypes
import queue
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .config import settings

log = logging.getLogger("web")
TOKEN = secrets.token_urlsafe(24)
COOKIE = "jarvis_device"

# What a paired phone may do: talk to Jarvis, answer approval cards, use the laptop controls, read status.
PHONE_METHODS = {"init", "send_text", "voice", "stop", "approve", "reject", "integrations", "activity", "ping",
                 "laptop_status", "screenshot", "running_apps", "lock_laptop", "power", "cancel_power", "game_mode",
                 "tasks", "add_task", "complete_task", "dismiss_task", "agent_status", "agent_run_now",
                 "jobs", "prepare_task", "open_result", "today", "brief_me", "team", "team_feed", "chat_history", "ask_agent"}
# The phone app's own files, served before pairing so it can show the pairing screen (and work offline).
APP_SHELL = {"mobile.html", "mobile.js", "mobile.css", "manifest.json", "sw.js", "icon.svg", "orb.js"}
INJECT = ("index.html", "overlay.html", "mobile.html")


class Hub:
    """Fans Jarvis events out to every open dashboard tab and phone."""

    def __init__(self):
        self.clients, self.lock = [], threading.Lock()

    def publish(self, kind, data):
        msg = json.dumps({"kind": kind, "data": data}, default=str)
        with self.lock:
            for q in self.clients:
                try:
                    q.put_nowait(msg)
                except queue.Full:
                    pass

    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)


class Pairing:
    """One short-lived code at a time, used once."""

    def __init__(self):
        self.code, self.expires, self.lock = None, 0.0, threading.Lock()

    def start(self, minutes=5):
        with self.lock:
            self.code = f"{secrets.randbelow(10**6):06d}"
            self.expires = time.time() + minutes * 60
            return self.code

    def consume(self, code):
        with self.lock:
            ok = bool(self.code) and time.time() < self.expires and secrets.compare_digest(str(code).strip(), self.code)
            if ok or time.time() >= self.expires:
                self.code = None
            return ok


def make_handler(api, ui_dir, port, hub, store=None, pairing=None):
    local_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    methods = {n for n in dir(api) if not n.startswith("_") and callable(getattr(api, n))}
    bridge = f'<script>window.JARVIS_TOKEN = "{TOKEN}";</script><script src="web-bridge.js"></script>'
    pairing = pairing or Pairing()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet; never log tokens in URLs
            pass

        def _send(self, code, body=b"", ctype="application/json", headers=()):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in headers:
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        # ---- who is asking
        def _host(self):
            return (self.headers.get("Host") or "").lower()

        def _remote(self):
            """True for anything that came through Tailscale (or any proxy), not straight from this PC."""
            return bool(self.headers.get("Tailscale-User-Login") or self.headers.get("X-Forwarded-For")) \
                or self._host() not in local_hosts

        def _host_ok(self):
            remote_host = (settings.get("remote_host") or "").lower().strip()
            if self._host() in local_hosts or (remote_host and self._host() in (remote_host, f"{remote_host}:443")):
                return True
            self._send(403, b'"bad host"')
            return False

        def _device(self):
            token = self.headers.get("X-Jarvis-Device") or ""
            for part in (self.headers.get("Cookie") or "").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE:
                    token = v
            return store.device_for(token) if store and token else None

        def _local_token_ok(self, given):
            return not self._remote() and bool(given) and secrets.compare_digest(given, TOKEN)

        # ---- GET: pages and the event stream
        def do_GET(self):
            if not self._host_ok():
                return
            url = urlparse(self.path)
            if url.path == "/events":
                if not (self._local_token_ok(parse_qs(url.query).get("token", [""])[0]) or self._device()):
                    return self._send(403, b'"bad token"')
                return self._events()
            if url.path in ("/", ""):
                name = "mobile.html" if self._remote() else "index.html"
            elif url.path == "/m":
                name = "mobile.html"
            else:
                name = url.path.lstrip("/")
            if self._remote() and name not in APP_SHELL and not self._device():
                return self._send(403, b'"pair this phone first"')
            path = (ui_dir / name).resolve()
            if ui_dir not in path.parents or not path.is_file():
                return self._send(404, b'"not found"')
            body = path.read_bytes()
            if name in INJECT:  # pages on this PC get the per-run token; the phone uses its device key instead
                body = body.replace(b"<!--bridge-->", b"" if self._remote() else bridge.encode())
            # Windows sometimes maps .js to text/plain, and browsers refuse to run modules served that way.
            known = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css", ".woff2": "font/woff2",
                     ".svg": "image/svg+xml", ".html": "text/html"}
            ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
            ctype = "application/manifest+json" if name == "manifest.json" else \
                known.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"
            self._send(200, body, ctype, [("Service-Worker-Allowed", "/")] if name == "sw.js" else ())

        # ---- POST: pairing and API calls
        def _body(self):
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"null")

        def do_POST(self):
            if not self._host_ok():
                return
            if self.path == "/pair":
                return self._pair()
            name = self.path.removeprefix("/api/")
            device = None
            if not self._local_token_ok(self.headers.get("X-Jarvis-Token") or ""):
                device = self._device()
                if not device:
                    return self._send(403, b'"bad token"')
                if name not in PHONE_METHODS:
                    return self._send(403, b'"not allowed from the phone"')
            if name not in methods:
                return self._send(404, b'"unknown method"')
            try:
                args = self._body() or []
                if device and name in ("send_text", "voice", "brief_me", "ask_agent"):
                    args = list(args) + ["phone"]  # replies to the phone aren't spoken on the laptop
                result = getattr(api, name)(*args)
                self._send(200, json.dumps(result, default=str).encode())
            except Exception as e:
                log.exception("api %s", name)
                self._send(500, json.dumps({"error": str(e)[:300]}).encode())

        def _pair(self):
            try:
                body = self._body() or {}
            except ValueError:
                body = {}
            if not store or not pairing.consume(body.get("code", "")):
                time.sleep(1)  # slows down guessing
                return self._send(403, b'{"ok": false, "error": "That code is wrong or has expired. Make a new one on the laptop."}')
            token = secrets.token_urlsafe(32)
            name = str(body.get("name") or "Phone")[:60]
            store.add_device(name, token)
            secure = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
            cookie = f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=31536000{secure}"
            if hasattr(api, "_on_paired"):
                api._on_paired(name)
            self._send(200, json.dumps({"ok": True, "name": name}).encode(), headers=[("Set-Cookie", cookie)])

        def _events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            q = hub.subscribe()
            try:
                while True:
                    try:
                        msg = q.get(timeout=15)
                    except queue.Empty:
                        msg = None
                    self.wfile.write(f"data: {msg}\n\n".encode() if msg else b": ping\n\n")
                    self.wfile.flush()
            except (ConnectionError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

    Handler.pairing = pairing
    return Handler


def serve(j, api, ui_dir, port=8765, open_browser=True):
    hub = Hub()
    j.on_event = hub.publish
    pairing = Pairing()
    api._pairing = pairing
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(api, ui_dir.resolve(), port, hub, j.store, pairing))
    server.daemon_threads = True
    url = f"http://127.0.0.1:{port}/"
    log.info("dashboard at %s", url)
    print(f"Jarvis dashboard: {url}  (Ctrl+C to stop)", flush=True)
    threading.Thread(target=j.boot, daemon=True).start()
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
