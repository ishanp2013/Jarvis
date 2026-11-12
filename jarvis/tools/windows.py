"""Windows desktop control: launch, switch, close apps; open sites; system info."""
import difflib
import json
import os
import subprocess
import time
import urllib.parse
from pathlib import Path

import psutil
import win32api
import win32con
import win32gui
import win32process

from ..config import settings

CREATE_NO_WINDOW = 0x08000000

# Friendly names people say -> executable stems, for finding running windows.
ALIASES = {
    "opera gx": "opera", "opera": "opera", "browser": "opera", "chrome": "chrome", "edge": "msedge",
    "discord": "discord", "spotify": "spotify", "outlook": "olk", "outlook classic": "outlook",
    "whatsapp": "whatsapp", "file explorer": "explorer", "explorer": "explorer", "vs code": "code",
    "visual studio code": "code", "notepad": "notepad", "calculator": "calculatorapp",
    "task manager": "taskmgr", "settings": "systemsettings", "steam": "steam",
}
# Executables we never close, whatever the user says.
PROTECTED = {"explorer", "csrss", "winlogon", "lsass", "services", "svchost", "dwm", "python", "pythonw",
             "msedgewebview2", "system", "smss", "wininit"}

_apps_cache = {"t": 0, "apps": []}


def start_apps():
    """Start-menu apps (name, AppID). Cached for 10 minutes."""
    if time.time() - _apps_cache["t"] < 600 and _apps_cache["apps"]:
        return _apps_cache["apps"]
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", "Get-StartApps | ConvertTo-Json -Compress"],
        capture_output=True, text=True, timeout=30, creationflags=CREATE_NO_WINDOW,
    ).stdout
    try:
        apps = [{"name": a["Name"], "appid": a["AppID"]} for a in json.loads(out)]
    except (ValueError, TypeError):
        apps = []
    _apps_cache.update(t=time.time(), apps=apps)
    return apps


def _best(name, choices, cutoff=0.6):
    name = name.lower().strip()
    lowered = {c.lower(): c for c in choices}
    if name in lowered:
        return lowered[name]
    starts = [c for c in lowered if c.startswith(name) or name in c.split()]
    if starts:
        return lowered[min(starts, key=len)]
    m = difflib.get_close_matches(name, list(lowered), n=1, cutoff=cutoff)
    return lowered[m[0]] if m else None


def browser_path():
    p = settings["browser_path"]
    return p if p and Path(p).exists() else ""


def open_url(url):
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    b = browser_path()
    if b:
        subprocess.Popen([b, url], creationflags=CREATE_NO_WINDOW)
    else:
        os.startfile(url)
    return f"Opened {url}" + ("" if b else " in the default browser (Opera GX not found)")


def youtube(query=None):
    if query:
        return open_url("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
    return open_url("https://www.youtube.com")


def open_app(name):
    n = name.lower().strip()
    if n in ("opera gx", "opera", "browser", "my browser") and browser_path():
        subprocess.Popen([browser_path()], creationflags=CREATE_NO_WINDOW)
        return "Opening Opera GX."
    apps = start_apps()
    match = _best(n, [a["name"] for a in apps])
    if not match:
        return f"I couldn't find an app called {name}."
    appid = next(a["appid"] for a in apps if a["name"] == match)
    subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{appid}"], creationflags=CREATE_NO_WINDOW)
    return f"Opening {match}."


def _windows():
    """Visible top-level windows: [(hwnd, title, exe_stem, pid)]."""
    found = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindow(hwnd, win32con.GW_OWNER):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title or title in ("Program Manager", "Windows Input Experience"):
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        try:
            exe = Path(psutil.Process(pid).name()).stem.lower()
        except psutil.Error:
            return True
        if exe == "applicationframehost":  # UWP host: use title instead
            exe = title.lower()
        found.append((hwnd, title, exe, pid))
        return True

    win32gui.EnumWindows(cb, None)
    return found


def find_windows(name):
    n = name.lower().strip()
    stem = ALIASES.get(n, n.replace(" ", ""))
    wins = _windows()
    hits = [w for w in wins if w[2] == stem or w[2].startswith(stem)]
    if not hits:
        hits = [w for w in wins if n in w[1].lower()]
    return hits


def running_apps():
    seen, apps = set(), []
    for _, title, exe, _ in _windows():
        if exe in seen or exe in ("msedgewebview2",):
            continue
        seen.add(exe)
        apps.append({"app": exe, "title": title[:80]})
    return apps


def switch_to(name):
    hits = find_windows(name)
    if not hits:
        return f"{name} doesn't seem to be open."
    hwnd = hits[0][0]
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    # Windows only lets the foreground process change focus; a synthetic Alt press satisfies that rule.
    win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
    try:
        win32gui.SetForegroundWindow(hwnd)
    finally:
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)
    return f"Switched to {hits[0][1]}."


def close_target(name):
    """Describe what closing `name` would affect, without doing it (for the confirmation card)."""
    hits = [w for w in find_windows(name) if w[2] not in PROTECTED]
    return hits


def close_app(name):
    hits = close_target(name)
    if not hits:
        return f"{name} doesn't seem to be open."
    for hwnd, *_ in hits:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)  # polite close: apps can still ask to save
    return f"Asked {len(hits)} {name} window(s) to close."


def system_info():
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
    info = {
        "cpu_percent": psutil.cpu_percent(interval=0.3),
        "ram_used_gb": round(vm.used / 2**30, 1),
        "ram_total_gb": round(vm.total / 2**30, 1),
        "ram_percent": vm.percent,
        "disk_free_gb": round(disk.free / 2**30, 1),
        "uptime_hours": round((time.time() - psutil.boot_time()) / 3600, 1),
    }
    bat = psutil.sensors_battery()
    if bat:
        info["battery_percent"] = round(bat.percent)
        info["plugged_in"] = bool(bat.power_plugged)
    return info


def top_processes(n=5):
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["memory_info"].rss, p.info["name"]))
        except (psutil.Error, AttributeError, TypeError):
            pass
    agg = {}
    for rss, name in procs:
        agg[name] = agg.get(name, 0) + rss
    top = sorted(agg.items(), key=lambda kv: -kv[1])[:n]
    return [{"name": k, "ram_mb": round(v / 2**20)} for k, v in top]


def media_key(action):
    keys = {"volume up": win32con.VK_VOLUME_UP, "volume down": win32con.VK_VOLUME_DOWN,
            "mute": win32con.VK_VOLUME_MUTE, "play pause": win32con.VK_MEDIA_PLAY_PAUSE,
            "next": win32con.VK_MEDIA_NEXT_TRACK, "previous": win32con.VK_MEDIA_PREV_TRACK}
    vk = keys.get(action)
    if vk is None:
        return "Unknown media action."
    for _ in range(5 if action.startswith("volume") else 1):
        win32api.keybd_event(vk, 0, 0, 0)
        win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
    return "Done."


def lock_pc():
    import ctypes
    ctypes.windll.user32.LockWorkStation()
    return "Locking the computer."


def power_action(action, delay=30):
    """Restart or shut down after a countdown, using Windows' own shutdown command. cancel_power() stops it."""
    flag = {"restart": "/r", "reboot": "/r", "shutdown": "/s", "shut down": "/s"}.get(action.lower().strip())
    if not flag:
        return f"I can restart or shut down the laptop, not {action}."
    verb = "Restarting" if flag == "/r" else "Shutting down"
    r = subprocess.run(["shutdown", flag, "/t", str(int(delay)), "/c", f"Jarvis: {verb.lower()} in {int(delay)} seconds."],
                       capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        return f"Windows refused: {(r.stderr or r.stdout).strip()[:120]}"
    return f"{verb} the laptop in {int(delay)} seconds. Say cancel shutdown to stop it."


def cancel_power():
    r = subprocess.run(["shutdown", "/a"], capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    return "Cancelled the restart or shutdown." if r.returncode == 0 else "There was no restart or shutdown to cancel."


def save_screenshot():
    """Saves the current screen to Pictures\\Screenshots and returns the path."""
    import datetime as dt
    from . import screen
    folder = Path(os.path.expanduser("~")) / "Pictures" / "Screenshots"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / dt.datetime.now().strftime("Jarvis %Y-%m-%d %H-%M-%S.png")
    path.write_bytes(screen.capture(max_width=10000))
    return str(path)
