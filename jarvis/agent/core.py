"""The background agent loop.

Every `agent_interval_min` minutes (and on "check now"):
1. collect new items from Classroom, Gmail, Outlook, phone notifications and Discord
2. keep non-school items as counts only; send school items to the AI in batches (agent/triage.py)
3. add assignments and tests to the task list, with deadlines and priorities
4. turn emails that need a reply into reply drafts, shown as approval cards (never sent on their own)
5. tell you about anything important (dashboard, phone, and a spoken line if you're at the laptop)

Every minute it also checks reminders: the day before a deadline and the morning of it.
It pauses in game mode and on a low battery, and stops at its share of the daily AI budget."""
import datetime as dt
import logging
import threading
import time

from .. import ai
from ..config import settings
from ..tools import google, microsoft
from . import dates, sources, triage

log = logging.getLogger("agent")
BATCH = 10


class Agent:
    def __init__(self, store, notify, request_reply=None, paused=None, on_task=None):
        """notify(text, important=False); request_reply(item, text) shows a reply draft card;
        paused() -> reason string to skip a scheduled run (game mode, low battery), or None;
        on_task(task) is called for each new task (the worker prepares a draft of it)."""
        self.store, self.notify = store, notify
        self.request_reply = request_reply or (lambda item, text: None)
        self.on_task = on_task or (lambda task: None)
        self.paused = paused or (lambda: None)
        self.lock = threading.Lock()
        self.running = False
        self.last = {"when": settings.get("agent_last_run") or 0, "summary": "Not run yet.", "problems": []}

    # ---------------- scheduling
    def start(self):
        threading.Thread(target=self._loop, daemon=True, name="agent").start()

    def next_run(self):
        return (settings.get("agent_last_run") or 0) + int(settings.get("agent_interval_min") or 45) * 60

    def _loop(self):
        time.sleep(60)  # let Jarvis finish starting
        while True:
            try:
                self.reminders()
                if settings.get("agent_enabled", True) and time.time() >= self.next_run():
                    why = self.paused()
                    if why:
                        log.info("agent skipped: %s", why)
                    else:
                        self.run("schedule")
            except Exception:
                log.exception("agent loop")
            time.sleep(60)

    def status(self):
        return {"enabled": bool(settings.get("agent_enabled", True)), "running": self.running, "last_run": self.last["when"],
                "next_run": self.next_run(), "summary": self.last["summary"], "problems": self.last["problems"],
                "usage": ai.usage(), "school_senders": sources.school_patterns()}

    # ---------------- one check
    def run(self, reason="manual"):
        if not self.lock.acquire(blocking=False):
            return "I'm already checking."
        self.running = True
        try:
            return self._run(reason)
        finally:
            self.running = False
            self.lock.release()

    def _run(self, reason):
        started = time.time()
        items, problems = sources.collect(self.store)
        school = [it for it in items if it["school"]]
        for it in items:
            if not it["school"]:
                self.store.add_item(it)  # remembered (so it isn't counted again), never sent to the AI
        new_tasks, drafts, important, analysed, waiting = [], 0, [], 0, 0
        for it in school:  # full email text for school mail (the list only has a preview)
            if it["source"] in ("gmail", "outlook"):
                try:
                    mod = google if it["source"] == "gmail" else microsoft
                    it["text"] = (mod.read_mail(it["ext_id"]).get("body") or it["text"])[:3000]
                except Exception:
                    pass
        for start in range(0, len(school), BATCH):
            batch = school[start:start + BATCH]
            if not ai.agent_may_use():
                waiting += len(school) - start
                problems.append("Today's AI budget for the agent is used up; the rest waits until it resets.")
                break
            try:
                results = triage.triage(batch)
            except ai.OutOfBudget as e:
                waiting += len(school) - start
                problems.append(str(e))
                break
            except Exception as e:
                problems.append(f"Understanding failed: {str(e)[:160]}")
                log.warning("triage failed: %s", e)
                continue  # left unseen, so it's retried next time
            for i, it in enumerate(batch):
                r = results.get(i)
                item_id = self.store.add_item(it)
                if not r or not item_id:
                    continue
                analysed += 1
                self.store.update_item(item_id, category=r["category"], importance=r["importance"], summary=r["summary"],
                                       needs_reply=int(r["needs_reply"]), deadline=r["deadline"], reply=r["reply"])
                if r["task"]:
                    tid = self.store.add_task(r["task"]["title"], r["task"]["requirements"], r["task"]["type"], r["task"]["due"],
                                              r["importance"], it["source"], f'{it["source"]}:{it["ext_id"]}')
                    if tid:
                        new_tasks.append({"title": r["task"]["title"], "due": r["task"]["due"]})
                        try:
                            self.on_task(self.store.task(tid))
                        except Exception:
                            log.exception("on_task")
                if r["reply"] and it["source"] in ("gmail", "outlook"):
                    self.request_reply(it, r["reply"])
                    drafts += 1
                if r["importance"] >= 4 or r["category"] in ("assignment", "test"):
                    important.append(r["summary"] or it["title"])
        # tell the user
        for t in new_tasks:
            self.notify(f"New task: {t['title']}, due {dates.say(t['due'])}.", important=True)
        for s in important[:3]:
            if not any(s == t["title"] for t in new_tasks):
                self.notify(s, important=False)
        parts = [f"{len(items)} new item{'s' if len(items) != 1 else ''}", f"{len(school)} from school"]
        if analysed:
            parts.append(f"{analysed} understood")
        if new_tasks:
            parts.append(f"{len(new_tasks)} new task{'s' if len(new_tasks) != 1 else ''}")
        if drafts:
            parts.append(f"{drafts} reply draft{'s' if drafts != 1 else ''} waiting for approval")
        if waiting:
            parts.append(f"{waiting} waiting for AI budget")
        summary = ", ".join(parts) + "."
        self.last = {"when": time.time(), "summary": summary, "problems": problems}
        settings.update({"agent_last_run": time.time()})
        self.store.log("agent", f"Checked ({reason}, {time.time() - started:.0f}s): {summary}" + (
            " Problems: " + "; ".join(problems) if problems else ""))
        return summary

    # ---------------- reminders
    def reminders(self, now=None):
        now = now or dt.datetime.now()
        for t in self.store.tasks():
            d = dates.as_date(t["due"])
            if not d:
                continue
            days = (d - now.date()).days
            done = set(filter(None, (t["reminded"] or "").split(",")))
            key, text = None, None
            if days == 1 and "1d" not in done and now.hour >= 16:
                key, text = "1d", f"Reminder: {t['title']} is due tomorrow."
            elif days == 0 and "0d" not in done and now.hour >= 7:
                key, text = "0d", f"Reminder: {t['title']} is due today."
            elif days < 0 and "over" not in done and now.hour >= 7:
                key, text = "over", f"{t['title']} was due {dates.say(t['due'])}. Mark it done if you've finished it."
            if key:
                self.store.update_task(t["id"], reminded=",".join(sorted(done | {key})))
                self.notify(text, important=True)

    # ---------------- the task list, for the brain and the dashboards
    def task_list(self):
        rows = self.store.tasks()
        today = dt.date.today()
        for r in rows:
            r["priority"] = dates.priority(r, today)
            r["due_text"] = dates.say(r["due"], today)
        return sorted(rows, key=lambda r: (-r["priority"], r["due"] or "9999"))

    def summary(self, limit=5):
        rows = self.task_list()
        if not rows:
            return "Your task list is clear."
        head = f"You have {len(rows)} open task{'s' if len(rows) != 1 else ''}. "
        return head + " ".join(f"{r['title']}, due {r['due_text']}." for r in rows[:limit])
