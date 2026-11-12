"""SQLite storage for conversation history, long-term memory and the activity log."""
import logging
import re
import sqlite3
import threading
import time

from .config import HOME

DB_FILE = HOME / "jarvis.db"

# Anything that looks like a credential is masked before it reaches disk.
_SECRET_PATTERNS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)((?:api[_-]?key|token|password|secret|xi-api-key)[\"'=:\s]+)[^\s\"',]+"),
    re.compile(r"AIza[0-9A-Za-z\-_]{30,}"),
    re.compile(r"sk_[0-9a-f]{20,}"),
    re.compile(r"[MN][A-Za-z\d]{23,25}\.[\w-]{6}\.[\w-]{27,}"),  # Discord token shape
]


def redact(text: str) -> str:
    if not text:
        return text
    for p in _SECRET_PATTERNS:
        text = p.sub(lambda m: (m.group(1) if m.groups() else "") + "[REDACTED]", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record):
        record.msg = redact(str(record.msg))
        if record.args:
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        return True


def setup_logging():
    handler = logging.FileHandler(HOME / "jarvis.log", encoding="utf-8")
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    for noisy in ("httpx", "httpx2", "httpcore", "huggingface_hub","urllib3", "faster_whisper", "msal", "pywebview"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


class Store:
    def __init__(self, path=DB_FILE):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, ts REAL, role TEXT, text TEXT);
            CREATE TABLE IF NOT EXISTS memories(id INTEGER PRIMARY KEY, ts REAL, text TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, text TEXT);
            CREATE TABLE IF NOT EXISTS devices(id INTEGER PRIMARY KEY, name TEXT, token_hash TEXT UNIQUE,
                                               created REAL, last_seen REAL);
            CREATE TABLE IF NOT EXISTS items(id INTEGER PRIMARY KEY, source TEXT, ext_id TEXT, ts REAL, sender TEXT,
                title TEXT, school INTEGER, category TEXT, importance INTEGER, summary TEXT, needs_reply INTEGER,
                deadline TEXT, reply TEXT, url TEXT, UNIQUE(source, ext_id));
            CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, task_id INTEGER, kind TEXT, title TEXT, state TEXT,
                step TEXT, data TEXT, result_path TEXT, error TEXT, created REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS tasks(id INTEGER PRIMARY KEY, title TEXT, details TEXT, kind TEXT, due TEXT,
                importance INTEGER, status TEXT, source TEXT, source_ref TEXT, created REAL, updated REAL,
                result_path TEXT, reminded TEXT DEFAULT '');
            """
        )
        self._db.commit()

    # ---- what the agent has seen (so nothing is processed twice)
    def seen(self, source, ext_id):
        return bool(self._query("SELECT 1 FROM items WHERE source=? AND ext_id=?", (source, str(ext_id))))

    def add_item(self, it):
        cur = self._exec("INSERT OR IGNORE INTO items(source, ext_id, ts, sender, title, school, url) VALUES(?,?,?,?,?,?,?)",
                         (it["source"], str(it["ext_id"]), time.time(), redact(it.get("sender", ""))[:200],
                          redact(it.get("title", ""))[:300], int(bool(it.get("school"))), it.get("url", "")))
        return cur.lastrowid

    def update_item(self, item_id, **f):
        cols = [k for k in f if k in ("category", "importance", "summary", "needs_reply", "deadline", "reply")]
        if cols:
            self._exec(f"UPDATE items SET {', '.join(c + '=?' for c in cols)} WHERE id=?",
                       [redact(f[c]) if isinstance(f[c], str) else f[c] for c in cols] + [item_id])

    def items_since(self, ts):
        rows = self._query("SELECT id, source, ts, sender, title, school, category, importance, summary, needs_reply, "
                           "deadline, reply, url FROM items WHERE ts>=? ORDER BY ts DESC", (ts,))
        keys = ("id", "source", "ts", "sender", "title", "school", "category", "importance", "summary", "needs_reply",
                "deadline", "reply", "url")
        return [dict(zip(keys, r)) for r in rows]

    # ---- prepared-work jobs (each step's output is saved, so a restart resumes where it stopped)
    _JOB_COLS = ("id", "task_id", "kind", "title", "state", "step", "data", "result_path", "error", "created", "updated")

    def add_job(self, kind, title, data, task_id=None):
        import json
        now = time.time()
        return self._exec("INSERT INTO jobs(task_id, kind, title, state, step, data, created, updated) VALUES(?,?,?,?,?,?,?,?)",
                          (task_id, kind, title[:200], "queued", "", json.dumps(data), now, now)).lastrowid

    def jobs(self, states=None, limit=30):
        import json
        sql = f"SELECT {', '.join(self._JOB_COLS)} FROM jobs"
        args = ()
        if states:
            sql += f" WHERE state IN ({','.join('?' * len(states))})"
            args = tuple(states)
        rows = self._query(sql + " ORDER BY id DESC LIMIT ?", args + (limit,))
        out = []
        for r in rows:
            j = dict(zip(self._JOB_COLS, r))
            j["data"] = json.loads(j["data"] or "{}")
            out.append(j)
        return out

    def job(self, job_id):
        found = [j for j in self.jobs(limit=500) if j["id"] == int(job_id)]
        return found[0] if found else None

    def update_job(self, job_id, **f):
        import json
        if "data" in f:
            f["data"] = json.dumps(f["data"])
        cols = [k for k in f if k in ("state", "step", "data", "result_path", "error")]
        self._exec(f"UPDATE jobs SET {', '.join(c + '=?' for c in cols)}, updated=? WHERE id=?",
                   [f[c] for c in cols] + [time.time(), int(job_id)])

    # ---- the task list
    _TASK_COLS = ("id", "title", "details", "kind", "due", "importance", "status", "source", "source_ref", "created",
                  "updated", "result_path", "reminded")

    def add_task(self, title, details="", kind="other", due=None, importance=3, source="you", source_ref=""):
        if source_ref and self._query("SELECT 1 FROM tasks WHERE source_ref=?", (source_ref,)):
            return None  # already on the list
        now = time.time()
        cur = self._exec("INSERT INTO tasks(title, details, kind, due, importance, status, source, source_ref, created, updated) "
                         "VALUES(?,?,?,?,?,?,?,?,?,?)", (redact(title)[:200], redact(details or "")[:2000], kind, due,
                                                         int(importance), "open", source, source_ref, now, now))
        return cur.lastrowid

    def tasks(self, status=("open",)):
        marks = ",".join("?" * len(status))
        rows = self._query(f"SELECT {', '.join(self._TASK_COLS)} FROM tasks WHERE status IN ({marks})", tuple(status))
        return [dict(zip(self._TASK_COLS, r)) for r in rows]

    def task(self, task_id):
        rows = self._query(f"SELECT {', '.join(self._TASK_COLS)} FROM tasks WHERE id=?", (int(task_id),))
        return dict(zip(self._TASK_COLS, rows[0])) if rows else None

    def update_task(self, task_id, **f):
        cols = [k for k in f if k in ("title", "details", "kind", "due", "importance", "status", "result_path", "reminded")]
        if cols:
            self._exec(f"UPDATE tasks SET {', '.join(c + '=?' for c in cols)}, updated=? WHERE id=?",
                       [f[c] for c in cols] + [time.time(), int(task_id)])

    # paired phones: only a hash of each device's token is stored
    @staticmethod
    def _hash(token):
        import hashlib
        return hashlib.sha256(token.encode()).hexdigest()

    def add_device(self, name, token):
        now = time.time()
        cur = self._exec("INSERT INTO devices(name, token_hash, created, last_seen) VALUES(?,?,?,?)",
                         (name[:60], self._hash(token), now, now))
        return cur.lastrowid

    def device_for(self, token):
        """The paired device with this token (and marks it as seen), or None."""
        if not token:
            return None
        rows = self._query("SELECT id, name FROM devices WHERE token_hash=?", (self._hash(token),))
        if not rows:
            return None
        self._exec("UPDATE devices SET last_seen=? WHERE id=?", (time.time(), rows[0][0]))
        return {"id": rows[0][0], "name": rows[0][1]}

    def devices(self):
        return [{"id": r[0], "name": r[1], "created": r[2], "last_seen": r[3]}
                for r in self._query("SELECT id, name, created, last_seen FROM devices ORDER BY id")]

    def remove_device(self, dev_id):
        self._exec("DELETE FROM devices WHERE id=?", (int(dev_id),))

    def _exec(self, sql, args=()):
        with self._lock:
            cur = self._db.execute(sql, args)
            self._db.commit()
            return cur

    def _query(self, sql, args=()):
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    # conversation
    def add_message(self, role, text):
        self._exec("INSERT INTO messages(ts, role, text) VALUES(?,?,?)", (time.time(), role, redact(text)))

    def recent_messages(self, n):
        rows = self._query("SELECT ts, role, text FROM messages ORDER BY id DESC LIMIT ?", (n,))
        return [{"ts": r[0], "role": r[1], "text": r[2]} for r in reversed(rows)]

    def clear_messages(self):
        self._exec("DELETE FROM messages")

    # memory
    def remember(self, text):
        self._exec("INSERT OR IGNORE INTO memories(ts, text) VALUES(?,?)", (time.time(), redact(text.strip())))

    def memories(self):
        return [{"id": r[0], "text": r[1]} for r in self._query("SELECT id, text FROM memories ORDER BY id")]

    def forget(self, mem_id):
        self._exec("DELETE FROM memories WHERE id=?", (mem_id,))

    # activity log
    def log(self, kind, text):
        self._exec("INSERT INTO activity(ts, kind, text) VALUES(?,?,?)", (time.time(), kind, redact(text)))
        self._exec("DELETE FROM activity WHERE id < (SELECT MAX(id) - 2000 FROM activity)")

    def activity(self, n=100):
        rows = self._query("SELECT ts, kind, text FROM activity ORDER BY id DESC LIMIT ?", (n,))
        return [{"ts": r[0], "kind": r[1], "text": r[2]} for r in rows]
