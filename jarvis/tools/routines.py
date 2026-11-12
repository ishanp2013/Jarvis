"""Routines: "When I say focus mode, close Discord and open my to-do list." Saying "focus mode" later runs
each step as if you'd said it, with the same safety checks (closing an app still asks first)."""
import re

from ..config import settings

_VERBS = r"(?:open|close|quit|launch|start|play|pause|resume|put|move|snap|maximi[sz]e|minimi[sz]e|switch|mute|unmute|lock|find|search|go|show|turn|volume|next|previous|send|message|text|remember)\b"
_DEFINE = re.compile(r"^(?:when(?:ever)?|if)\s+i\s+say\s+[\"']?(.+?)[\"']?\s*[,:]\s*(?:you\s+should\s+|please\s+|then\s+|just\s+)?(.+)$"
                     r"|^(?:when(?:ever)?|if)\s+i\s+say\s+[\"']?(.+?)[\"']?\s+(?:you\s+should\s+|please\s+|then\s+|just\s+)?(" + _VERBS + r".+)$")
_SPLIT = re.compile(r"\s*[,;]\s*(?:and\s+)?(?:then\s+)?|\s+and\s+then\s+|\s+then\s+|\s+and\s+(?=" + _VERBS + ")")


def routines():
    return dict(settings["routines"] or {})


def steps(text):
    return [s.strip(" .") for s in _SPLIT.split(text) if s and s.strip(" .")]


def parse_define(text):
    """(name, [steps]) for 'when I say X, do A and B', else None. Text is lowercase."""
    m = _DEFINE.match(text.strip().rstrip(".!"))
    if not m:
        return None
    name, body = (m[1], m[2]) if m[1] else (m[3], m[4])
    name = name.strip(" \"'.,")
    parts = steps(body)
    return (name, parts) if name and parts else None


def save(name, parts):
    book = routines()
    book[name] = parts
    settings.update({"routines": book})


def remove(name):
    book = routines()
    key = next((k for k in book if k.lower() == name.lower().strip(" \"'")), None)
    if key:
        book.pop(key)
        settings.update({"routines": book})
    return key


def match(text):
    """The routine `text` asks to run ('focus mode', 'run focus mode', 'start focus mode'), or None."""
    t = re.sub(r"^(?:run|do|start|activate|begin|go into|enter)\s+(?:my\s+|the\s+)?(?:routine\s+)?", "", text.strip().rstrip(".!?"))
    t = re.sub(r"\s+(?:routine|please)$", "", t)
    book = routines()
    return next((k for k in book if k.lower() == t), None)
