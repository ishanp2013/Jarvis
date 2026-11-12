"""Google Classroom, read-only, through Google's official API with your school account.

Your school account signs in separately from your personal Google account (Connections -> Google
Classroom) and Jarvis only asks for read access to your classes, classwork and announcements.
Some schools block outside apps: Google then shows "access blocked" and only the school admin can allow it."""
import datetime as dt

from . import google

API = "https://classroom.googleapis.com/v1"


def connected():
    return google.connected("school")


def connect():
    return google.connect(acct="school")


def disconnect():
    google.disconnect("school")


def _get(path, **params):
    return google._req("GET", API + path, "school", params=params)


def courses():
    res = _get("/courses", studentId="me", courseStates="ACTIVE", pageSize=30)
    return [{"id": c["id"], "name": c.get("name", ""), "section": c.get("section", "")} for c in res.get("courses", [])]


def _due(w):
    d = w.get("dueDate")
    if not d:
        return None
    t = w.get("dueTime") or {}
    if t:  # Classroom gives due times in UTC
        when = dt.datetime(d["year"], d["month"], d["day"], t.get("hours", 23), t.get("minutes", 59), tzinfo=dt.timezone.utc)
        return when.astimezone().strftime("%Y-%m-%dT%H:%M")
    return f"{d['year']:04d}-{d['month']:02d}-{d['day']:02d}"


def recent(per_course=8):
    """New-ish classwork and announcements across active classes, newest first."""
    out = []
    for c in courses():
        try:
            for w in _get(f"/courses/{c['id']}/courseWork", orderBy="updateTime desc", pageSize=per_course).get("courseWork", []):
                out.append({"kind": "classwork", "id": f"cw-{w['id']}", "course": c["name"], "title": w.get("title", ""),
                            "text": w.get("description", "")[:3000], "due": _due(w), "type": w.get("workType", ""),
                            "url": w.get("alternateLink", ""), "updated": w.get("updateTime", "")})
            for a in _get(f"/courses/{c['id']}/announcements", orderBy="updateTime desc", pageSize=per_course).get("announcements", []):
                out.append({"kind": "announcement", "id": f"an-{a['id']}", "course": c["name"], "title": "",
                            "text": a.get("text", "")[:3000], "due": None, "url": a.get("alternateLink", ""),
                            "updated": a.get("updateTime", "")})
        except RuntimeError:
            continue  # one class we can't read shouldn't stop the rest
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out
