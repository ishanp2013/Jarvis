"""Game detection for game mode: is a game in the foreground right now?

Uses Windows' own "full-screen app running" signal (the one Focus Assist uses) plus whether the
foreground program lives in a Steam or Epic library folder, so full-screen videos in a browser don't count."""
import ctypes
import os

import psutil
import win32gui
import win32process

from . import games

QUNS_BUSY, QUNS_D3D_FULLSCREEN, QUNS_PRESENTATION = 2, 3, 4
NOT_GAMES = {"opera.exe", "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "vlc.exe", "spotify.exe",
             "explorer.exe", "powerpnt.exe", "applicationframehost.exe", "python.exe", "pythonw.exe", "discord.exe",
             "whatsapp.exe", "steamwebhelper.exe", "epicgameslauncher.exe", "steam.exe"}
GAME_DIR_HINTS = ("\\steamapps\\common\\", "\\epic games\\", "\\riot games\\", "\\xboxgames\\", "\\ea games\\",
                  "\\ubisoft game launcher\\games\\", "\\battle.net\\")


def _notification_state():
    state = ctypes.c_int(0)
    try:
        ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
    except (OSError, AttributeError):
        return 0
    return state.value


def foreground_exe():
    try:
        _, pid = win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())
        return psutil.Process(pid).exe()
    except (psutil.Error, OSError, ValueError):
        return ""


def detect():
    """(True, game name) when a game is in the foreground, else (False, "")."""
    exe = foreground_exe()
    name = os.path.basename(exe).lower()
    if not exe or name in NOT_GAMES:
        return False, ""
    path = exe.lower()
    title = os.path.splitext(os.path.basename(exe))[0]
    if any(h in path for h in GAME_DIR_HINTS) or any(path.startswith(f + os.sep) for f in games.game_folders()):
        return True, title
    if _notification_state() == QUNS_D3D_FULLSCREEN:
        return True, title
    return False, ""
