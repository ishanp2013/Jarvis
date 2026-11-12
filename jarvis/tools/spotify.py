"""Spotify desktop control without an API key.

Spotify's playback API needs Premium and a developer app, so Jarvis drives the desktop app instead:
it opens a spotify: link (Liked Songs, or a track found by web search), then finds the page's big
green Play button in a capture of the Spotify window and clicks it, putting the mouse back after."""
import ctypes
import difflib
import os
import re
import time
import urllib.parse

import numpy as np
import psutil
import win32api
import win32con
import win32gui
import win32process
import win32ui

from .windows import media_key


SPOTIFY_GREEN = np.array([30, 215, 96])  # #1ED760 (lighter while hovered), the Play button
TRACK_RE = re.compile(r"open\.spotify\.com/(?:intl-\w+/)?track/([A-Za-z0-9]{22})")

_user32 = ctypes.windll.user32


def _per_monitor_dpi():
    # Capture and click coordinates must be physical pixels, like Spotify's own.
    try:
        _user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


def window():
    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h) and win32gui.GetClassName(h) == "Chrome_WidgetWin_1":
            try:
                if psutil.Process(win32process.GetWindowThreadProcessId(h)[1]).name().lower() == "spotify.exe":
                    found.append(h)
            except psutil.Error:
                pass
    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def now_playing():
    """'Artist - Song' while playing, '' when paused or closed (Spotify puts it in the window title)."""
    h = window()
    title = win32gui.GetWindowText(h) if h else ""
    return "" if not title or title.startswith("Spotify") else title


def _open(uri):
    """Open a spotify: link; return (window, whether Spotify had to start)."""
    started = window() is None
    os.startfile(uri)
    deadline = time.time() + (20 if started else 6)
    while time.time() < deadline:
        if (h := window()):
            if win32gui.IsIconic(h):
                win32gui.ShowWindow(h, win32con.SW_SHOWNOACTIVATE)
            return h, started
        time.sleep(0.3)
    return None, started


def _capture(h):
    l, t, r, b = win32gui.GetClientRect(h)
    w, hgt = r - l, b - t
    hdc = win32gui.GetWindowDC(h)
    src = win32ui.CreateDCFromHandle(hdc)
    mem = src.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(src, w, hgt)
    mem.SelectObject(bmp)
    try:
        _user32.PrintWindow(h, mem.GetSafeHdc(), 3)  # client area, full GPU content
        img = np.frombuffer(bmp.GetBitmapBits(True), np.uint8).reshape(hgt, w, 4)[:, :, 2::-1]
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        mem.DeleteDC()
        src.DeleteDC()
        win32gui.ReleaseDC(h, hdc)
    return img


def _green(img):
    return np.abs(img.astype(int) - SPOTIFY_GREEN).sum(axis=-1) < 100


def find_play_button(img):
    """Centre (x, y) of the large green Play button, or None. Small green icons are ignored."""
    mask = _green(img).astype(np.int32)
    side = max(24, img.shape[1] // 50)  # the button is about 1/25 of the window width
    s = np.pad(mask.cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    box = s[side:, side:] - s[:-side, side:] - s[side:, :-side] + s[:-side, :-side]
    y, x = np.unravel_index(box.argmax(), box.shape)
    if box[y, x] < side * side * 0.6:
        return None
    # Centre of the whole green disc, so the icon in the middle can be read. Use the disc's extent,
    # not the mean, since the dark icon isn't centred and a green Shuffle icon may sit beside it.
    cy, cx = y + side // 2, x + side // 2
    y0, x0 = max(0, cy - 3 * side), max(0, cx - 3 * side)
    near = mask[y0:cy + 3 * side, x0:cx + 3 * side]

    def mid(counts):
        lo = hi = int(counts.argmax())
        while lo > 0 and counts[lo - 1] > counts.max() * 0.3:
            lo -= 1
        while hi < len(counts) - 1 and counts[hi + 1] > counts.max() * 0.3:
            hi += 1
        return (lo + hi) // 2
    return mid(near.sum(0)) + x0, mid(near.sum(1)) + y0


def shows_pause(img, spot):
    """True when the big button shows Pause (two bars, green gap in the middle), i.e. that page is playing."""
    x, y = spot
    return bool(_green(img[y - 2:y + 3, x - 1:x + 2]).mean() > 0.5)


def find_shuffle(img, spot):
    """(x, y, on) for the Shuffle toggle just right of the Play button, or None. It turns green when on."""
    x, y = spot
    r = max(12, int(np.sqrt(_green(img[y - 60:y + 60, x - 60:x + 60]).sum() / np.pi)))  # Play button radius
    band = img[y - r // 2:y + r // 2, x + int(1.6 * r):x + int(3.4 * r)]
    light = band.max(axis=-1) > 150  # the icon is pale grey when off, green when on
    if light.sum() < 15:
        return None
    ys, xs = np.nonzero(light)
    if np.ptp(xs) > 1.2 * r:  # wider than an icon: page title text, not the toggle
        return None
    on = _green(band)[ys, xs].mean() > 0.5
    return x + int(1.6 * r) + int(xs.mean()), y - r // 2 + int(ys.mean()), bool(on)


def _click(h, x, y):
    """Click client point (x, y) of Spotify, then put the mouse back. Chromium ignores posted
    mouse messages, so this is a real click; it only happens if Spotify is on top at that point."""
    sx, sy = win32gui.ClientToScreen(h, (x, y))
    if win32gui.GetForegroundWindow() != h:
        win32gui.ShowWindow(h, win32con.SW_SHOW)
        try:
            win32gui.SetForegroundWindow(h)
        except win32gui.error:
            pass
        time.sleep(0.3)
    if win32gui.GetAncestor(win32gui.WindowFromPoint((sx, sy)), win32con.GA_ROOT) != h:
        return False
    old = win32api.GetCursorPos()
    try:
        win32api.SetCursorPos((sx, sy))
        time.sleep(0.05)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0)
        time.sleep(0.05)
    finally:
        win32api.SetCursorPos(old)
    return True


def _wait_playing(seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if now_playing():
            return True
        time.sleep(0.25)
    return False


def _pause():
    if now_playing():
        media_key("play pause")
        time.sleep(0.8)


def _play_uri(uri, press_play, shuffle=False):
    """Open `uri` and make sure it plays. Spotify only acts on a link while paused (a track link then
    starts by itself), so pause first. Pages that don't start get their big Play button pressed;
    a track's page is its album, whose button would play the album from the top, so not for tracks."""
    _per_monitor_dpi()
    _pause()
    h, started = _open(uri)
    if not h:
        return False
    if not press_play:
        return _wait_playing(15 if started else 6)
    time.sleep(6 if started else 1.5)  # let the new page replace the old one
    for _ in range(8):
        img = _capture(h)
        if (spot := find_play_button(img)):
            if shuffle and (sh := find_shuffle(img, spot)) and not sh[2] and _click(h, sh[0], sh[1]):
                # The toggle opens a menu (Shuffle / Smart Shuffle); pick plain Shuffle.
                time.sleep(0.5)
                for vk in (win32con.VK_DOWN, win32con.VK_RETURN):
                    win32api.keybd_event(vk, 0, 0, 0)
                    win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
                    time.sleep(0.3)
            if shows_pause(img, spot):
                return True
            return _click(h, *spot) and _wait_playing(4)
        time.sleep(0.5)
    return False

def _track_hits(query):
    """[(result title, track id)] from the first search engine that finds Spotify track pages.
    Engines are tried one at a time (the mixed default is slower) and any of them may rate-limit."""
    from ddgs import DDGS
    for backend in ("bing", "duckduckgo", "yahoo", "brave", "mojeek"):
        try:
            rows = DDGS().text(f"{query} site:open.spotify.com/track", max_results=10, backend=backend)
        except Exception:
            continue
        hits = [(r.get("title", ""), m.group(1)) for r in rows if (m := TRACK_RE.search(r.get("href", "")))]
        if hits:
            return hits
    return []


def _score(query, title):
    """How well a result title like 'Dracula - song and lyrics by Tame Impala | Spotify' fits the request."""
    # 'Dracula - Sped Up - song and lyrics by X': the version belongs to the song part.
    song = re.split(r"\s+-\s+(?=(?:song|single|ep)\b)", title, maxsplit=1, flags=re.I)[0]
    artist = re.split(r"\s+[|-]\s+Spotify", title.split(" by ", 1)[-1])[0] if " by " in title else ""
    q, s = query.lower(), song.lower()
    best = max(difflib.SequenceMatcher(None, q, s).ratio(),
               difflib.SequenceMatcher(None, q, f"{s} by {artist.lower()}").ratio(),
               difflib.SequenceMatcher(None, q, f"{s} {artist.lower()}").ratio())
    # Prefer the original over remixes, sped-up and live versions unless those were asked for.
    if re.search(r"remix|sped|slowed|live|cover|karaoke|instrumental|version|\(with ", s) and not re.search(r"remix|sped|slowed|live|cover|karaoke|instrumental|version|with", q):
        best -= 0.15
    return best


_found = {}


def find_track(query):
    """(track id, 'Song - Artist') for a song request, found by web search (no Spotify API key needed)."""
    key = query.lower().strip()
    if key in _found:
        return _found[key]
    if not (hits := _track_hits(query)):
        return None, ""
    title, track = max(hits, key=lambda h: _score(query, h[0]))
    _found[key] = track, title.partition(" | ")[0]
    return _found[key]


_ON_SPOTIFY = r"(?:\s+(?:on|in|from|using|with|through)\s+spo\w*fy)?"
_ANY = re.compile(r"^(?:play|put on)\s+(?:me\s+)?(?:any|a|some|random|a random|something|anything)(?:\s+(?:good\s+)?(?:song|songs|music|track|tune|tunes))?" + _ON_SPOTIFY + r"$")
_LIKED = re.compile(r"^(?:play|shuffle|put on)\s+(?:my\s+|all\s+my\s+|the\s+)?(?:liked|favou?rite|saved)(?:\s+(?:songs|music|tracks|playlist))?" + _ON_SPOTIFY + r"$")
_SONG = re.compile(r"^(?:play|put on)\s+(?:the\s+)?(?:song\s+|track\s+)?(.+?)" + _ON_SPOTIFY + r"$")
_NOT_SONGS = {"pause", "music", "it", "again", "the music", "something", "next", "previous", "spotify"}


def parse(text):
    """('any'|'liked'|'song', query) for a play request, or None. Text is lowercase without the wake phrase."""
    t = text.strip().rstrip(".!?")
    if re.search(r"\b(youtube|video)\b", t):
        return None
    if _ANY.match(t):
        return "any", ""
    if _LIKED.match(t):
        return "liked", ""
    if (m := _SONG.match(t)) and m.group(1) not in _NOT_SONGS:
        return "song", m.group(1)
    return None


def play(kind, query=""):
    try:
        if kind == "any":
            return play_any()
        if kind == "liked":
            return play_liked()
        return play_song(query)
    except OSError:
        return "Spotify doesn't seem to be installed. Get it from the Microsoft Store and sign in first."


def play_liked(shuffle=False):
    if not _play_uri("spotify:collection:tracks", press_play=True, shuffle=shuffle):
        return "I opened your Liked Songs in Spotify but couldn't press Play. Press the green Play button."
    return f"{'Shuffling' if shuffle else 'Playing'} your Liked Songs. Now playing: {now_playing()}."


def play_any():
    reply = play_liked(shuffle=True)
    if (first := now_playing()):
        # Play resumes whatever song was loaded; skipping once lands on a random one.
        media_key("next")
        deadline = time.time() + 4
        while time.time() < deadline and now_playing() in (first, ""):
            time.sleep(0.25)
        reply = f"Shuffling your Liked Songs. Now playing: {now_playing() or first}."
    return reply


def play_song(query):
    track, title = find_track(query)
    if not track:
        os.startfile(f"spotify:search:{urllib.parse.quote(query)}")
        return f"I couldn't find \"{query}\" on Spotify, so I've opened a Spotify search for it."
    if not _play_uri(f"spotify:track:{track}", press_play=False):
        return f"I opened {title or query} in Spotify, but it didn't start. Press Play on that song."
    return f"Playing {now_playing()} on Spotify."