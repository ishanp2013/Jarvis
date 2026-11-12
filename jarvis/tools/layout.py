"""Window layout: "Notepad on the left, Chrome on the right", "maximise Discord", "Spotify on the other screen".

Positions are fractions of a monitor's work area (the screen minus the taskbar). Windows have an invisible
resize border, so the visible frame is measured and the window is grown to make the snap gap-free."""
import ctypes
import re
import time
from ctypes import wintypes

import win32api
import win32con
import win32gui

from . import windows as win

# (left, top, width, height) as fractions of the work area
SPOTS = {
    "left": (0, 0, .5, 1), "right": (.5, 0, .5, 1), "top": (0, 0, 1, .5), "bottom": (0, .5, 1, .5),
    "top left": (0, 0, .5, .5), "top right": (.5, 0, .5, .5), "bottom left": (0, .5, .5, .5), "bottom right": (.5, .5, .5, .5),
    "left third": (0, 0, 1 / 3, 1), "middle third": (1 / 3, 0, 1 / 3, 1), "right third": (2 / 3, 0, 1 / 3, 1),
    "centre": (.15, .1, .7, .8),
}
_WORDS = {"center": "centre", "middle": "centre", "upper": "top", "lower": "bottom", "left side": "left",
          "right side": "right", "left half": "left", "right half": "right", "top half": "top", "bottom half": "bottom"}
_SCREENS = r"(?:other|next|second|2nd|first|1st|main|primary|big|laptop|external)\s+(?:screen|monitor|display)|(?:screen|monitor|display)\s+(?:one|two|1|2)"

_dwm = ctypes.WinDLL("dwmapi")


def _dpi_aware():
    # Coordinates must be physical pixels on every monitor, whatever the calling process's DPI mode.
    try:
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        pass


def monitors():
    """Work areas [(l, t, r, b)], primary first, then left to right."""
    _dpi_aware()
    found = []
    for hmon, _, _ in win32api.EnumDisplayMonitors():
        info = win32api.GetMonitorInfo(hmon)
        found.append((not info["Flags"] & 1, info["Work"][0], info["Work"]))
    return [w for _, _, w in sorted(found)]


def _frame(hwnd):
    """Visible frame (without the invisible resize border)."""
    r = wintypes.RECT()
    if _dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 9, ctypes.byref(r), ctypes.sizeof(r)) == 0:  # DWMWA_EXTENDED_FRAME_BOUNDS
        return r.left, r.top, r.right, r.bottom
    return win32gui.GetWindowRect(hwnd)


def _monitor_of(hwnd):
    mons = monitors()
    info = win32api.GetMonitorInfo(win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST))
    return mons.index(info["Work"]) if info["Work"] in mons else 0


def _screen_index(words, hwnd):
    mons = monitors()
    if not words or len(mons) == 1:
        return _monitor_of(hwnd)
    if re.search(r"other|next", words):
        return (_monitor_of(hwnd) + 1) % len(mons)
    if re.search(r"second|2nd|two|2|external|big", words):
        return 1
    return 0


def place(hwnd, spot, screen=None):
    _dpi_aware()
    if spot == "maximise":
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        if screen is not None:
            place(hwnd, "centre", screen)
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        return
    if spot == "minimise":
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        return
    l, t, r, b = monitors()[screen if screen is not None else _monitor_of(hwnd)]
    fx, fy, fw, fh = SPOTS[spot]
    x, y, w, h = l + round((r - l) * fx), t + round((b - t) * fy), round((r - l) * fw), round((b - t) * fh)
    if win32gui.IsIconic(hwnd) or win32gui.GetWindowPlacement(hwnd)[1] == win32con.SW_SHOWMAXIMIZED:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetWindowPos(hwnd, 0, x, y, w, h, win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)
    # Grow by the invisible border so the visible edges land exactly on the target.
    wl, wt, wr, wb = win32gui.GetWindowRect(hwnd)
    vl, vt, vr, vb = _frame(hwnd)
    win32gui.SetWindowPos(hwnd, 0, x - (vl - wl), y - (vt - wt), w + (vl - wl) + (wr - vr), h + (vt - wt) + (wb - vb),
                          win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE)


def _window_for(app, launch=True):
    hits = [w for w in win.find_windows(app) if w[2] not in win.PROTECTED or w[2] == "explorer" and app.lower() in ("file explorer", "explorer")]
    if hits or not launch:
        return hits[0] if hits else None
    reply = win.open_app(app)
    if reply.startswith("I couldn't"):
        return None
    deadline = time.time() + 10
    while time.time() < deadline:
        time.sleep(0.4)
        if (hits := win.find_windows(app)):
            time.sleep(0.4)  # let it finish appearing before it's moved
            return hits[0]
    return None


def _clause(text):
    """'notepad on the left' -> ('notepad', 'left', None); 'maximise discord' -> ('discord', 'maximise', None)."""
    t = text.strip(" ,.").lower()
    t = re.sub(r"^(?:and\s+|then\s+)+", "", t)
    if m := re.match(r"^(maximi[sz]e|make full ?screen|full ?screen|minimi[sz]e|hide)\s+(?:the\s+)?(.+?)(?:\s+(?:on|to)\s+(?:the\s+)?(" + _SCREENS + "))?$", t):
        spot = "minimise" if m[1].startswith(("minim", "hide")) else "maximise"
        return m[2], spot, m[3]
    m = re.match(r"^(?:put|move|snap|place|throw|send|open|show)?\s*(?:the\s+)?(.+?)\s+(?:on|to|in|at|into)\s+(?:the\s+)?(.+)$", t)
    if not m:
        return None
    app, where = m[1], m[2]
    if re.match(r"(?:what|who|where|which|how|why|is|are|was|does|do|can)\b", app):
        return None  # a question, not a layout
    screen = None
    if s := re.search(_SCREENS, where):
        screen, where = s[0], (where[:s.start()] + where[s.end():]).strip()
        where = re.sub(r"^(?:of|on)\s+(?:the\s+)?|\s+(?:of|on)\s+(?:the\s+)?$", "", where).strip()
    where = re.sub(r"\s+(?:of the screen|side of the screen|of my screen)$", "", where)
    where = _WORDS.get(where, where)
    if not where and screen:
        where = "maximise"
    if where in ("full screen", "fullscreen", "whole screen"):
        where = "maximise"
    if where not in SPOTS and where != "maximise":
        return None
    return app, where, screen


def parse(text):
    """[(app, spot, screen words)] when the whole request is a layout, else None."""
    parts = re.split(r",\s*|\s+and\s+(?=(?:put |move |snap |place |maximi|minimi|the )?[\w .'-]+?\s+(?:on|to|in|at)\s+(?:the\s+)?)|;\s*", text.strip().rstrip(".!?"))
    clauses = [_clause(p) for p in parts if p.strip()]
    return clauses if clauses and all(clauses) else None


def arrange(clauses):
    done, missing = [], []
    for app, spot, screen in clauses:
        w = _window_for(app)
        if not w:
            missing.append(app)
            continue
        place(w[0], spot, _screen_index(screen, w[0]) if screen else None)
        done.append(f"{app} {'maximised' if spot == 'maximise' else 'minimised' if spot == 'minimise' else 'on the ' + spot}")
    if len(monitors()) == 1 and any(s for _, _, s in clauses):
        done.append("(there's only one screen)")
    reply = ("Done: " + ", ".join(done) + ".") if done else ""
    if missing:
        reply += f" I couldn't find or open {', '.join(missing)}."
    return reply.strip()
