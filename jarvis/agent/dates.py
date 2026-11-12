"""Due dates: reading them ("by Friday", "tomorrow", "20 Nov"), saying them ("Thursday"), and ranking tasks."""
import datetime as dt
import re

DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def parse(text, today=None):
    """'YYYY-MM-DD' for a spoken or written date, or None."""
    today = today or dt.date.today()
    t = (text or "").lower().strip()
    if not t:
        return None
    if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", t):
        return m.group(0)
    if re.search(r"\btoday\b|\btonight\b", t):
        return today.isoformat()
    if "day after tomorrow" in t:
        return (today + dt.timedelta(days=2)).isoformat()
    if "tomorrow" in t:
        return (today + dt.timedelta(days=1)).isoformat()
    if "next week" in t:
        return (today + dt.timedelta(days=7 - today.weekday())).isoformat()  # next Monday
    if m := re.search(r"in (\d+) days?", t):
        return (today + dt.timedelta(days=int(m.group(1)))).isoformat()
    for i, d in enumerate(DAYS):
        if re.search(rf"\b{d}\b", t):
            ahead = (i - today.weekday()) % 7 or 7  # "Friday" said on a Friday means next Friday
            if re.search(rf"next {d}", t) and ahead < 7:
                ahead += 7
            return (today + dt.timedelta(days=ahead)).isoformat()
    if m := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([a-z]{3})[a-z]*", t) or \
            re.search(r"\b([a-z]{3})[a-z]*\s+(\d{1,2})(?:st|nd|rd|th)?\b", t):
        a, b = m.groups()
        day, mon = (a, b) if a.isdigit() else (b, a)
        if mon in MONTHS:
            d = dt.date(today.year, MONTHS.index(mon) + 1, int(day))
            if d < today - dt.timedelta(days=60):
                d = d.replace(year=today.year + 1)
            return d.isoformat()
    if m := re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t):  # day/month, as used in the UK and UAE
        y = int(m.group(3)) if m.group(3) else today.year
        y = y + 2000 if y < 100 else y
        try:
            return dt.date(y, int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            return None
    return None


def as_date(due):
    if not due:
        return None
    try:
        return dt.date.fromisoformat(str(due)[:10])
    except ValueError:
        return None


def say(due, today=None):
    """'today', 'tomorrow', 'Thursday', 'Thursday 27 Nov', 'overdue since Monday'."""
    d = as_date(due)
    if not d:
        return "no due date"
    today = today or dt.date.today()
    n = (d - today).days
    if n < 0:
        return f"overdue since {d.strftime('%A %d %b').replace(' 0', ' ')}"
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    if n < 7:
        return d.strftime("%A")
    return d.strftime("%A %d %b").replace(" 0", " ")


def priority(task, today=None):
    """Higher is more urgent: importance (1-5) plus how close the deadline is."""
    d = as_date(task.get("due"))
    today = today or dt.date.today()
    if not d:
        urgency = 1
    else:
        n = (d - today).days
        urgency = 7 if n < 0 else 6 if n == 0 else 5 if n == 1 else 4 if n <= 3 else 3 if n <= 7 else 1
    return int(task.get("importance") or 3) * 2 + urgency
