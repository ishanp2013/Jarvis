"""WhatsApp: there is no official API for a personal account, so Jarvis works through the WhatsApp
desktop app: it opens the chat with the message typed in and, for saved contacts, presses Send
(unless "Ask before sending" is on). It can't read chats.

WhatsApp links can target a chat only by phone number, so names are looked up in a small contact
list kept in Jarvis's local settings."""
import difflib
import os
import re
import time
import urllib.parse

from ..config import settings

# Speech recognition often writes the app's name in other ways.
_APP_NAME = re.compile(r"\bwhat'?s\s?app\b|\bwhats\s?up\b(?=\s*$)", re.I)

_PATTERNS = [
    # "send hi to sam on whatsapp"
    re.compile(r"^(?:please )?(?:send|text|message|whatsapp|tell)\s+(?P<msg>.+?)\s+to\s+(?P<name>[\w .'-]+?)\s+(?:on|in|via|through|using|over)\s+whatsapp$", re.I),
    # "send sam a whatsapp saying hi"
    re.compile(r"^(?:send|write)\s+(?P<name>[\w .'-]+?)\s+a\s+whatsapp(?: message)?\s*(?:saying|that says|:)?\s*(?P<msg>.+)$", re.I),
    # "message sam on whatsapp saying hi" / "whatsapp sam: hi"
    re.compile(r"^(?:please )?(?:send|text|message|whatsapp)\s+(?:a message to\s+)?(?P<name>[\w .'-]+?)\s+(?:(?:on|in|via)\s+whatsapp\s*)?(?:saying|that says|that|:)\s*(?P<msg>.+)$", re.I),
    # "on whatsapp, send hi to sam"
    re.compile(r"^(?:on|in)\s+whatsapp,?\s+(?:send|text|tell)\s+(?P<msg>.+?)\s+to\s+(?P<name>[\w .'-]+)$", re.I),
]


def normalise(text):
    return _APP_NAME.sub("whatsapp", text.strip().rstrip(".!?"))


def parse(text):
    """Return (name, message) for a WhatsApp send request, or None."""
    t = normalise(text)
    if "whatsapp" not in t.lower():
        return None
    for p in _PATTERNS:
        m = p.match(t)
        if m:
            msg = m.group("msg").strip().strip("\"'")
            return m.group("name").strip(), msg
    return None


def contacts():
    return dict(settings["whatsapp_contacts"] or {})


def find_contact(name):
    book = contacts()
    lowered = {k.lower(): k for k in book}
    key = name.lower().strip()
    if key in lowered:
        return lowered[key], book[lowered[key]]
    close = difflib.get_close_matches(key, list(lowered), n=1, cutoff=0.75)
    return (lowered[close[0]], book[lowered[close[0]]]) if close else (None, None)


def save_contact(name, phone):
    digits = re.sub(r"\D", "", phone or "")
    if not name.strip() or len(digits) < 8:
        raise ValueError("Give a name and a full number with country code, e.g. +971 50 123 4567.")
    book = contacts()
    book[name.strip()] = digits
    settings.update({"whatsapp_contacts": book})
    return book


def remove_contact(name):
    book = contacts()
    book.pop(name, None)
    settings.update({"whatsapp_contacts": book})
    return book


def open_with_message(text, phone=""):
    if not settings["whatsapp_enabled"]:
        return "WhatsApp drafts are turned off in Connections."
    digits = re.sub(r"\D", "", phone or "")
    q = urllib.parse.quote(text)
    # The desktop app handles whatsapp:// directly; wa.me is the documented web fallback.
    try:
        os.startfile(f"whatsapp://send?{'phone=' + digits + '&' if digits else ''}text={q}")
    except OSError:
        os.startfile(f"https://wa.me/{digits}?text={q}")
    return "WhatsApp is open with your message ready. Check it, then press Send." if digits else \
        "WhatsApp is open with your message ready. Choose the chat, then press Send."


def _whatsapp_in_front(timeout):
    import psutil
    import win32gui
    import win32process
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = win32gui.GetForegroundWindow()
        try:
            if "whatsapp" in psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower():
                return True
        except (psutil.Error, ValueError):
            pass
        time.sleep(0.3)
    return False


def send_to(name, text):
    """Opens the saved contact's chat with `text` typed in and presses Enter in WhatsApp to send it.
    Only for saved contacts (a name alone can't pick a chat), and only once WhatsApp is the window in front."""
    if not settings["whatsapp_enabled"]:
        return "WhatsApp is turned off in Connections."
    found, phone = find_contact(name)
    if not phone:
        return draft_to(name, text) + " I can only send by myself to contacts saved in Connections."
    open_with_message(text, phone)
    if not _whatsapp_in_front(12):
        return f"WhatsApp didn't come to the front, so I left the message to {found} typed in but unsent."
    time.sleep(2.5)  # let the chat finish loading with the text in the box
    if not _whatsapp_in_front(1):
        return f"You switched away from WhatsApp, so I left the message to {found} unsent."
    import win32api
    import win32con
    win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
    win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
    return f"Sent to {found} on WhatsApp."


def draft_to(name, text):
    """Open WhatsApp at `name`'s chat (if saved) with `text` typed in. Never sends."""
    found, phone = find_contact(name) if name else (None, None)
    result = open_with_message(text, phone or "")
    if name and not found and settings["whatsapp_enabled"]:
        result += f" I don't have a number saved for {name}; add one in Connections to open their chat directly."
    return result
