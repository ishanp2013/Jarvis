"""Your Android phone, through KDE Connect (free, official, open source; paired by you in its own app).

What works: find my phone (ring), opening links and apps on the phone (YouTube, a WhatsApp chat, Discord),
reading the notifications currently on the phone ("who messaged me"), a ping message.

What Android doesn't allow, so Jarvis doesn't try: unlocking the phone, or pressing Call / Send inside
WhatsApp or Discord on the phone. Messages go through WhatsApp Desktop on the laptop instead (same account)."""
import os
import re
import shutil
import subprocess
import time
import urllib.parse

from ..config import settings

CREATE_NO_WINDOW = 0x08000000
# App links that open the app itself on Android (falling back to the website if it isn't installed).
APPS = {
    "youtube": "https://www.youtube.com", "youtube music": "https://music.youtube.com", "whatsapp": "https://wa.me/",
    "discord": "https://discord.com/app", "spotify": "https://open.spotify.com", "google classroom": "https://classroom.google.com",
    "classroom": "https://classroom.google.com", "gmail": "https://mail.google.com", "instagram": "https://www.instagram.com",
    "maps": "https://maps.google.com", "google maps": "https://maps.google.com", "chrome": "https://www.google.com",
    "google": "https://www.google.com", "drive": "https://drive.google.com", "google drive": "https://drive.google.com",
    "telegram": "https://t.me/", "reddit": "https://www.reddit.com", "x": "https://x.com", "twitter": "https://x.com",
}
UNLOCK_REFUSAL = ("I can't unlock your phone. Android only unlocks with your PIN, fingerprint or face on the phone itself, "
                  "and I won't try to get around that. Everything else I can do for the phone still works while it's locked.")


def cli():
    exe = shutil.which("kdeconnect-cli")
    if exe:
        return exe
    alias = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "kdeconnect-cli.exe")
    return alias if os.path.exists(alias) else None


def _run(*args, timeout=20):
    exe = cli()
    if not exe:
        raise RuntimeError("KDE Connect isn't installed on this laptop. Get it from the Microsoft Store and pair your phone.")
    r = subprocess.run([exe, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=CREATE_NO_WINDOW)
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


_cache = {"at": 0.0, "devices": []}


def devices(refresh=False):
    """[{'id', 'name', 'reachable'}] for paired phones."""
    if not refresh and time.time() - _cache["at"] < 20:
        return _cache["devices"]
    _, out, _ = _run("-l")
    found = []
    for line in out.splitlines():
        m = re.match(r"^- (.+?): (\w+)(?: on .+?)? \((.+)\)$", line.strip())
        if m and "paired" in m.group(3):
            found.append({"id": m.group(2), "name": m.group(1), "reachable": "reachable" in m.group(3)})
    _cache.update(at=time.time(), devices=found)
    return found


def _device():
    devs = devices()
    want = (settings.get("phone_device") or "").strip()
    dev = next((d for d in devs if want and want in (d["id"], d["name"])), None) or next((d for d in devs if d["reachable"]), None) \
        or (devs[0] if devs else None)
    if not dev:
        raise RuntimeError("No phone is paired with KDE Connect. Open KDE Connect on both devices and pair them.")
    if not dev["reachable"]:
        devices(refresh=True)
        dev = next((d for d in _cache["devices"] if d["id"] == dev["id"]), dev)
        if not dev["reachable"]:
            raise RuntimeError(f"I can't reach your {dev['name']} right now. It may be off, out of Wi-Fi and Tailscale, "
                               "or KDE Connect isn't running on it.")
    return dev


def _do(*args):
    dev = _device()
    code, out, err = _run("-d", dev["id"], *args)
    if code != 0:
        raise RuntimeError(f"KDE Connect couldn't do that: {(err or out)[:150]}")
    return dev, out


def status():
    try:
        devs = devices(refresh=True)
    except RuntimeError as e:
        return {"installed": False, "error": str(e), "devices": []}
    return {"installed": True, "devices": devs}


def ring():
    dev, _ = _do("--ring")
    return f"Ringing your {dev['name']}."


def ping(message="Jarvis is connected."):
    dev, _ = _do("--ping-msg", message)
    return f"Sent a message to your {dev['name']}."


def open_url(url):
    if not re.match(r"^(https?|tel|mailto):", url):
        url = "https://" + url
    dev, _ = _do("--share", url)
    return dev


def open_app(name):
    name = name.lower().strip()
    url = APPS.get(name)
    if not url:
        return None
    dev = open_url(url)
    proper = {"youtube": "YouTube", "youtube music": "YouTube Music", "whatsapp": "WhatsApp", "x": "X",
              "google classroom": "Google Classroom", "gmail": "Gmail"}.get(name, name.title())
    return f"Opening {proper} on your {dev['name']}."


def youtube_search(query):
    dev = open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
    return f"Searching YouTube for {query} on your {dev['name']}."


def whatsapp_chat(number, text=""):
    """Opens a WhatsApp chat on the phone (the user presses Call or Send; Android doesn't let Jarvis do it)."""
    url = f"https://wa.me/{number}" + (f"?text={urllib.parse.quote(text)}" if text else "")
    return open_url(url)


def notifications():
    """[{'app', 'title'}] currently showing on the phone. Needs Notification sync on in the phone's KDE Connect app."""
    _, out = _do("--list-notifications")
    rows = []
    for line in out.splitlines():
        m = re.match(r"^- ([^:]+): (.*)$", line.strip())
        if m:
            rows.append({"app": m.group(1).strip(), "title": m.group(2).strip()})
    return rows


MESSAGING = {"whatsapp", "messages", "telegram", "discord", "instagram", "messenger", "signal", "gmail", "outlook",
             "google classroom", "classroom", "slack", "teams", "snapchat"}


def summary(only_messages=False):
    rows = notifications()
    if only_messages:
        rows = [r for r in rows if r["app"].lower() in MESSAGING]
    if not rows:
        return ("No new messages on your phone." if only_messages else "No notifications on your phone right now.") + \
            " If that seems wrong, turn on Notification sync for this laptop in the phone's KDE Connect app."
    by_app = {}
    for r in rows:
        by_app.setdefault(r["app"], []).append(r["title"])
    parts = [f"{app}: {', '.join(t[:80] for t in titles[:3])}" + (f" and {len(titles) - 3} more" if len(titles) > 3 else "")
             for app, titles in by_app.items()]
    return ("Recent messages on your phone. " if only_messages else f"{len(rows)} notifications on your phone. ") + "; ".join(parts) + "."
