"""Start Jarvis's background core when you sign in to Windows: a shortcut in your own Startup folder
(no admin rights, no system changes). Settings -> Desktop turns it on and off."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHORTCUT = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Jarvis.lnk"


def _pythonw():
    exe = Path(sys.executable)
    w = exe.with_name("pythonw.exe")
    return str(w if w.exists() else exe)


def enabled():
    return SHORTCUT.exists()


def enable():
    import win32com.client
    sc = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(SHORTCUT))
    sc.TargetPath = _pythonw()
    sc.Arguments = "-W ignore -m jarvis --service"
    sc.WorkingDirectory = str(ROOT)
    sc.Description = "Jarvis background assistant"
    sc.WindowStyle = 7  # minimised
    sc.Save()
    return True


def disable():
    if SHORTCUT.exists():
        SHORTCUT.unlink()  # only ever Jarvis's own shortcut
    return False


def set_enabled(on):
    return enable() if on else disable()
