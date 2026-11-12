"""Google (Gmail, Google Calendar, Google Tasks) with Google's official OAuth sign-in.

You sign in on Google's own page in your browser; Jarvis receives the result on a one-time local
address (the "loopback" flow Google documents for desktop apps). Needs your own free OAuth client
(Google Cloud console, "Desktop app"); see SETUP.md. Tokens are encrypted with Windows DPAPI.

Exposes the same functions as microsoft.py (unread, search_mail, read_mail, send_mail, reply_mail,
events, create_event, tasks, add_task), so every email/calendar/task command works with Gmail too."""
import base64
import datetime as dt
import email.utils
import hashlib
import json
import secrets
import threading
import time
import urllib.parse
import webbrowser
from email.message import EmailMessage
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import win32crypt

from ..config import HOME, get_secret, settings

SCOPES = ["openid", "email", "https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send",
          "https://www.googleapis.com/auth/calendar.events", "https://www.googleapis.com/auth/calendar.readonly",
          "https://www.googleapis.com/auth/tasks", "https://www.googleapis.com/auth/drive.readonly"]
AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
TOKEN_FILE = HOME / "google_token.bin"
_lock = threading.Lock()


# ------------------------------------------------------------------ tokens
def _load():
    if not TOKEN_FILE.exists():
        return {}
    try:
        return json.loads(win32crypt.CryptUnprotectData(TOKEN_FILE.read_bytes(), None, None, None, 0)[1])
    except Exception:
        TOKEN_FILE.unlink(missing_ok=True)
        return {}


def _save(tok):
    TOKEN_FILE.write_bytes(win32crypt.CryptProtectData(json.dumps(tok).encode(), "jarvis-google", None, None, None, 0))


def _client():
    cid, secret = settings.get("google_client_id", "").strip(), get_secret("google_client_secret")
    if not cid or not secret:
        raise RuntimeError("Google isn't set up yet. Add your OAuth client ID and secret in Connections.")
    return cid, secret


def connect(timeout=300):
    """Opens Google's sign-in page and waits for the result on a one-time local port."""
    cid, secret = _client()
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state:
                got.update({k: v[0] for k, v in q.items()})
            ok = "code" in got
            body = ("<h2>Jarvis is connected to Google. You can close this tab.</h2>" if ok
                    else "<h2>Google sign-in didn't finish. Close this tab and try again.</h2>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    redirect = f"http://127.0.0.1:{srv.server_address[1]}"
    webbrowser.open(AUTH + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": " ".join(SCOPES),
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "access_type": "offline", "prompt": "consent"}))
    srv.timeout = 2
    deadline = time.time() + timeout
    try:
        while "code" not in got and "error" not in got and time.time() < deadline:
            srv.handle_request()
    finally:
        srv.server_close()
    if "code" not in got:
        raise RuntimeError("Google sign-in was cancelled or timed out." if "error" not in got else f"Google said: {got['error']}")
    r = httpx.post(TOKEN, data={"code": got["code"], "client_id": cid, "client_secret": secret, "redirect_uri": redirect,
                                "grant_type": "authorization_code", "code_verifier": verifier}, timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"Google sign-in failed: {r.text[:200]}")
    tok = r.json()
    tok["expires_at"] = time.time() + tok.get("expires_in", 3600) - 60
    _save(tok)
    settings.update({"google_enabled": True})
    return account_name()


def disconnect():
    tok = _load()
    if tok.get("refresh_token"):
        try:  # also revoke it at Google, so the old token can't be used anywhere
            httpx.post("https://oauth2.googleapis.com/revoke", data={"token": tok["refresh_token"]}, timeout=10)
        except httpx.HTTPError:
            pass
    TOKEN_FILE.unlink(missing_ok=True)
    settings.update({"google_enabled": False})


def connected():
    return bool(settings.get("google_enabled") and _load().get("refresh_token"))


def _token():
    with _lock:
        tok = _load()
        if not tok.get("refresh_token"):
            raise RuntimeError("Google isn't connected. Sign in under Connections.")
        if time.time() < tok.get("expires_at", 0):
            return tok["access_token"]
        cid, secret = _client()
        r = httpx.post(TOKEN, data={"client_id": cid, "client_secret": secret, "refresh_token": tok["refresh_token"],
                                    "grant_type": "refresh_token"}, timeout=20)
        if r.status_code >= 400:
            raise RuntimeError("Google sign-in has expired. Reconnect it under Connections.")
        new = r.json()
        tok.update(access_token=new["access_token"], expires_at=time.time() + new.get("expires_in", 3600) - 60)
        _save(tok)
        return tok["access_token"]


def _req(method, url, **kw):
    r = httpx.request(method, url, headers={"Authorization": f"Bearer {_token()}"}, timeout=20, **kw)
    if r.status_code >= 400:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text[:200]
        if "has not been used in project" in msg or "is disabled" in msg:
            api = next((n for k, n in (("gmail", "Gmail API"), ("calendar", "Google Calendar API"),
                                       ("tasks", "Google Tasks API"), ("drive", "Google Drive API")) if k in msg.lower()), "that API")
            raise RuntimeError(f"The {api} is switched off in your Google Cloud project. Turn it on under "
                               f"APIs & Services, Library, wait a minute, then ask again")
        if r.status_code == 403 and "insufficient" in msg.lower():
            raise RuntimeError("Your Google sign-in doesn't include this permission yet. Press Sign in under "
                               "Connections, Google again and tick every box")
        raise RuntimeError(f"Google error {r.status_code}: {msg}")
    return r.json() if r.content else {}


def account_name():
    return _req("GET", "https://openidconnect.googleapis.com/v1/userinfo").get("email", "")


# ------------------------------------------------------------------ Gmail
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"


def _headers(m):
    return {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}


def _mail_row(m):
    h = _headers(m)
    name, addr = email.utils.parseaddr(h.get("from", ""))
    labels = m.get("labelIds", [])
    return {"id": m["id"], "subject": h.get("subject") or "(no subject)", "from": name or addr, "from_address": addr,
            "received": h.get("date", ""), "preview": m.get("snippet", "")[:300],
            "important": "IMPORTANT" in labels or "STARRED" in labels}


def _list(q, limit):
    ids = _req("GET", f"{GMAIL}/messages", params={"q": q, "maxResults": limit}).get("messages", [])
    return [_mail_row(_req("GET", f"{GMAIL}/messages/{i['id']}", params={"format": "metadata",
            "metadataHeaders": ["From", "Subject", "Date"]})) for i in ids]


def unread(limit=10):
    return _list("is:unread in:inbox", limit)


def search_mail(query, limit=10):
    return _list(query, limit)


def _body(part):
    if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
    for p in part.get("parts", []) or []:
        if (text := _body(p)):
            return text
    return ""


def read_mail(msg_id):
    m = _req("GET", f"{GMAIL}/messages/{msg_id}", params={"format": "full"})
    row = _mail_row(m)
    row["body"] = (_body(m.get("payload", {})) or m.get("snippet", ""))[:8000]
    return row


def _send(msg, thread=None):
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    _req("POST", f"{GMAIL}/messages/send", json={"raw": raw, **({"threadId": thread} if thread else {})})


def send_mail(to, subject, body):
    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    _send(msg)
    return "Email sent from Gmail."


def reply_mail(msg_id, body):
    m = _req("GET", f"{GMAIL}/messages/{msg_id}", params={"format": "metadata",
             "metadataHeaders": ["From", "Subject", "Message-ID", "References", "Reply-To"]})
    h = _headers(m)
    msg = EmailMessage()
    msg["To"] = h.get("reply-to") or h.get("from", "")
    subj = h.get("subject", "")
    msg["Subject"] = subj if subj.lower().startswith("re:") else f"Re: {subj}"
    if h.get("message-id"):
        msg["In-Reply-To"] = h["message-id"]
        msg["References"] = (h.get("references", "") + " " + h["message-id"]).strip()
    msg.set_content(body)
    _send(msg, m.get("threadId"))
    return "Reply sent from Gmail."


# ------------------------------------------------------------------ Calendar
CAL = "https://www.googleapis.com/calendar/v3"


def events(days=7):
    start = dt.datetime.now().astimezone()
    end = start + dt.timedelta(days=days)
    out = []
    for cal in _req("GET", f"{CAL}/users/me/calendarList").get("items", []):
        if not cal.get("selected", True):
            continue
        try:
            rows = _req("GET", f"{CAL}/calendars/{urllib.parse.quote(cal['id'])}/events", params={
                "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
                "orderBy": "startTime", "maxResults": 25}).get("items", [])
        except RuntimeError:
            continue
        for e in rows:
            s, f = e.get("start", {}), e.get("end", {})
            out.append({"subject": e.get("summary", "(no title)"), "start": (s.get("dateTime") or s.get("date", ""))[:16],
                        "end": (f.get("dateTime") or f.get("date", ""))[:16], "location": e.get("location", ""),
                        "all_day": "date" in s, "calendar": cal.get("summary", "")})
    return sorted(out, key=lambda e: e["start"])[:25]


def create_event(subject, start, end=None, location=""):
    s = dt.datetime.fromisoformat(start).astimezone()
    e = dt.datetime.fromisoformat(end).astimezone() if end else s + dt.timedelta(hours=1)
    body = {"summary": subject, "start": {"dateTime": s.isoformat()}, "end": {"dateTime": e.isoformat()}}
    if location:
        body["location"] = location
    _req("POST", f"{CAL}/calendars/primary/events", json=body)
    return f"Added '{subject}' to your Google Calendar."


# ------------------------------------------------------------------ Tasks
TASKS = "https://tasks.googleapis.com/tasks/v1"


def tasks(limit=20):
    rows = _req("GET", f"{TASKS}/lists/@default/tasks", params={"showCompleted": "false", "maxResults": limit}).get("items", [])
    return [{"title": t.get("title", ""), "due": t.get("due", "")[:10], "importance": "normal"} for t in rows]


def add_task(title, due=None, reminder=None):
    body = {"title": title}
    if due or reminder:  # Google Tasks keeps a due date only (no time or separate reminder)
        body["due"] = dt.datetime.fromisoformat(due or reminder).strftime("%Y-%m-%dT00:00:00.000Z")
    _req("POST", f"{TASKS}/lists/@default/tasks", json=body)
    return f"Added task '{title}' to Google Tasks" + (" (Google Tasks reminds on the due date only)." if reminder else ".")


# ------------------------------------------------------------------ Drive (read-only)
DRIVE = "https://www.googleapis.com/drive/v3/files"
_EXPORT = {"application/vnd.google-apps.document": "text/plain", "application/vnd.google-apps.spreadsheet": "text/csv",
           "application/vnd.google-apps.presentation": "text/plain"}


def drive_search(query, limit=8):
    q = query.replace("\\", "").replace("'", "\'")
    res = _req("GET", DRIVE, params={"q": f"(name contains '{q}' or fullText contains '{q}') and trashed = false",
                                     "pageSize": limit, "orderBy": "modifiedTime desc",
                                     "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"})
    return [{"id": f["id"], "name": f["name"], "type": f["mimeType"].split(".")[-1].split("/")[-1],
             "modified": f.get("modifiedTime", "")[:10], "url": f.get("webViewLink", "")} for f in res.get("files", [])]


def drive_read(file_id, max_chars=8000):
    meta = _req("GET", f"{DRIVE}/{file_id}", params={"fields": "id,name,mimeType,webViewLink"})
    mt = meta["mimeType"]
    if mt in _EXPORT:
        r = httpx.get(f"{DRIVE}/{file_id}/export", params={"mimeType": _EXPORT[mt]},
                      headers={"Authorization": f"Bearer {_token()}"}, timeout=30)
    elif mt.startswith("text/") or mt in ("application/json",):
        r = httpx.get(f"{DRIVE}/{file_id}", params={"alt": "media"}, headers={"Authorization": f"Bearer {_token()}"}, timeout=30)
    else:
        return {"name": meta["name"], "url": meta.get("webViewLink", ""), "text": "",
                "note": "This file type can't be read as text; open the link instead."}
    if r.status_code >= 400:
        raise RuntimeError(f"Google Drive error {r.status_code}")
    return {"name": meta["name"], "url": meta.get("webViewLink", ""), "text": r.text[:max_chars]}
