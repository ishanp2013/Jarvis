"""WhatsApp: there is no official API for a personal account, so Jarvis works through the WhatsApp
desktop app: it opens the chat with the message typed in and, for saved contacts, presses Send
(unless "Ask before sending" is on).

Reading happens locally through Windows UI Automation (the accessibility interface), in two ways:
- the chat list: chat names, times, the last message's preview and unread counts. Nothing is opened.
- one whole chat ("read my chat with Sam", "has Sam replied?"): Jarvis opens that chat in WhatsApp Desktop and
  reads the messages it has loaded (usually the most recent few dozen), with who sent each, the time, and
  whether yours were sent, delivered or read. Opening a chat marks its new messages as read, just like you
  opening it, and Jarvis then goes back to the chat you had open.

WhatsApp links can target a chat only by phone number, so names are looked up in a small contact
list kept in Jarvis's local settings."""
import difflib
import os
import re
import time
import urllib.parse

from ..config import settings

# Speech recognition often writes the app's name in other ways.
_APP_NAME = re.compile(r"\bwhat'?s\s?app\b|\bwhats\s?up\b(?=\s*$)", re.I)

_PATTERNS = [
    # "send hi to sam on whatsapp"
    re.compile(r"^(?:please )?(?:send|text|message|whatsapp|tell)\s+(?P<msg>.+?)\s+to\s+(?P<name>[\w .'-]+?)\s+(?:on|in|via|through|using|over)\s+whatsapp$", re.I),
    # "send sam a whatsapp saying hi"
    re.compile(r"^(?:send|write)\s+(?P<name>[\w .'-]+?)\s+a\s+whatsapp(?: message)?\s*(?:saying|that says|:)?\s*(?P<msg>.+)$", re.I),
    # "message sam on whatsapp saying hi" / "whatsapp sam: hi"
    re.compile(r"^(?:please )?(?:send|text|message|whatsapp)\s+(?:a message to\s+)?(?P<name>[\w .'-]+?)\s+(?:(?:on|in|via)\s+whatsapp\s*)?(?:saying|that says|that|:)\s*(?P<msg>.+)$", re.I),
    # "on whatsapp, send hi to sam"
    re.compile(r"^(?:on|in)\s+whatsapp,?\s+(?:send|text|tell)\s+(?P<msg>.+?)\s+to\s+(?P<name>[\w .'-]+)$", re.I),
]

_WA = r"(?:\s+(?:on|in|over|through|from)\s+whatsapp)"
_READ = [
    # "has sam replied (to my message) on whatsapp", "did sam text me back", "has sam send any replies"
    re.compile(r"^(?:has|have|did)\s+(?P<name>.+?)\s+(?:sen[dt]|repl|respond|answer|text|messag|writ|wrote|got back|said|say|seen|read|opened|looked)", re.I),
    # "any reply from sam on whatsapp", "did i get a message from sam"
    re.compile(r"\b(?:any|a|an)\s+(?:new\s+)?(?:repl(?:y|ies)|messages?|response|answer|texts?)\s+from\s+(?P<name>.+?)" + _WA + r"?$", re.I),
    # "what did sam say on whatsapp"
    re.compile(r"^what\s+did\s+(?P<name>.+?)\s+(?:say|send|reply|write|text)", re.I),
    # "read my chat with sam on whatsapp", "open my whatsapp chat with sam", "what's in my chat with sam"
    re.compile(r"\b(?:chat|conversation|messages)\s+(?:with|from)\s+(?P<name>.+?)" + _WA + r"?$", re.I),
    # "last message from sam on whatsapp"
    re.compile(r"\blast\s+(?:whatsapp\s+)?message\s+(?:from|with|in|of)\s+(?P<name>.+?)" + _WA + r"?$", re.I),
]
_SUMMARY = re.compile(r"^(?:check|read)(?: my)? whatsapp(?: messages| chats)?$|\bwhatsapp messages\b|"
                      r"\b(?:any|new|unread)\b.*\b(?:messages?|chats?|texts?)\b.*\bwhatsapp\b|\bwhatsapp\b.*\bunread\b", re.I)
_NOBODY = {"anyone", "anybody", "someone", "somebody", "i", "you", "whatsapp", "anyone else"}


def normalise(text):
    return _APP_NAME.sub("whatsapp", text.strip().rstrip(".!?"))


def parse_read(text):
    """("reply", name) for "has Sam replied on WhatsApp?", ("summary", None) for "check my WhatsApp", else None.
    The question has to mention WhatsApp, so it isn't confused with email."""
    t = normalise(text)
    if "whatsapp" not in t.lower():
        return None
    for p in _READ:
        if m := p.search(t):
            name = re.sub(_WA + r".*$", "", m.group("name"), flags=re.I)
            name = re.sub(r"^(?:my|the)\s+|\s+(?:me|back|any|yet)$", "", name.strip(), flags=re.I).strip(" ,'\"")
            if not name or name.lower() in _NOBODY:
                return "summary", None
            if re.search(r"\b(?:seen|read|opened|looked at)\b", t[m.start("name") + len(m.group("name")):], re.I):
                return "seen", name
            if re.search(r"\b(?:chat|conversation)\s+(?:with|from)\b|^(?:read|open|show)\b|\bwhat did\b", t, re.I):
                return "chat", name
            return "reply", name
    if _SUMMARY.search(t):
        return "summary", None
    return None


# ---- reading the chat list ---------------------------------------------------------------------------------
_TIME = (r"(?:\d{1,2}:\d{2}(?:\s?[AaPp]\.?[Mm]\.?)?|\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|yesterday|today|"
         r"monday|tuesday|wednesday|thursday|friday|saturday|sunday)")
_UNREAD = re.compile(r"^(\d+)\s+unread\s+messages?\s*", re.I)


_REACTION = re.compile(r'^(?:(?P<who>[^:]+?)\s+)?reacted\s+(?P<emo>.+?)\s+to:?\s*"?(?P<msg>.*?)"?$', re.I)


class ReadError(Exception):
    pass


def parse_row(header, leaves):
    """One chat-list row. `header` is the row's first part (e.g. "2 unread messages Sam 9:41 PM"), `leaves`
    the row's text and emoji pieces in reading order. Returns {chat, time, unread, sender, text, from_me}."""
    unread = 0
    header = header or ""
    if m := _UNREAD.match(header):
        unread, header = int(m.group(1)), header[m.end():]
    header = header.strip()
    when = ""
    if m := re.search(_TIME + r"\s*$", header, re.I):
        when, header = m.group(0).strip(), header[:m.start()].strip()
    pieces = [x for x in leaves if x and not _UNREAD.match(x)]
    after = 0
    for i, x in enumerate(pieces):
        if when and x.strip() == when:
            after = i + 1
            break
    rest = pieces[after:]
    sender = ""
    if len(rest) >= 3 and rest[1].strip() == ":":
        sender, rest = rest[0].strip().lstrip("~").strip(), rest[2:]
    text = re.sub(r"\s+", " ", "".join(rest).replace("​", "")).strip()
    row = {"chat": header, "time": when, "unread": unread, "sender": sender, "text": text,
           "from_me": sender.lower() == "you", "reaction": "", "reacted_to": ""}
    # the latest thing in the chat can be a reaction rather than a message: 'Reacted 👍 to: "see you"'
    if m := _REACTION.match(text):
        who = (m.group("who") or sender or "").strip()
        row.update(reaction=m.group("emo").strip(), reacted_to=m.group("msg").strip(), from_me=who.lower() == "you",
                   sender="" if who.lower() in ("", "you") else who)
    return row


def _window():
    import psutil
    import win32gui
    import win32process
    pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower().startswith("whatsapp")}
    if not pids:
        raise ReadError("WhatsApp Desktop isn't running. Open it once and I can check your chats.")
    found = []

    def cb(h, _):
        if win32process.GetWindowThreadProcessId(h)[1] in pids and win32gui.IsWindowVisible(h) and win32gui.GetWindowText(h):
            found.append(h)
    win32gui.EnumWindows(cb, None)
    if not found:
        raise ReadError("WhatsApp Desktop is running in the background without a window. Open it once and I can check your chats.")
    return found[0]


def _session(work):
    """Show WhatsApp (without taking focus) if it's minimised, find its chat list, run work(client, U, root, grid),
    and minimise it again afterwards."""
    if not settings.get("whatsapp_read", True):
        raise ReadError("Reading WhatsApp is turned off in Connections.")
    import win32gui
    from . import uia
    client, U = uia._client(), uia._U()
    hwnd = _window()
    was_min = bool(win32gui.IsIconic(hwnd))
    cond = client.CreatePropertyCondition(U.UIA_NamePropertyId, "Chat list")
    try:
        grid = None
        if not was_min:
            grid = client.ElementFromHandle(hwnd).FindFirst(U.TreeScope_Descendants, cond)
        if grid is None:
            win32gui.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE: whatever you're typing in keeps the focus
            deadline = time.time() + 6
            while grid is None and time.time() < deadline:
                time.sleep(0.5)
                grid = client.ElementFromHandle(hwnd).FindFirst(U.TreeScope_Descendants, cond)
        if grid is None:
            raise ReadError("I couldn't find the chat list in WhatsApp. If it's showing a login code or an update, finish that first.")
        return work(client, U, client.ElementFromHandle(hwnd), grid)
    finally:
        if was_min:
            win32gui.ShowWindow(hwnd, 7)  # SW_SHOWMINNOACTIVE
            time.sleep(0.3)
            if not win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, 6)


def recent_chats():
    """The chats WhatsApp Desktop's list shows, newest first (usually the 15 to 20 most recent). Read-only:
    nothing is opened."""
    return _session(lambda client, U, root, grid: [c for c, _ in _rows(client, grid)])


def _rows(client, grid):
    walker = client.RawViewWalker

    def kids(e):
        out, c = [], walker.GetFirstChildElement(e)
        while c:
            out.append(c)
            c = walker.GetNextSiblingElement(c)
        return out

    def leaves(e, out, depth=0):
        for k in kids(e):
            if k.CurrentControlType in (50020, 50006) and k.CurrentName:  # text, image (emoji)
                out.append(k.CurrentName)
            if depth < 8:
                leaves(k, out, depth + 1)
        return out

    items = client.CreatePropertyCondition(30003, 50029)  # control type: data item
    chats = []
    for row in kids(grid):
        full = row.CurrentName or ""
        found = row.FindAll(4, items)  # descendants: the row's copy, its header part, labels like "Pinned chat"
        head = None  # the header is the shortest part the row's name starts with: "[N unread] name time"
        for i in range(found.Length):
            n = found.GetElement(i).CurrentName or ""
            if n and n != full and full.startswith(n) and (head is None or len(n) < len(head)):
                head = n
        if head is None:
            continue
        c = parse_row(head, leaves(row, []))
        if c["chat"]:
            chats.append((c, row))
    return chats


_MSG_TIME = re.compile(r"^\d{1,2}:\d{2}(?:\s?[AaPp]\.?[Mm]\.?)?$")
_DAY = re.compile(r"^(?:today|yesterday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
                  r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})$", re.I)
_STATUS = re.compile(r"^\s*(sent|delivered|read|pending|played|seen)\s*$", re.I)


def parse_messages(tokens):
    """Messages from the chat panel's pieces in reading order: ("me", "You:") starts one of your messages,
    ("t", text) is text or an emoji, ("status", "Read") follows your message's time, ("quote", ...) is a quoted
    message (left out). Every message ends with its time. Returns [{me, text, time, day, status}]."""
    msgs, parts, me, day = [], [], False, ""
    for kind, val in tokens:
        val = (val or "").replace("\u200b", "")
        v = val.strip()
        if kind == "me":
            me = True
        elif kind == "status":
            if msgs and msgs[-1]["me"] and not msgs[-1]["status"]:
                msgs[-1]["status"] = _STATUS.match(val).group(1).capitalize() if _STATUS.match(val) else v
        elif kind == "t" and _MSG_TIME.match(v):
            text = re.sub(r"\s+", " ", " ".join(parts)).strip()
            if text:
                msgs.append({"me": me, "text": text, "time": v, "day": day, "status": ""})
            parts, me = [], False
        elif kind == "t" and _DAY.match(v) and not parts:
            day = v
        elif kind == "t" and v and v not in ("~", "Forwarded", "You"):
            parts.append(v.lstrip("~ ").strip() if v.startswith("~") else v)
    return msgs


def _cached_tree(client, U, element):
    """The element's whole subtree (names and control types) fetched in one go: far faster than one call each."""
    req = client.CreateCacheRequest()
    req.AddProperty(U.UIA_NamePropertyId)
    req.AddProperty(U.UIA_ControlTypePropertyId)
    req.TreeScope = 7  # element, children and descendants
    req.TreeFilter = client.RawViewCondition
    return element.BuildUpdatedCache(req)


def _cached_kids(e):
    try:
        arr = e.GetCachedChildren()
    except Exception:
        return []
    return [arr.GetElement(i) for i in range(arr.Length)] if arr else []


def _panel_tokens(panel):
    tokens = []

    def walk(e, depth=0):
        for k in _cached_kids(e):
            ct, nm = k.CachedControlType, (k.CachedName or "")
            if ct == 50000 and nm.startswith("Quoted message"):
                continue  # a reply's quote: its text belongs to an older message
            sub = _cached_kids(k)
            if ct in (50020, 50006) and nm:  # text, emoji
                tokens.append(("t", nm))
            elif ct == 50026 and nm.strip() == "You:":
                tokens.append(("me", nm))
            elif ct == 50026 and _STATUS.match(nm):
                tokens.append(("status", nm))
            elif ct == 50000 and nm and not any(x.CachedName for x in sub):  # a link or long text shown as a button
                tokens.append(("t", nm))
            if depth < 40:
                walk(k, depth + 1)
    walk(panel)
    return tokens


def _compose(client, U, root, chat):
    """The message box of the open chat, if that chat is `chat` (WhatsApp labels it "Type a message to <chat>")."""
    cond = client.CreateAndCondition(client.CreatePropertyCondition(U.UIA_ControlTypePropertyId, 50004),
                                     client.CreatePropertyCondition(U.UIA_NamePropertyId, f"Type a message to {chat}"))
    return root.FindFirst(U.TreeScope_Descendants, cond)


def _open(client, U, root, row, chat, wait=6):
    """Open a chat-list row and wait until WhatsApp shows that chat. Of the row's selectable parts only the header
    opens it, so each is tried in turn. Returns the chat's message box, or None."""
    items = row.FindAll(4, client.CreatePropertyCondition(U.UIA_ControlTypePropertyId, 50029))
    for i in range(items.Length):
        pat = items.GetElement(i).GetCurrentPattern(10010)  # SelectionItem
        if not pat:
            continue
        try:
            pat.QueryInterface(U.IUIAutomationSelectionItemPattern).Select()
        except Exception:
            continue
        deadline = time.time() + wait
        while time.time() < deadline:
            box = _compose(client, U, root, chat)
            if box is not None:
                return box
            time.sleep(0.3)
        wait = 2  # the first part usually doesn't open it: don't wait as long for the others
    return None


def _open_chat_name(client, U, root):
    """The name of the chat open right now (from its message box), or None."""
    e = root.FindFirst(U.TreeScope_Descendants, client.CreatePropertyCondition(U.UIA_ControlTypePropertyId, 50004))
    edits = root.FindAll(U.TreeScope_Descendants, client.CreatePropertyCondition(U.UIA_ControlTypePropertyId, 50004)) \
        if e is None or not (e.CurrentName or "").startswith("Type a message to ") else None
    if edits is not None:
        e = None
        for i in range(min(edits.Length, 8)):
            if (edits.GetElement(i).CurrentName or "").startswith("Type a message to "):
                e = edits.GetElement(i)
                break
    return (e.CurrentName or "")[len("Type a message to "):] if e is not None else None


def read_chat(name):
    """Open the chat matching `name` and read the messages WhatsApp has loaded. Returns
    {"chat", "messages", "was_unread"}; the chat you had open before is opened again afterwards."""
    def work(client, U, root, grid):
        rows = _rows(client, grid)
        found = match_chat([c for c, _ in rows], name)
        if not found:
            raise ReadError(f"I don't see a chat with {name} among your {len(rows)} most recent WhatsApp chats. "
                            "If it's saved under another name, ask me with that name.")
        row = next(r for c, r in rows if c is found)
        before = _open_chat_name(client, U, root)
        box = _compose(client, U, root, found["chat"]) or _open(client, U, root, row, found["chat"])
        if box is None:
            raise ReadError(f"I couldn't open your chat with {found['chat']} in WhatsApp.")
        walker, chat_list = client.RawViewWalker, client.CreatePropertyCondition(U.UIA_NamePropertyId, "Chat list")
        panel = box
        for _ in range(40):  # up to the part of the window that holds this chat, but not the chat list
            parent = walker.GetParentElement(panel)
            if parent is None or parent.FindFirst(U.TreeScope_Descendants, chat_list):
                break
            panel = parent
        msgs = parse_messages(_panel_tokens(_cached_tree(client, U, panel)))
        if before and before != found["chat"]:  # back to the chat you had open
            prev = next((r for c, r in rows if c["chat"] == before), None)
            if prev is not None:
                try:
                    _open(client, U, root, prev, before, wait=3)
                except Exception:
                    pass
        return {"chat": found["chat"], "messages": msgs, "was_unread": found["unread"], "row": found}
    return _session(work)


def _say_msg(m, chat):
    who = "You" if m["me"] else chat
    return f"{who}{_when(m['time'])}: \"{_quote(m['text'], 160)}\""


def chat_reply_status(name, data=None):
    """Spoken answer to "has <name> replied?", from the whole chat: replies after your last message, if any."""
    try:
        data = read_chat(name) if data is None else data
    except ReadError as e:
        return str(e)
    msgs, chat = data["messages"], data["chat"]
    if not msgs:
        return f"I opened your chat with {chat} but couldn't read any messages in it."
    mine = [i for i, m in enumerate(msgs) if m["me"]]
    if not mine:
        last = msgs[-1]
        return f"You haven't messaged {chat} recently. Their latest message{_when(last['time'])}: \"{_quote(last['text'])}\"."
    after = msgs[mine[-1] + 1:]
    if not after:
        seen = {"Read": "They've read it", "Delivered": "It's delivered but not read yet",
                "Sent": "It's sent but not delivered yet"}.get(msgs[-1]["status"], "")
        row = data.get("row") or {}
        react = f" They reacted {row['reaction']} to it." if row.get("reaction") and not row.get("from_me") else ""
        return f"No reply yet. Your last message{_when(msgs[-1]['time'])} was \"{_quote(msgs[-1]['text'], 120)}\"." + \
            (f" {seen}." if seen else "") + react
    first = after[0]
    more = f" Then {len(after) - 1} more message{'s' if len(after) > 2 else ''}, the latest: \"{_quote(after[-1]['text'], 120)}\"." \
        if len(after) > 1 else ""
    return f"Yes. {chat} replied{_when(first['time'])}: \"{_quote(first['text'])}\".{more}"


def chat_seen_status(name, data=None):
    """Spoken answer to "has <name> seen my message?": the read ticks on your last message."""
    try:
        data = read_chat(name) if data is None else data
    except ReadError as e:
        return str(e)
    mine = [m for m in data["messages"] if m["me"]]
    if not mine:
        return f"You haven't sent {data['chat']} anything recently."
    m = mine[-1]
    state = {"Read": "Yes, they've read it", "Delivered": "Not yet: it's delivered but not read",
             "Sent": "Not yet: it's sent but not delivered", "Pending": "Not yet: it hasn't been sent"}.get(
        m["status"], "I can't tell: WhatsApp isn't showing read receipts for it (they may have read receipts off)")
    return f"{state}. Your last message to {data['chat']}{_when(m['time'])}: \"{_quote(m['text'], 120)}\"."


def chat_recap(name, data=None, last=6):
    """Spoken: the last few messages of a chat."""
    try:
        data = read_chat(name) if data is None else data
    except ReadError as e:
        return str(e)
    msgs = data["messages"][-last:]
    if not msgs:
        return f"I opened your chat with {data['chat']} but couldn't read any messages in it."
    return f"Your chat with {data['chat']}, latest {len(msgs)} messages. " + ". ".join(_say_msg(m, data["chat"]) for m in msgs) + "."


def chat_for_ai(name, last=40):
    """For Herald's tool: the chat as short lines, oldest first."""
    try:
        data = read_chat(name)
    except ReadError as e:
        return str(e)
    lines = [f"[{m['day'] + ' ' if m['day'] else ''}{m['time']}] {'Me' if m['me'] else data['chat']}: {_quote(m['text'], 300)}"
             + (f" ({m['status'].lower()})" if m["me"] and m["status"] else "") for m in data["messages"][-last:]]
    note = " Opening it marked its new messages as read." if data["was_unread"] else ""
    return f"Chat with {data['chat']} (the {len(lines)} latest messages WhatsApp has loaded).{note}\n" + "\n".join(lines)


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (s or "").lower())).strip()


def match_chat(chats, name):
    """Best chat for a spoken name: exact, then containing every word, then close spelling."""
    want = _norm(name)
    if not want:
        return None
    names = [_norm(c["chat"]) for c in chats]
    for c, n in zip(chats, names):
        if n == want:
            return c
    for c, n in zip(chats, names):
        if want in n or all(w in n.split() for w in want.split()):
            return c
    close = difflib.get_close_matches(want, names, n=1, cutoff=0.72)
    if close:
        return chats[names.index(close[0])]
    first = want.split()[0]
    for c, n in zip(chats, names):  # a close first word ("suriya" for "surya")
        if len(first) >= 4 and any(difflib.SequenceMatcher(None, first, w).ratio() >= 0.8 for w in n.split()):
            return c
    return None


def _when(t):
    if not t:
        return ""
    if re.match(r"\d{1,2}:\d{2}", t):
        return f" at {t}"
    return f" {t.lower()}" if t.lower() in ("yesterday", "today") else f" on {t}"


def _quote(text, limit=220):
    text = text or "a photo, voice note or file"
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def reply_status(name, chats=None):
    """Spoken answer to "has <name> replied on WhatsApp?", from the chat list only."""
    try:
        chats = recent_chats() if chats is None else chats
    except ReadError as e:
        return str(e)
    c = match_chat(chats, name)
    if not c:
        return (f"I don't see a chat with {name} among your {len(chats)} most recent WhatsApp chats, so nothing new from "
                f"them lately. If the chat is saved under another name, ask me with that name.")
    if c.get("reaction") and not c["from_me"]:
        return (f"No written reply, but {c['sender'] or c['chat']} reacted {c['reaction']} to your message"
                f"{_when(c['time'])}: \"{_quote(c['reacted_to'], 120)}\".")
    if c["from_me"]:
        return f"Not yet. The last message in your chat with {c['chat']} is yours{_when(c['time'])}: \"{_quote(c['text'])}\"."
    who = f"{c['sender']} in {c['chat']}" if c["sender"] else c["chat"]
    unread = f" You have {c['unread']} unread." if c["unread"] else ""
    return f"Yes. The latest message is from {who}{_when(c['time'])}: \"{_quote(c['text'])}\".{unread}"


def summary(chats=None):
    """Spoken overview: which chats have unread messages, with the newest preview of each."""
    try:
        chats = recent_chats() if chats is None else chats
    except ReadError as e:
        return str(e)
    unread = [c for c in chats if c["unread"]]
    if not unread:
        return (f"No unread WhatsApp chats. The most recent is {chats[0]['chat']}{_when(chats[0]['time'])}."
                if chats else "Your WhatsApp chat list is empty.")
    total = sum(c["unread"] for c in unread)
    parts = []
    for c in unread[:4]:
        who = f"{c['sender']} in {c['chat']}" if c["sender"] else c["chat"]
        parts.append(f"{who}: \"{_quote(c['text'], 120)}\"")
    more = f" And {len(unread) - 4} more chats." if len(unread) > 4 else ""
    return (f"You have {total} unread WhatsApp message{'s' if total != 1 else ''} in {len(unread)} "
            f"chat{'s' if len(unread) != 1 else ''}. " + ". ".join(parts) + "." + more)


def chats_for_ai(name=""):
    """For Herald's tool: the chat list (or one chat) as short lines."""
    try:
        chats = recent_chats()
    except ReadError as e:
        return str(e)
    if name:
        c = match_chat(chats, name)
        if not c:
            return f"No chat matching '{name}' among the {len(chats)} most recent chats."
        chats = [c]
    return "\n".join(f"{c['chat']} | {c['time']} | unread {c['unread']} | last from "
                     f"{'me' if c['from_me'] else (c['sender'] or c['chat'])}: {_quote(c['text'], 160)}"
                     for c in chats) or "No chats."


def parse(text):
    """Return (name, message) for a WhatsApp send request, or None."""
    t = normalise(text)
    if "whatsapp" not in t.lower():
        return None
    for p in _PATTERNS:
        m = p.match(t)
        if m:
            msg = m.group("msg").strip().strip("\"'")
            return m.group("name").strip(), msg
    return None


def contacts():
    return dict(settings["whatsapp_contacts"] or {})


def find_contact(name):
    book = contacts()
    lowered = {k.lower(): k for k in book}
    key = name.lower().strip()
    if key in lowered:
        return lowered[key], book[lowered[key]]
    close = difflib.get_close_matches(key, list(lowered), n=1, cutoff=0.75)
    return (lowered[close[0]], book[lowered[close[0]]]) if close else (None, None)


def save_contact(name, phone):
    digits = re.sub(r"\D", "", phone or "")
    if not name.strip() or len(digits) < 8:
        raise ValueError("Give a name and a full number with country code, e.g. +971 50 123 4567.")
    book = contacts()
    book[name.strip()] = digits
    settings.update({"whatsapp_contacts": book})
    return book


def remove_contact(name):
    book = contacts()
    book.pop(name, None)
    settings.update({"whatsapp_contacts": book})
    return book


def open_with_message(text, phone=""):
    if not settings["whatsapp_enabled"]:
        return "WhatsApp drafts are turned off in Connections."
    digits = re.sub(r"\D", "", phone or "")
    q = urllib.parse.quote(text)
    # The desktop app handles whatsapp:// directly; wa.me is the documented web fallback.
    try:
        os.startfile(f"whatsapp://send?{'phone=' + digits + '&' if digits else ''}text={q}")
    except OSError:
        os.startfile(f"https://wa.me/{digits}?text={q}")
    return "WhatsApp is open with your message ready. Check it, then press Send." if digits else \
        "WhatsApp is open with your message ready. Choose the chat, then press Send."


def _whatsapp_in_front(timeout):
    import psutil
    import win32gui
    import win32process
    deadline = time.time() + timeout
    while time.time() < deadline:
        hwnd = win32gui.GetForegroundWindow()
        try:
            if "whatsapp" in psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower():
                return True
        except (psutil.Error, ValueError):
            pass
        time.sleep(0.3)
    return False


def send_to(name, text):
    """Opens the saved contact's chat with `text` typed in and presses Enter in WhatsApp to send it.
    Only for saved contacts (a name alone can't pick a chat), and only once WhatsApp is the window in front."""
    if not settings["whatsapp_enabled"]:
        return "WhatsApp is turned off in Connections."
    found, phone = find_contact(name)
    if not phone:
        return draft_to(name, text) + " I can only send by myself to contacts saved in Connections."
    open_with_message(text, phone)
    if not _whatsapp_in_front(12):
        return f"WhatsApp didn't come to the front, so I left the message to {found} typed in but unsent."
    time.sleep(2.5)  # let the chat finish loading with the text in the box
    if not _whatsapp_in_front(1):
        return f"You switched away from WhatsApp, so I left the message to {found} unsent."
    import win32api
    import win32con
    win32api.keybd_event(win32con.VK_RETURN, 0, 0, 0)
    win32api.keybd_event(win32con.VK_RETURN, 0, win32con.KEYEVENTF_KEYUP, 0)
    return f"Sent to {found} on WhatsApp."


def draft_to(name, text):
    """Open WhatsApp at `name`'s chat (if saved) with `text` typed in. Never sends."""
    found, phone = find_contact(name) if name else (None, None)
    result = open_with_message(text, phone or "")
    if name and not found and settings["whatsapp_enabled"]:
        result += f" I don't have a number saved for {name}; add one in Connections to open their chat directly."
    return result
