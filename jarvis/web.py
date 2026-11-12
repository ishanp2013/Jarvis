"""Browser mode: serves the dashboard on http://127.0.0.1:<port> instead of the desktop window.

Same Jarvis (mic, wake word, voice, tools); only the screen is a browser tab. The dashboard calls
POST /api/<method> and receives events from GET /events (Server-Sent Events).

Safety: the server listens on 127.0.0.1 only, rejects other Host headers (DNS rebinding) and needs
a random per-run token that only the served page knows, so other websites can't drive Jarvis."""
import json
import logging
import mimetypes
import queue
import secrets
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

log = logging.getLogger("web")
TOKEN = secrets.token_urlsafe(24)


class Hub:
    """Fans Jarvis events out to every open dashboard tab."""

    def __init__(self):
        self.clients, self.lock = [], threading.Lock()

    def publish(self, kind, data):
        msg = json.dumps({"kind": kind, "data": data}, default=str)
        with self.lock:
            for q in self.clients:
                q.put(msg)

    def subscribe(self):
        q = queue.Queue(maxsize=500)
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)


def make_handler(api, ui_dir, port, hub):
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    methods = {n for n in dir(api) if not n.startswith("_") and callable(getattr(api, n))}
    bridge = f'<script>window.JARVIS_TOKEN = "{TOKEN}";</script><script src="web-bridge.js"></script>'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet; never log tokens in URLs
            pass

        def _send(self, code, body=b"", ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self):
            if self.headers.get("Host") not in hosts:
                self._send(403, b'"bad host"')
                return False
            return True

        def do_GET(self):
            if not self._host_ok():
                return
            url = urlparse(self.path)
            if url.path == "/events":
                if parse_qs(url.query).get("token", [""])[0] != TOKEN:
                    return self._send(403, b'"bad token"')
                return self._events()
            name = "index.html" if url.path in ("/", "") else url.path.lstrip("/")
            path = (ui_dir / name).resolve()
            if ui_dir not in path.parents or not path.is_file():
                return self._send(404, b'"not found"')
            body = path.read_bytes()
            if name in ("index.html", "overlay.html"):  # pages that talk to Jarvis get the bridge before their scripts
                body = body.replace(b"<!--bridge-->", bridge.encode())
            self._send(200, body, mimetypes.guess_type(name)[0] or "application/octet-stream")

        def do_POST(self):
            if not self._host_ok():
                return
            if self.headers.get("X-Jarvis-Token") != TOKEN:
                return self._send(403, b'"bad token"')
            name = self.path.removeprefix("/api/")
            if name not in methods:
                return self._send(404, b'"unknown method"')
            try:
                args = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"[]")
                result = getattr(api, name)(*args)
                self._send(200, json.dumps(result, default=str).encode())
            except Exception as e:
                log.exception("api %s", name)
                self._send(500, json.dumps({"error": str(e)[:300]}).encode())

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

    return Handler


def serve(j, api, ui_dir, port=8765, open_browser=True):
    hub = Hub()
    j.on_event = hub.publish
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(api, ui_dir.resolve(), port, hub))
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
