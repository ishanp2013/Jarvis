"""Installed Steam and Epic Games titles, launched through each launcher's own official link
(steam://rungameid/..., com.epicgames.launcher://apps/...). Nothing is logged in or modified."""
import glob
import json
import os
import re
import time
import winreg

_cache = {"at": 0, "games": []}
SKIP = re.compile(r"redistributable|steamworks|proton|steam linux runtime|soundtrack|dedicated server|\bsdk\b", re.I)


def _steam_root():
    for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
        try:
            with winreg.OpenKey(hive, key) as k:
                for name in ("SteamPath", "InstallPath"):
                    try:
                        return winreg.QueryValueEx(k, name)[0]
                    except OSError:
                        pass
        except OSError:
            pass
    return None


def _steam():
    root = _steam_root()
    if not root:
        return []
    libs = {os.path.normpath(root)}
    try:
        vdf = open(os.path.join(root, "steamapps", "libraryfolders.vdf"), encoding="utf-8", errors="ignore").read()
        libs |= {os.path.normpath(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf)}
    except OSError:
        pass
    out = []
    for lib in libs:
        for acf in glob.glob(os.path.join(lib, "steamapps", "appmanifest_*.acf")):
            try:
                txt = open(acf, encoding="utf-8", errors="ignore").read()
                appid, name = re.search(r'"appid"\s+"(\d+)"', txt).group(1), re.search(r'"name"\s+"([^"]+)"', txt).group(1)
                folder = re.search(r'"installdir"\s+"([^"]+)"', txt)
            except (OSError, AttributeError):
                continue
            if not SKIP.search(name):
                out.append({"name": name, "store": "Steam", "launch": f"steam://rungameid/{appid}",
                            "folder": os.path.join(lib, "steamapps", "common", folder.group(1)) if folder else ""})
    return out


def _epic():
    out = []
    base = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Epic", "EpicGamesLauncher", "Data", "Manifests")
    for item in glob.glob(os.path.join(base, "*.item")):
        try:
            m = json.load(open(item, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not m.get("bIsApplication", True) or m.get("bIsIncompleteInstall"):
            continue
        link = f"com.epicgames.launcher://apps/{m['CatalogNamespace']}%3A{m['CatalogItemId']}%3A{m['AppName']}?action=launch&silent=true"
        out.append({"name": m.get("DisplayName", m["AppName"]), "store": "Epic", "launch": link,
                    "folder": m.get("InstallLocation", "")})
    return out


def installed(refresh=False):
    if refresh or time.time() - _cache["at"] > 300:
        _cache.update(at=time.time(), games=sorted(_steam() + _epic(), key=lambda g: g["name"].lower()))
    return _cache["games"]


def game_folders():
    return [g["folder"].lower() for g in installed() if g["folder"]]


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace(":", " ").replace("-", " ")).split()


def find(query):
    """Only confident matches: the exact title, or every word of the request in one game's title."""
    q = _norm(re.sub(r"^(?:the game |game )", "", query.strip().lower()))
    if not q:
        return None
    games = installed()
    for g in games:
        if _norm(g["name"]) == q:
            return g
    hits = [g for g in games if set(q) <= set(_norm(g["name"]))]
    if len(hits) == 1:
        return hits[0]
    # initials: "gta" -> Grand Theft Auto, "cs" -> Counter-Strike
    if len(q) == 1 and len(q[0]) >= 2:
        hits = [g for g in games if "".join(w[0] for w in _norm(g["name"]) if not w.isdigit()).startswith(q[0])]
        if len(hits) == 1:
            return hits[0]
    return None


def launch(query):
    g = find(query)
    if not g:
        return None
    os.startfile(g["launch"])
    return f"Launching {re.sub(r'[®™©]', '', g['name'])} through {g['store']}."
