"""Where the agent looks: Google Classroom (school account), your Google calendars (a school calendar shared with
your personal account shows up here), Gmail (including Classroom's emails forwarded from a
school account that can't be connected), Outlook, WhatsApp Desktop on this PC (each chat's latest message, read
from the chat list without opening anything), phone notifications (through KDE Connect) and the Discord
channels you selected.

Each collector returns only items it hasn't seen before. Every item is marked school or not, using your
list of school senders (Settings -> Agent). School items always go to the AI; personal ones only when
"find to-dos in personal messages" is on, and never newsletters, no-reply mail and the like (see worth_reading)."""
import datetime as dt
import logging
import re

from ..config import settings
from ..tools import classroom, discord, google, microsoft, phone, whatsapp

log = logging.getLogger("agent")
MESSAGE_APPS = {"whatsapp", "whatsapp business", "classroom", "google classroom", "discord", "telegram", "messages", "gmail"}


def school_patterns():
    return [p.strip().lower() for p in re.split(r"[\n,;]", settings.get("agent_school_senders") or "") if p.strip()]


# Google Classroom's own emails (new work, announcements, comments, due-date reminders). A school account that
# can't be connected can forward just these to your personal Gmail, which Jarvis reads.
CLASSROOM_MAIL = re.compile(r"@classroom\.google\.com\s*$|^classroom\.google\.com$", re.I)


# Calendar entries that are school work, e.g. Classroom's "Assignment: Worksheets on pressure".
SCHOOL_EVENT = re.compile(r"^\s*(?:assignment|due|homework|quiz|test|exam|project|worksheet|classwork|question)\b", re.I)


def is_school(item, patterns=None):
    if item["source"] == "classroom":
        return True
    if item["source"] == "calendar" and SCHOOL_EVENT.search(str(item.get("title", ""))):
        return True
    if CLASSROOM_MAIL.search(str(item.get("address", "")).strip()):
        return True
    pats = school_patterns() if patterns is None else patterns
    hay = " ".join(str(item.get(k, "")) for k in ("sender", "address", "group")).lower()
    return any(p in hay for p in pats)


# Mail that is never a personal to-do: automated senders, newsletters, receipts and the like.
AUTOMATED = re.compile(r"(?:^|[._+-])(?:no-?reply|do-?not-?reply|notifications?|notify|alerts?|newsletters?|news|"
                       r"mailer(?:-daemon)?|marketing|promo(?:tions?)?|offers?|deals|updates?|digest|info|hello|team|"
                       r"support|billing|receipts?|accounts?|security|bounce)(?:[._+-]|@)", re.I)


def worth_reading(item):
    """A personal item that could hold a to-do for you: not your own message, not an automated email."""
    if item.get("from_me"):
        return False
    if item["source"] in ("gmail", "outlook") and AUTOMATED.search(str(item.get("address", "")).lower()):
        return False
    return bool((item.get("text") or item.get("title") or "").strip())


def _gmail():
    out, ids = [], set()
    # the inbox, plus Classroom emails wherever a filter put them (forwarded ones can skip the inbox)
    for q in ("in:inbox newer_than:3d", "from:classroom.google.com newer_than:7d -in:trash -in:spam"):
        for m in google.search_mail(q, 25):
            if m["id"] in ids:
                continue
            ids.add(m["id"])
            out.append({"source": "gmail", "ext_id": m["id"], "sender": m["from"], "address": m["from_address"],
                        "title": m["subject"], "text": m["preview"], "when": m["received"], "url": ""})
    return out


def _calendar():
    """Entries on the Google calendars you can see over the next 2 weeks that look like school work, or that sit on a
    calendar named like a school sender. This is how a school calendar shared with your personal Google account
    (or a class calendar added to it) reaches Scholar without touching the school account."""
    out, pats = [], school_patterns()
    for e in google.events(14, limit=100):
        if e["calendar_id"].endswith("holiday@group.v.calendar.google.com"):
            continue
        if not (SCHOOL_EVENT.search(e["subject"]) or any(p in e["calendar"].lower() for p in pats)):
            continue
        out.append({"source": "calendar", "ext_id": f"{e['id']}|{e['start']}", "sender": e["calendar"], "group": e["calendar"],
                    "title": e["subject"], "text": e["description"], "due": e["start"][:10], "when": e["start"], "url": ""})
    return out


def _outlook():
    out = []
    for m in microsoft.unread(25):
        out.append({"source": "outlook", "ext_id": m["id"], "sender": m.get("from", ""), "address": m.get("from_address", ""),
                    "title": m.get("subject", ""), "text": m.get("preview", ""), "when": m.get("received", ""), "url": ""})
    return out


def _classroom():
    out = []
    for w in classroom.recent():
        out.append({"source": "classroom", "ext_id": w["id"] + "@" + w["updated"][:16], "sender": w["course"], "group": w["course"],
                    "title": (("Classwork: " + w["title"]) if w["kind"] == "classwork" else "Announcement"),
                    "text": w["text"], "due": w["due"], "when": w["updated"], "url": w["url"]})
    return out


def _phone():
    out = []
    day = dt.date.today().isoformat()
    for n in phone.notifications():
        if n["app"].lower() not in MESSAGE_APPS:
            continue
        # A notification only shows its title (a group or a person); one entry per chat per day is enough.
        out.append({"source": "phone", "ext_id": f"{n['app']}|{n['title']}|{day}", "sender": n["title"], "group": n["title"],
                    "title": f"{n['app']}: {n['title']}", "text": n.get("text", ""), "when": day, "url": ""})
    return out


def _whatsapp_quiet():
    """Reading the chat list needs WhatsApp's window un-minimised for a moment. In the background that's only done
    when it won't get in your way: the window is already open, or you haven't touched the PC for a minute."""
    import win32gui
    try:
        return not win32gui.IsIconic(whatsapp._window()) or _idle_seconds() >= 60
    except whatsapp.ReadError:  # closed to the tray: bringing it back is only done while you're away
        return _idle_seconds() >= 60


def _idle_seconds():
    """Seconds since the last keyboard or mouse input on this PC."""
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 0
    return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000


WAITING = {"whatsapp": False}  # WhatsApp was skipped because you were busy; the agent retries when you pause


def whatsapp_due():
    """True when a skipped WhatsApp read can run now (you've paused, or WhatsApp is open)."""
    return WAITING["whatsapp"] and _whatsapp_ready() and _whatsapp_quiet()


def _whatsapp():
    out = []
    if not _whatsapp_quiet():
        WAITING["whatsapp"] = True
        log.info("whatsapp: skipped, you're busy; will read it as soon as you pause")
        return out
    WAITING["whatsapp"] = False
    if not whatsapp.wake():
        raise RuntimeError("WhatsApp Desktop is closed and wouldn't reopen. Open it once so I can read your groups.")
    for c in whatsapp.recent_chats():
        if c.get("from_me") or c.get("reaction") or not (c.get("text") or "").strip():
            continue
        out.append({"source": "whatsapp", "ext_id": f"{c['chat']}|{c.get('time', '')}|{c['text'][:80]}",
                    "sender": c.get("sender") or c["chat"], "group": c["chat"], "title": f"WhatsApp: {c['chat']}",
                    "text": c["text"], "when": c.get("time", ""), "url": "", "unread": c.get("unread", 0)})
    return out


def _whatsapp_ready():
    if not (settings.get("agent_whatsapp", True) and settings.get("whatsapp_read", True)):
        return False
    try:
        return whatsapp.running()  # a window isn't needed: it may be closed to the tray
    except Exception:
        return False


def _discord():
    out = []
    for name in discord.selected_channels():
        for m in discord.read_channel(name, 20)["messages"]:
            out.append({"source": "discord", "ext_id": f"{name}|{m['time']}|{m['author']}", "sender": m["author"], "group": name,
                        "title": f"#{name}", "text": m["text"], "when": m["time"], "url": ""})
    return out


COLLECTORS = {
    "classroom": (classroom.connected, _classroom),
    "gmail": (google.connected, _gmail),
    "calendar": (google.connected, _calendar),
    "outlook": (microsoft.connected, _outlook),
    "whatsapp": (_whatsapp_ready, _whatsapp),
    "phone": (lambda: bool(phone.cli()), _phone),
    "discord": (discord.connected, _discord),
}


def collect(store):
    """(new items, problems): every source that's connected, new items only, each marked school or not."""
    items, problems = [], []
    pats = school_patterns()
    for name, (ready, fetch) in COLLECTORS.items():
        try:
            if not ready():
                continue
            for it in fetch():
                if not store.seen(it["source"], it["ext_id"]):
                    it["school"] = is_school(it, pats)
                    items.append(it)
        except Exception as e:  # one broken source mustn't stop the others
            log.warning("agent source %s failed: %s", name, e)
            problems.append(f"{name}: {str(e)[:160]}")
    return items, problems
