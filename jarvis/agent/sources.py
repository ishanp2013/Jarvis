"""Where the agent looks: Google Classroom (school account), Gmail (including Classroom's emails forwarded from a
school account that can't be connected), Outlook, phone notifications (WhatsApp groups and the like, through
KDE Connect) and the Discord channels you selected.

Each collector returns only items it hasn't seen before. Every item is marked school or not, using your
list of school senders (Settings -> Agent). Only school items are ever sent to the AI."""
import datetime as dt
import logging
import re

from ..config import settings
from ..tools import classroom, discord, google, microsoft, phone

log = logging.getLogger("agent")
MESSAGE_APPS = {"whatsapp", "whatsapp business", "classroom", "google classroom", "discord", "telegram", "messages", "gmail"}


def school_patterns():
    return [p.strip().lower() for p in re.split(r"[\n,;]", settings.get("agent_school_senders") or "") if p.strip()]


# Google Classroom's own emails (new work, announcements, comments, due-date reminders). A school account that
# can't be connected can forward just these to your personal Gmail, which Jarvis reads.
CLASSROOM_MAIL = re.compile(r"@classroom\.google\.com\s*$|^classroom\.google\.com$", re.I)


def is_school(item, patterns=None):
    if item["source"] == "classroom":
        return True
    if CLASSROOM_MAIL.search(str(item.get("address", "")).strip()):
        return True
    pats = school_patterns() if patterns is None else patterns
    hay = " ".join(str(item.get(k, "")) for k in ("sender", "address", "group")).lower()
    return any(p in hay for p in pats)


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
    "outlook": (microsoft.connected, _outlook),
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
