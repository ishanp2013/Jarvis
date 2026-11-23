"""Operator's hands on the system: folders and files, and Windows commands.

Rule (the user's): Jarvis just does things, and asks first only for major ones.
- Runs straight away: making folders; moving, copying and renaming files (when your own words asked for it);
  commands that only look at things (listing, searching, network and system info).
- Asks first (approval card): deleting anything (always to the Recycle Bin, never permanently), and any command that
  isn't on the known-harmless list (installing, uninstalling, changing settings, stopping programs, the registry...).
- Never: Windows' own folders, Program Files, other people's profiles, or Jarvis's private data folder."""
import os
import re
import shutil
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = 0x08000000
HOME = Path(os.path.expanduser("~"))

# --------------------------------------------------------------- where Jarvis may and may not work
_PROTECTED = [Path(os.environ.get("SystemRoot", r"C:\Windows")), Path(os.environ.get("ProgramFiles", r"C:\Program Files")),
              Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")), Path(os.environ.get("ProgramData", r"C:\ProgramData")),
              HOME / "AppData", Path(os.environ.get("LOCALAPPDATA", str(HOME / "AppData" / "Local"))) / "JarvisAssistant"]
_NAMED = {"desktop": "Desktop", "documents": "Documents", "my documents": "Documents", "downloads": "Downloads",
          "pictures": "Pictures", "photos": "Pictures", "music": "Music", "videos": "Videos", "home": ""}


def _known_folder(name):
    try:  # Documents/Desktop may be redirected (OneDrive); ask Windows where they really are
        from win32com.shell import shell, shellcon
        csidl = {"Desktop": shellcon.CSIDL_DESKTOPDIRECTORY, "Documents": shellcon.CSIDL_PERSONAL,
                 "Pictures": shellcon.CSIDL_MYPICTURES, "Music": shellcon.CSIDL_MYMUSIC, "Videos": shellcon.CSIDL_MYVIDEO}.get(name)
        if csidl is not None:
            return Path(shell.SHGetFolderPath(0, csidl, None, 0))
    except Exception:
        pass
    return HOME / name


def resolve(path):
    """A real path from what was said: an absolute path, '~/...', or 'Documents/School', 'my desktop'."""
    p = str(path).strip().strip('"').replace("/", "\\")
    low = p.lower().removeprefix("my ")
    for key, folder in sorted(_NAMED.items(), key=lambda kv: -len(kv[0])):
        if low == key or low.startswith(key + "\\"):
            base = _known_folder(folder) if folder else HOME
            rest = p[len(p) - len(low) + len(key):].lstrip("\\")
            return (base / rest) if rest else base
    if p.startswith("~"):
        return HOME / p[1:].lstrip("\\")
    path = Path(p)
    # The AI sometimes guesses a user name (C:\Users\Someone\Desktop\x): if that folder doesn't exist on this PC,
    # read the rest of the path from your own folders instead.
    parts = path.parts
    if path.is_absolute() and len(parts) > 3 and parts[1].lower() == "users" and not Path(*parts[:3]).exists():
        return resolve("\\".join(parts[3:]))
    return path if path.is_absolute() else _known_folder("Documents") / path


def check_allowed(path):
    """Raises if the path is somewhere Jarvis must never change."""
    real = Path(os.path.abspath(path))
    if len(real.parts) <= 2:  # a whole drive, or C:\Users
        raise RuntimeError(f"I won't change {real} itself: that's a whole drive or the users folder.")
    for prot in _PROTECTED:
        try:
            real.relative_to(prot)
            raise RuntimeError(f"{real} is in a protected system folder ({prot}); I don't change things there.")
        except ValueError:
            continue
    users = Path(os.environ.get("SystemDrive", "C:") + "\\Users")
    try:
        rel = real.relative_to(users)
        if rel.parts and rel.parts[0].lower() != HOME.name.lower():
            raise RuntimeError("That's in another person's user folder; I only work in yours.")
    except ValueError:
        pass
    return real


# --------------------------------------------------------------- files and folders
def create_folder(path):
    p = check_allowed(resolve(path))
    p.mkdir(parents=True, exist_ok=True)
    return f"Made the folder {p}."


def _dest(src, dest):
    d = check_allowed(resolve(dest))
    return d / src.name if d.is_dir() else d


def move(src, dest):
    s = check_allowed(resolve(src))
    if not s.exists():
        raise RuntimeError(f"{s} doesn't exist.")
    d = _dest(s, dest)
    if d.exists():
        raise RuntimeError(f"{d} already exists; I won't overwrite it.")
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return f"Moved {s.name} to {d.parent}."


def copy(src, dest):
    s = check_allowed(resolve(src))
    if not s.exists():
        raise RuntimeError(f"{s} doesn't exist.")
    d = _dest(s, dest)
    if d.exists():
        raise RuntimeError(f"{d} already exists; I won't overwrite it.")
    d.parent.mkdir(parents=True, exist_ok=True)
    (shutil.copytree if s.is_dir() else shutil.copy2)(str(s), str(d))
    return f"Copied {s.name} to {d.parent}."


def rename(path, new_name):
    s = check_allowed(resolve(path))
    if not s.exists():
        raise RuntimeError(f"{s} doesn't exist.")
    if re.search(r'[\\/:*?"<>|]', new_name):
        raise RuntimeError("A file name can't contain \\ / : * ? \" < > |")
    d = s.with_name(new_name)
    if d.exists():
        raise RuntimeError(f"{d.name} already exists there.")
    s.rename(d)
    return f"Renamed {s.name} to {d.name}."


def recycle(path):
    """Moves a file or folder to the Recycle Bin (never a permanent delete). Callers ask the user first."""
    s = check_allowed(resolve(path))
    if not s.exists():
        raise RuntimeError(f"{s} doesn't exist.")
    from win32com.shell import shell, shellcon
    flags = shellcon.FOF_ALLOWUNDO | shellcon.FOF_NOCONFIRMATION | shellcon.FOF_SILENT | shellcon.FOF_NOERRORUI
    code, aborted = shell.SHFileOperation((0, shellcon.FO_DELETE, str(s), None, flags))
    if code or aborted or s.exists():
        raise RuntimeError(f"Windows didn't move {s.name} to the Recycle Bin (code {code}).")
    return f"Moved {s.name} to the Recycle Bin. You can restore it from there."


def list_folder(path, limit=40):
    p = resolve(path)
    if not p.is_dir():
        raise RuntimeError(f"{p} isn't a folder.")
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    return {"folder": str(p), "items": [(x.name + ("\\" if x.is_dir() else "")) for x in items[:limit]],
            "more": max(0, len(items) - limit)}


# --------------------------------------------------------------- Windows commands
# Commands that only look at things run straight away. Everything else is "major": the user approves it first.
SAFE_COMMANDS = re.compile(
    r"^\s*(?:get-(?:childitem|content|date|process|service|computerinfo|netipaddress|netadapter|volume|psdrive|location|"
    r"item|itemproperty|hotfix|wmiobject|ciminstance|printer|clipboard|command|help|uptime|filehash|acl|eventlog|winevent)\b"
    r"|(?:dir|ls|type|cat|where|whoami|hostname|ipconfig|systeminfo|tasklist|ping|tracert|nslookup|getmac|ver|tree|"
    r"echo|test-path|test-connection|resolve-path|measure-object|select-string|findstr|driverquery|wmic\s+\w+\s+get)\b)", re.I)
DANGEROUS = re.compile(r"(remove-item|\brm\b|\bdel\b|\berase\b|rmdir|\brd\b|format|diskpart|reg\s+(add|delete)|set-itemproperty|"
                       r"new-itemproperty|remove-itemproperty|stop-process|taskkill|stop-service|set-service|bcdedit|"
                       r"cipher\s+/w|vssadmin|wevtutil\s+cl|net\s+user|shutdown|restart-computer|invoke-expression|\biex\b|"
                       r"downloadstring|invoke-webrequest|start-bitstransfer|set-executionpolicy|uninstall|install|winget|choco)", re.I)
_CHAIN = re.compile(r"[;&`]|\$\(|>|<|\|\|")
# Steps after a pipe that only filter, sort or format what the first command found.
PIPE_SAFE = re.compile(r"^\s*(?:where-object|where|\?|select-object|select|sort-object|sort|format-table|ft|format-list|fl|"
                       r"measure-object|measure|out-string|convertto-json|convertto-csv|group-object|select-string|findstr|"
                       r"first|last)\b", re.I)
_METHOD = re.compile(r"\.\s*\w+\s*\(")  # .Delete(), .Kill(): calling methods can change things


def is_safe(command):
    """True for a command that only reads or looks at things: a known-harmless command, optionally piped into
    filtering, sorting or formatting steps. No chaining, redirection, method calls or anything that changes things."""
    c = command.strip()
    if not c or DANGEROUS.search(c) or _CHAIN.search(c) or _METHOD.search(c):
        return False
    first, *rest = c.split("|")
    return bool(SAFE_COMMANDS.match(first)) and all(PIPE_SAFE.match(step) for step in rest)


def run(command, timeout=60):
    """Runs a PowerShell command and returns its output. Callers decide whether it needs approval first."""
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    return {"exit_code": r.returncode, "output": out[-4000:], "errors": err[-1500:]}
