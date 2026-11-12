"""File search through the Windows Search index: matches file names and what's inside documents, offline.

"Find my notes about the Tokyo trip" -> searches your user folder for files mentioning "tokyo" and "trip",
opens the best match (programs and scripts are only shown in Explorer, never run) and lists the rest."""
import os
import re
import subprocess

import pythoncom
import win32com.client

HOME = os.path.expanduser("~")
# Opening these would run code, so Jarvis only shows them in Explorer.
RUNNABLE = {".exe", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".msi", ".msc", ".scr",
            ".lnk", ".url", ".reg", ".py", ".pyw", ".jar", ".hta", ".cpl", ".appref-ms"}
_STOP = set("""a an the my me mine our your some any of about on for with from in into to and or that this these those
file files document documents doc docs notes note called named titled where is are was it i find search look locate open show
please can you could jarvis everything something stuff thing things which has have containing contains mentions mentioning
one ones latest recent recently last""".split())
_KINDS = {"pdf": "pdf", "pdfs": "pdf", "photo": "picture", "photos": "picture", "picture": "picture", "pictures": "picture",
          "image": "picture", "images": "picture", "video": "video", "videos": "video", "spreadsheet": "document",
          "presentation": "document", "slides": "document", "song": "music", "songs": "music", "music": "music"}

_REQ = re.compile(r"^(?:find|search|look for|locate|where(?:'s| is| are))\s+(?:for\s+)?(?:in\s+)?(?:my\s+)?(?:files?\s+(?:for|about)\s+)?(.+?)\??$")


def parse(text):
    """Search words for a file request, or None. Text is lowercase."""
    t = text.strip().rstrip(".!")
    if re.match(r"^(?:search|look)\s+(?:the\s+)?(?:web|internet|online|google|youtube|for .+ on (?:youtube|google|the web))", t):
        return None
    if not (m := _REQ.match(t)):
        return None
    words = m[1]
    # Only file-ish requests: "my ...", or mentions files, documents, notes, a file type, or a file name with an extension.
    if not re.search(r"\b(my|file|files|document|documents|doc|docs|notes?|pdfs?|photos?|pictures?|images?|videos?|spreadsheet|presentation|slides|folder)\b|\.\w{2,4}\b", t):
        return None
    return words


def _keywords(words):
    kws = [w for w in re.findall(r"[\w.'-]+", words.lower()) if w not in _STOP and w not in _KINDS and len(w) > 1]
    kind = next((_KINDS[w] for w in re.findall(r"\w+", words.lower()) if w in _KINDS), None)
    if "pdf" in words.lower():
        kind = "pdf"
    return kws[:6], kind


JUNK = re.compile(r"\\(?:AppData|\.git|\.gradle|\.cache|\.vscode|node_modules|__pycache__|build|dist|bin|obj|venv|\.venv|site-packages|\.android)\\", re.I)


def _score(path, rank, kws):
    name, low = os.path.basename(path).lower(), path.lower()
    s = sum(3 for k in kws if k in name) + sum(1 for k in kws if k in low) - rank * 0.05
    return s + (1 if re.search(r"\\(desktop|documents|downloads|pictures|onedrive)\\", low) else 0)


def search(words, limit=8):
    """[{'path', 'name', 'modified'}] best first, from the user's own folders."""
    kws, kind = _keywords(words)
    if not kws and not kind:
        return []
    safe = [k.replace("'", "''").replace('"', "") for k in kws]
    conds = [f"SCOPE='file:{HOME.replace(os.sep, '/')}'"]
    if safe:
        # Any word may match (in the name or inside the file); results are ranked by how many do.
        terms = " OR ".join(f'"{k}*"' for k in safe)
        names = " OR ".join(f"System.FileName LIKE '%{k}%'" for k in safe)
        conds.append(f"(CONTAINS(*, '{terms}') OR {names})")
    if kind == "pdf":
        conds.append("System.FileExtension = '.pdf'")
    elif kind:
        conds.append(f"System.Kind = '{kind}'")
    sql = (f"SELECT TOP 200 System.ItemPathDisplay, System.ItemNameDisplay, System.DateModified FROM SYSTEMINDEX "
           f"WHERE {' AND '.join(conds)} ORDER BY System.Search.Rank DESC, System.DateModified DESC")
    pythoncom.CoInitialize()
    try:
        conn = win32com.client.Dispatch("ADODB.Connection")
        conn.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
        rs, _ = conn.Execute(sql)
        out = []
        while not rs.EOF:
            path = rs.Fields.Item(0).Value
            if path and not JUNK.search(path) and os.path.isfile(path):
                out.append({"path": path, "name": rs.Fields.Item(1).Value or os.path.basename(path),
                            "modified": str(rs.Fields.Item(2).Value or "")[:10], "rank": len(out)})
            rs.MoveNext()
        conn.Close()
    finally:
        pythoncom.CoUninitialize()
    out.sort(key=lambda h: -_score(h["path"], h["rank"], kws))
    return out[:limit]


def open_file(path):
    """Opens a document; anything that could run code is only shown in Explorer."""
    if os.path.splitext(path)[1].lower() in RUNNABLE:
        subprocess.Popen(["explorer.exe", "/select,", path])
        return "shown in File Explorer"
    os.startfile(path)
    return "opened"


def find(words):
    try:
        hits = search(words)
    except Exception as e:
        return f"Windows Search isn't answering ({str(e)[:80]}). Check the Windows Search service is running."
    if not hits:
        return f"I couldn't find any files matching {words}."
    how = open_file(hits[0]["path"])
    folder = os.path.basename(os.path.dirname(hits[0]["path"]))
    reply = f"Found {hits[0]['name']} in your {folder} folder, {how}."
    if len(hits) > 1:
        reply += " Also found " + " and ".join(h["name"] for h in hits[1:3]) + "."
    return reply
