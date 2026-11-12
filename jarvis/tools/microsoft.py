"""Microsoft Graph (Outlook.com mail, Outlook Calendar, Microsoft To Do) with official MSAL sign-in.

Uses delegated permissions for the signed-in personal Microsoft account only. The token cache is
encrypted with Windows DPAPI, so only this Windows user can read it.
"""
import datetime as dt
import subprocess

import httpx
import msal
import win32crypt

from ..config import HOME, settings

AUTHORITY = "https://login.microsoftonline.com/consumers"
SCOPES = ["User.Read", "Mail.Read", "Mail.Send", "Calendars.ReadWrite", "Tasks.ReadWrite"]
GRAPH = "https://graph.microsoft.com/v1.0"
CACHE_FILE = HOME / "ms_token.bin"


def _load_cache():
    cache = msal.SerializableTokenCache()
    if CACHE_FILE.exists():
        try:
            blob = win32crypt.CryptUnprotectData(CACHE_FILE.read_bytes(), None, None, None, 0)[1]
            cache.deserialize(blob.decode())
        except Exception:
            CACHE_FILE.unlink(missing_ok=True)
    return cache


def _save_cache(cache):
    if cache.has_state_changed:
        blob = win32crypt.CryptProtectData(cache.serialize().encode(), "jarvis-ms", None, None, None, 0)
        CACHE_FILE.write_bytes(blob)


def _app():
    cid = settings["ms_client_id"].strip()
    if not cid:
        raise RuntimeError("Microsoft isn't set up yet. Add your app's client ID in Integrations.")
    cache = _load_cache()
    return msal.PublicClientApplication(cid, authority=AUTHORITY, token_cache=cache), cache


def connect():
    """Interactive sign-in in the system browser (official Microsoft login page)."""
    app, cache = _app()
    result = app.acquire_token_interactive(SCOPES, prompt="select_account", timeout=300)
    _save_cache(cache)
    if "access_token" not in result:
        raise RuntimeError(result.get("error_description", "Sign-in was cancelled."))
    settings.update({"ms_enabled": True})
    return account_name()


def disconnect():
    CACHE_FILE.unlink(missing_ok=True)
    settings.update({"ms_enabled": False})


def connected():
    if not settings["ms_enabled"] or not settings["ms_client_id"]:
        return False
    try:
        app, _ = _app()
        return bool(app.get_accounts())
    except Exception:
        return False


def _token():
    app, cache = _app()
    accounts = app.get_accounts()
    result = app.acquire_token_silent(SCOPES, account=accounts[0]) if accounts else None
    _save_cache(cache)
    if not result or "access_token" not in result:
        raise RuntimeError("Microsoft sign-in has expired. Reconnect it in Integrations.")
    return result["access_token"]


_tz = None


def _windows_tz():
    global _tz
    if _tz is None:
        out = subprocess.run(["tzutil", "/g"], capture_output=True, text=True, creationflags=0x08000000)
        _tz = out.stdout.strip() or "UTC"
    return _tz


def _req(method, path, **kw):
    headers = {"Authorization": f"Bearer {_token()}", "Prefer": f'outlook.timezone="{_windows_tz()}", outlook.body-content-type="text"'}
    r = httpx.request(method, GRAPH + path, headers=headers, timeout=20, **kw)
    if r.status_code >= 400:
        try:
            msg = r.json()["error"]["message"]
        except Exception:
            msg = r.text[:200]
        raise RuntimeError(f"Microsoft Graph error {r.status_code}: {msg}")
    return r.json() if r.content else {}


def account_name():
    me = _req("GET", "/me?$select=displayName,userPrincipalName")
    return me.get("userPrincipalName") or me.get("displayName", "")


def _mail_row(m):
    sender = (m.get("from") or {}).get("emailAddress", {})
    return {"id": m["id"], "subject": m.get("subject") or "(no subject)",
            "from": sender.get("name") or sender.get("address", ""), "from_address": sender.get("address", ""),
            "received": m.get("receivedDateTime", ""), "preview": (m.get("bodyPreview") or "")[:300],
            "important": m.get("importance") == "high" or (m.get("flag") or {}).get("flagStatus") == "flagged"}


_MAIL_FIELDS = "id,subject,from,receivedDateTime,bodyPreview,importance,flag,isRead"


def unread(limit=10):
    q = (f"/me/mailFolders/inbox/messages?$top={limit}&$select={_MAIL_FIELDS}"
         "&$filter=receivedDateTime ge 2000-01-01T00:00:00Z and isRead eq false&$orderby=receivedDateTime desc")
    return [_mail_row(m) for m in _req("GET", q).get("value", [])]


def search_mail(query, limit=10):
    safe = query.replace('"', "")
    return [_mail_row(m) for m in _req("GET", f'/me/messages?$search="{safe}"&$top={limit}&$select={_MAIL_FIELDS}').get("value", [])]


def read_mail(msg_id):
    m = _req("GET", f"/me/messages/{msg_id}?$select={_MAIL_FIELDS},body,toRecipients")
    row = _mail_row(m)
    row["body"] = (m.get("body") or {}).get("content", "")[:8000]
    return row


def send_mail(to, subject, body):
    msg = {"subject": subject, "body": {"contentType": "Text", "content": body},
           "toRecipients": [{"emailAddress": {"address": a.strip()}} for a in to.split(",") if a.strip()]}
    _req("POST", "/me/sendMail", json={"message": msg, "saveToSentItems": True})
    return "Email sent."


def reply_mail(msg_id, body):
    _req("POST", f"/me/messages/{msg_id}/reply", json={"comment": body})
    return "Reply sent."


def events(days=7):
    """Events from every calendar on the account, including subscribed ones (e.g. a Google Calendar ICS feed)."""
    start = dt.datetime.now().astimezone()
    end = start + dt.timedelta(days=days)
    window = (f"startDateTime={start.isoformat()}&endDateTime={end.isoformat()}"
              "&$top=25&$select=subject,start,end,location,isAllDay").replace("+", "%2B")
    out = []
    for cal in _req("GET", "/me/calendars?$select=id,name").get("value", []):
        try:
            rows = _req("GET", f"/me/calendars/{cal['id']}/calendarView?{window}").get("value", [])
        except RuntimeError:
            continue  # one unreadable calendar shouldn't hide the rest
        for e in rows:
            out.append({"subject": e.get("subject", ""), "start": e["start"]["dateTime"][:16], "end": e["end"]["dateTime"][:16],
                        "location": (e.get("location") or {}).get("displayName", ""), "all_day": e.get("isAllDay", False),
                        "calendar": cal.get("name", "")})
    return sorted(out, key=lambda e: e["start"])[:25]


def create_event(subject, start, end=None, location=""):
    """start/end are local ISO datetimes, e.g. 2026-11-04T15:00."""
    s = dt.datetime.fromisoformat(start)
    e = dt.datetime.fromisoformat(end) if end else s + dt.timedelta(hours=1)
    body = {"subject": subject, "start": {"dateTime": s.isoformat(), "timeZone": _windows_tz()},
            "end": {"dateTime": e.isoformat(), "timeZone": _windows_tz()}}
    if location:
        body["location"] = {"displayName": location}
    _req("POST", "/me/events", json=body)
    return f"Added '{subject}' to your calendar."


def _default_list():
    lists = _req("GET", "/me/todo/lists").get("value", [])
    for l in lists:
        if l.get("wellknownListName") == "defaultList":
            return l["id"]
    return lists[0]["id"] if lists else None


def tasks(limit=20):
    lid = _default_list()
    if not lid:
        return []
    q = f"/me/todo/lists/{lid}/tasks?$filter=status ne 'completed'&$top={limit}"
    return [{"title": t.get("title", ""), "due": (t.get("dueDateTime") or {}).get("dateTime", "")[:10],
             "importance": t.get("importance", "normal")} for t in _req("GET", q).get("value", [])]


def add_task(title, due=None, reminder=None):
    lid = _default_list()
    body = {"title": title}
    if due:
        body["dueDateTime"] = {"dateTime": dt.datetime.fromisoformat(due).strftime("%Y-%m-%dT00:00:00"), "timeZone": _windows_tz()}
    if reminder:
        body["isReminderOn"] = True
        body["reminderDateTime"] = {"dateTime": dt.datetime.fromisoformat(reminder).isoformat(), "timeZone": _windows_tz()}
    _req("POST", f"/me/todo/lists/{lid}/tasks", json=body)
    return f"Added task '{title}'" + (" with a reminder." if reminder else ".")
