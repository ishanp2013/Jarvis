"""The "welcome back" briefing and the Today view.

Built from what Jarvis already knows (items it has read, the task list, prepared work, the activity log and
your calendar) with plain templates: no AI request, and nothing leaves the laptop.

Sections: messages and emails, tasks and deadlines, what Jarvis did while you were away, and your schedule."""
import datetime as dt
import os
import time

from . import dates

SOURCE_NAMES = {"gmail": "email", "outlook": "email", "classroom": "Classroom post", "phone": "message", "discord": "Discord message"}


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def compose(store, agent, worker=None, since=None, calendar=None, pending=0, now=None):
    """{'since', 'sections': {...}, 'spoken': str, 'empty': bool}. calendar() -> events list or raises."""
    now = now or time.time()
    since = since or now - 12 * 3600
    today = dt.date.fromtimestamp(now)
    items = store.items_since(since)

    # messages and emails
    emails = [i for i in items if i["source"] in ("gmail", "outlook")]
    messages = [i for i in items if i["source"] in ("phone", "discord")]
    school = [i for i in items if i["school"]]
    important = [i for i in school if (i["importance"] or 0) >= 4 or i["category"] in ("assignment", "test")]
    announcements = [i for i in school if i["category"] == "announcement"]
    replies = [i for i in school if i["needs_reply"]]

    # tasks
    open_tasks = agent.task_list()
    new_tasks = [t for t in open_tasks if (t["created"] or 0) >= since and t["source"] != "you"]
    due_soon = [t for t in open_tasks if (d := dates.as_date(t["due"])) and 0 <= (d - today).days <= 2]
    overdue = [t for t in open_tasks if (d := dates.as_date(t["due"])) and (d - today).days < 0]
    done = [t for t in store.tasks(("done",)) if (t["updated"] or 0) >= since]

    # what Jarvis did
    jobs = worker.store.jobs(limit=50) if worker else []
    made = [j for j in jobs if j["state"] == "done" and (j["updated"] or 0) >= since and j["result_path"]]
    failed = [j for j in jobs if j["state"] == "failed" and (j["updated"] or 0) >= since]
    waiting = [j for j in jobs if j["state"] == "waiting"]
    checks = [a for a in store.activity(300) if a["kind"] == "agent" and a["ts"] >= since and a["text"].startswith("Checked")]
    problems = [a["text"].split("Problems: ", 1)[1] for a in checks if "Problems: " in a["text"]][:3]

    # schedule
    events, cal_error = [], None
    if calendar:
        try:
            events = calendar()
        except Exception as e:
            cal_error = str(e)[:120]
    ev_today = [e for e in events if e["start"][:10] == today.isoformat()]
    ev_tomorrow = [e for e in events if e["start"][:10] == (today + dt.timedelta(days=1)).isoformat()]
    due_tomorrow = [t for t in open_tasks if (d := dates.as_date(t["due"])) and (d - today).days == 1]

    sections = {
        "messages": {"emails": len(emails), "messages": len(messages), "school": len(school),
                     "important": [{"summary": i["summary"] or i["title"], "from": i["sender"], "source": i["source"]} for i in important[:6]],
                     "announcements": [i["summary"] or i["title"] for i in announcements[:4]],
                     "needs_reply": [{"summary": i["summary"] or i["title"], "from": i["sender"]} for i in replies[:5]]},
        "tasks": {"new": [_t(t) for t in new_tasks[:6]], "due_soon": [_t(t) for t in due_soon[:6]],
                  "overdue": [_t(t) for t in overdue[:6]], "open": len(open_tasks), "done": [t["title"] for t in done[:6]],
                  "top": [_t(t) for t in open_tasks[:6]]},
        "agent": {"checks": len(checks), "analysed": sum(1 for i in school if i["category"]),
                  "files": [{"title": j["title"], "file": os.path.basename(j["result_path"]), "id": j["id"]} for j in made[:5]],
                  "failed": [j["title"] for j in failed[:3]], "waiting": len(waiting), "problems": problems,
                  "approvals": pending},
        "schedule": {"today": [_e(e) for e in ev_today[:6]], "tomorrow": [_e(e) for e in ev_tomorrow[:6]],
                     "due_tomorrow": [t["title"] for t in due_tomorrow[:4]], "calendar_error": cal_error},
    }
    spoken = _speak(sections, since, now)
    empty = not (emails or messages or new_tasks or due_soon or overdue or made or failed or ev_today or pending)
    return {"since": since, "generated": now, "sections": sections, "spoken": spoken, "empty": empty}


def _t(t):
    return {"id": t["id"], "title": t["title"], "due": t["due_text"] if "due_text" in t else dates.say(t["due"]), "kind": t["kind"]}


def _e(e):
    when = "all day" if e.get("all_day") else e["start"][11:16]
    return {"time": when, "subject": e["subject"]}


def _speak(s, since, now):
    """One short spoken paragraph: the most useful things first."""
    away_h = (now - since) / 3600
    parts = ["Welcome back." if away_h >= 0.5 else "Here's where things stand."]
    m = s["messages"]
    counts = [x for x in (_plural(m["messages"], "new message") if m["messages"] else "",
                          _plural(m["emails"], "email") if m["emails"] else "") if x]
    if counts:
        parts.append("You received " + " and ".join(counts) + ".")
    t = s["tasks"]
    for task in t["new"][:2]:
        parts.append(f"New: {task['title']}, due {task['due']}.")
    if len(t["new"]) > 2:
        parts.append(f"And {len(t['new']) - 2} more new tasks.")
    for f in s["agent"]["files"][:2]:
        parts.append(f"I've prepared {f['title']} and saved it in your School Projects folder.")
    due = [x for x in t["due_soon"] if x["title"] not in {n["title"] for n in t["new"]}]
    if due:
        parts.append("Coming up: " + "; ".join(f"{x['title']}, {x['due']}" for x in due[:3]) + ".")
    if t["overdue"]:
        parts.append(f"{_plural(len(t['overdue']), 'task')} overdue, starting with {t['overdue'][0]['title']}.")
    if m["needs_reply"]:
        parts.append(f"{_plural(len(m['needs_reply']), 'message')} need{'s' if len(m['needs_reply']) == 1 else ''} your reply.")
    if s["agent"]["approvals"]:
        parts.append(f"{_plural(s['agent']['approvals'], 'item')} {'is' if s['agent']['approvals'] == 1 else 'are'} waiting for your approval.")
    if s["agent"]["failed"]:
        parts.append(f"I couldn't finish {s['agent']['failed'][0]}.")
    sc = s["schedule"]
    if sc["today"]:
        parts.append("Today: " + "; ".join(f"{e['subject']} at {e['time']}" if e["time"] != "all day" else e["subject"]
                                           for e in sc["today"][:3]) + ".")
    if sc["tomorrow"]:
        parts.append(f"Tomorrow you have {sc['tomorrow'][0]['subject']}" +
                     (f" and {_plural(len(sc['tomorrow']) - 1, 'other event')}." if len(sc["tomorrow"]) > 1 else "."))
    if len(parts) == 1:
        parts.append("Nothing new since you left, and nothing urgent." if t["open"] == 0 else
                     f"Nothing new. You have {_plural(t['open'], 'open task')}, the next being {t['top'][0]['title']}, due {t['top'][0]['due']}.")
    return " ".join(parts)
