"""Builder: Jarvis improves himself through Claude Code (Anthropic's official command-line tool).

How it works:
1. You ask ("tell Claude Code to make the UI cooler"). An approval card shows exactly what will be sent.
2. On approval, Builder makes a separate copy of the code on its own Git branch (a "worktree" next to the project),
   so the Jarvis you're using is untouched while it works.
3. Claude Code works in that copy. It may only read and edit files there: no commands, no web.
4. Builder runs the test suite on the result and tells you what changed and whether the tests pass.
5. Applying the change is another approval card. Afterwards Jarvis restarts with the new code, and
   "undo Builder's last change" puts it back (a new Git commit that reverses it; history is never deleted).

Builder only runs when Claude Code is signed in with your own personal account (see builder_status())."""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..config import settings

log = logging.getLogger("builder")
ROOT = Path(__file__).resolve().parent.parent.parent
CREATE_NO_WINDOW = 0x08000000
PERSONAL_DOMAINS = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "msn.com", "icloud.com",
                    "me.com", "yahoo.com", "proton.me", "protonmail.com", "aol.com", "gmx.com", "zoho.com"}
GUIDE = ("You are improving Jarvis, a Python/JavaScript personal assistant (this folder is a working copy on its own "
         "branch). Make the change below carefully, in the existing style. Keep every existing feature working and "
         "keep the tests in tests/ passing; add or update tests when you change behaviour. Don't add network services, "
         "telemetry, new accounts or secrets, and don't weaken the safety rules (approval cards, permissions, private "
         "mode). When you finish, reply with a short summary of what you changed.\n\nThe request:\n")


def cli():
    exe = shutil.which("claude")
    if exe:
        return exe
    for p in (Path.home() / ".local" / "bin" / "claude.exe", Path(os.environ.get("APPDATA", "")) / "npm" / "claude.cmd"):
        if p.exists():
            return str(p)
    return None


def account():
    """{'signed_in', 'personal'}: personal is True for a personal email service, False for a company or school
    domain, None when unknown. The address itself is never returned or logged."""
    try:
        data = json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))
        email = ((data.get("oauthAccount") or {}).get("emailAddress") or "").lower()
    except (OSError, ValueError):
        email = ""
    if not email:
        return {"signed_in": False, "personal": None}
    return {"signed_in": True, "personal": email.split("@")[-1] in PERSONAL_DOMAINS}


def status():
    a = account()
    return {"installed": bool(cli()), **a, "enabled": bool(settings.get("builder_enabled")),
            "confirmed": bool(settings.get("builder_account_confirmed")), "project": str(ROOT)}


def check_allowed():
    s = status()
    if not s["installed"]:
        raise RuntimeError("Claude Code isn't installed on this laptop, so Builder can't work.")
    if not s["enabled"]:
        raise RuntimeError("Builder is switched off. Turn it on in Settings, Builder, after checking which account Claude Code uses.")
    if not s["signed_in"]:
        raise RuntimeError("Claude Code isn't signed in. Open a terminal, run claude, and sign in with your personal account.")
    if s["personal"] is False and not s["confirmed"]:
        raise RuntimeError("Claude Code is signed in with a company or school account, not a personal one, so Builder won't use "
                           "it. Sign in with your own account (run claude, then /login), or confirm in Settings that it's yours.")


def _git(*args, cwd=None, timeout=120):
    r = subprocess.run(["git", *args], cwd=str(cwd or ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=CREATE_NO_WINDOW)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout.strip()


def _python():
    exe = Path(sys.executable)
    w = exe.with_name("python.exe")
    return str(w if w.exists() else exe)


class Builder:
    def __init__(self, store, notify, ask_apply):
        """notify(text, important); ask_apply(job) shows the "apply this change?" approval card."""
        self.store, self.notify, self.ask_apply = store, notify, ask_apply
        self.busy = False

    # ---------------- 1. start: a separate copy, Claude Code, tests
    def start(self, request):
        check_allowed()
        if self.busy:
            return "Builder is already working on something. I'll tell you when it's done."
        if _git("status", "--porcelain"):
            return "The Jarvis folder has changes that aren't saved in Git yet, so Builder won't start. Commit them first."
        stamp = time.strftime("%Y%m%d-%H%M%S")
        branch, tree = f"builder/{stamp}", ROOT.parent / f"{ROOT.name}-builder" / stamp
        job_id = self.store.add_job("builder", request[:200], {"request": request, "branch": branch, "tree": str(tree)})
        self.busy = True
        threading.Thread(target=self._run, args=(job_id,), daemon=True, name="builder").start()
        self.store.log("agent", f"Builder started: {request[:150]}", "builder")
        return "Builder has started. Claude Code is working on a separate copy, so nothing changes until you approve it."

    def _run(self, job_id):
        job = self.store.job(job_id)
        d = job["data"]
        tree = Path(d["tree"])
        try:
            self.store.update_job(job_id, state="running", step="copy")
            tree.parent.mkdir(parents=True, exist_ok=True)
            _git("worktree", "add", "-b", d["branch"], str(tree), "HEAD")
            self.store.update_job(job_id, step="claude code")
            r = subprocess.run([cli(), "-p", GUIDE + d["request"], "--output-format", "text", "--permission-mode", "acceptEdits",
                                "--allowedTools", "Read,Edit,Write,Glob,Grep"], cwd=str(tree), capture_output=True, text=True,
                               encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW,
                               timeout=int(settings.get("builder_timeout_min") or 30) * 60)
            summary = (r.stdout or "").strip()[-1500:] or (r.stderr or "").strip()[-500:]
            if r.returncode != 0:
                raise RuntimeError(f"Claude Code stopped with an error: {summary[:300]}")
            _git("add", "-A", cwd=tree)
            if not _git("status", "--porcelain", cwd=tree):
                self._cleanup(d)
                self.store.update_job(job_id, state="done", step="no changes", error="")
                self.notify(f"Builder: Claude Code finished but didn't change anything. It said: {summary[:200]}")
                return
            _git("-c", "user.name=Jarvis Builder", "-c", "user.email=builder@jarvis.local", "commit", "-q", "-m",
                 f"Builder: {d['request'][:60]}", "-m", summary[:800], cwd=tree)
            stat = _git("diff", "--shortstat", "HEAD~1", "HEAD", cwd=tree)
            self.store.update_job(job_id, step="tests")
            t = subprocess.run([_python(), "-W", "ignore", "-m", "unittest", "discover", "-s", "tests"], cwd=str(tree),
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                               creationflags=CREATE_NO_WINDOW)
            tail = (t.stderr or t.stdout or "").strip().splitlines()
            passed = t.returncode == 0
            self.store.update_job(job_id, state="ready", step="waiting for you",
                                  data={**d, "summary": summary, "stat": stat, "tests_passed": passed,
                                        "tests": " ".join(tail[-2:]) if tail else ""})
            self.store.log("agent", f"Builder finished: {stat}; tests {'passed' if passed else 'FAILED'}", "builder")
            self.ask_apply(self.store.job(job_id))
            self.notify(f"Builder finished: {stat}. Tests {'pass' if passed else 'fail, so I suggest discarding it'}. "
                        "Check the card to apply or discard it.", important=True)
        except Exception as e:
            log.exception("builder job %s", job_id)
            self.store.update_job(job_id, state="failed", error=str(e)[:400])
            self.store.log("agent", f"Builder failed: {str(e)[:200]}", "builder")
            self._cleanup(d)
            self.notify(f"Builder couldn't finish: {str(e)[:160]}")
        finally:
            self.busy = False

    # ---------------- 2. apply, discard, undo
    def apply(self, job_id):
        job = self.store.job(int(job_id))
        if not job or job["kind"] != "builder" or job["state"] != "ready":
            return "That Builder change isn't waiting to be applied any more."
        if _git("status", "--porcelain"):
            return "The Jarvis folder has unsaved changes, so I won't merge over them. Commit them first."
        d = job["data"]
        before = _git("rev-parse", "HEAD")
        _git("merge", "--no-ff", "-q", d["branch"], "-m", f"Apply Builder change: {d['request'][:60]}")
        merged = _git("rev-parse", "HEAD")
        self._cleanup(d)
        self.store.update_job(job["id"], state="applied", step="applied", data={**d, "before": before, "merge": merged})
        self.store.log("agent", f"Builder change applied ({merged[:7]}); undo goes back to {before[:7]}", "builder")
        restart_soon()
        return "Applied. Jarvis is restarting with the new code. Say 'undo Builder's last change' if you don't like it."

    def discard(self, job_id):
        job = self.store.job(int(job_id))
        if not job or job["kind"] != "builder":
            return "There's no such Builder change."
        self._cleanup(job["data"])
        self.store.update_job(job["id"], state="discarded", step="discarded")
        self.store.log("agent", "Builder change discarded", "builder")
        return "Discarded. Nothing in Jarvis changed."

    def undo_last(self):
        applied = [j for j in self.store.jobs(states=("applied",), limit=50) if j["kind"] == "builder" and j["data"].get("merge")]
        if not applied:
            return "There's no applied Builder change to undo."
        j = applied[0]
        if _git("status", "--porcelain"):
            return "The Jarvis folder has unsaved changes, so I won't undo over them. Commit them first."
        _git("revert", "--no-edit", "-m", "1", j["data"]["merge"])
        self.store.update_job(j["id"], state="undone", step="undone")
        self.store.log("agent", f"Builder change undone ({j['data']['merge'][:7]} reverted)", "builder")
        restart_soon()
        return "Undone. Jarvis is restarting with the previous code."

    def _cleanup(self, d):
        try:
            if Path(d["tree"]).exists():
                _git("worktree", "remove", "--force", d["tree"])
        except Exception as e:
            log.warning("worktree cleanup: %s", e)
        try:
            if d.get("branch") and _git("branch", "--list", d["branch"]):
                _git("branch", "-D", d["branch"])
        except Exception as e:
            log.warning("branch cleanup: %s", e)

    def jobs(self):
        return [{"id": j["id"], "title": j["title"], "state": j["state"], "step": j["step"], "error": j["error"],
                 "stat": j["data"].get("stat", ""), "tests_passed": j["data"].get("tests_passed"),
                 "summary": (j["data"].get("summary") or "")[:400]}
                for j in self.store.jobs(limit=40) if j["kind"] == "builder"][:10]


def restart_soon():
    """Restarts Jarvis's background core a few seconds from now, so the reply can be spoken first."""
    pyw = Path(sys.executable).with_name("pythonw.exe")
    cmd = f'ping -n 6 127.0.0.1 >nul & start "" "{pyw if pyw.exists() else sys.executable}" -W ignore -m jarvis --service'
    subprocess.Popen(["cmd", "/c", cmd], cwd=str(ROOT), creationflags=CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    threading.Timer(3.0, lambda: os._exit(0)).start()
