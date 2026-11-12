"""Pressing buttons inside apps through Windows UI Automation, the accessibility interface: "press Save in Notepad",
"click the Settings tab in Discord". Controls are invoked directly, so the mouse never moves.

Works with most Windows apps. Some Chromium-based apps (Spotify, for one) don't expose their buttons this way."""
import difflib
import re

import comtypes
import comtypes.client

from . import windows as win

# Buttons whose press could send, buy, delete or change something: Jarvis asks first (on-screen button only).
RISKY = re.compile(r"\b(send|post|publish|submit|delete|remove|erase|discard|uninstall|format|buy|purchase|pay|order|checkout|"
                   r"transfer|confirm|accept|agree|allow|grant|sign out|log ?out|reset|clear|empty|overwrite|replace all|block|report)\b", re.I)

# Control types worth pressing: button, checkbox, hyperlink, list item, menu item, radio, tab, split button, tree item, menu bar item
_TYPES = {50000, 50002, 50005, 50007, 50011, 50013, 50019, 50024, 50031, 50010}
_INVOKE, _TOGGLE, _SELECT, _EXPAND = 10000, 10015, 10010, 10005

_uia = None


def _client():
    global _uia
    comtypes.CoInitialize()
    if _uia is None:
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as U
        _uia = comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)
    return _uia


def _U():
    from comtypes.gen import UIAutomationClient as U
    return U


_REQ = [
    re.compile(r"^(?:click|press|tap|hit|select|choose|push)\s+(?:on\s+)?(?:the\s+)?(.+?)(?:\s+(?:button|tab|link|option|menu item|menu|checkbox|toggle|item))?\s+(?:in|on)\s+(?:the\s+)?(.+?)(?:\s+(?:app|window))?$"),
    re.compile(r"^in\s+(?:the\s+)?(?P<app>.+?)(?:\s+(?:app|window))?,?\s+(?:click|press|tap|hit|select|choose|push)\s+(?:on\s+)?(?:the\s+)?(?P<name>.+?)(?:\s+(?:button|tab|link|option|menu item|menu|checkbox|toggle|item))?$"),
]


def parse(text):
    """(button name, app) for 'press X in Y' / 'in Y, click X', else None. Text is lowercase."""
    t = text.strip().rstrip(".!?")
    if m := _REQ[0].match(t):
        return m[1], m[2]
    if m := _REQ[1].match(t):
        return m["name"], m["app"]
    return None


def controls(hwnd):
    """[(name, control type, element)] for the pressable, enabled controls in a window."""
    uia = _client()
    root = uia.ElementFromHandle(hwnd)
    found = root.FindAll(4, uia.CreateTrueCondition())  # TreeScope_Descendants
    out = []
    for i in range(found.Length):
        e = found.GetElement(i)
        try:
            name, ctype = (e.CurrentName or "").strip(), e.CurrentControlType
            if name and ctype in _TYPES and e.CurrentIsEnabled and not e.CurrentIsOffscreen:
                out.append((name, ctype, e))
        except comtypes.COMError:
            continue
    return out


def find(hwnd, wanted):
    items = controls(hwnd)
    w = wanted.lower().strip()
    names = [n.lower() for n, _, _ in items]
    for test in (lambda n: n == w, lambda n: n.startswith(w) or w in n.split(), lambda n: w in n):
        hits = [i for i, n in enumerate(names) if test(n)]
        if hits:
            return items[hits[0]]
    close = difflib.get_close_matches(w, names, n=1, cutoff=0.75)
    return items[names.index(close[0])] if close else None


def _press(e):
    U = _U()
    for pid, iface, act in ((_INVOKE, U.IUIAutomationInvokePattern, "Invoke"), (_TOGGLE, U.IUIAutomationTogglePattern, "Toggle"),
                            (_SELECT, U.IUIAutomationSelectionItemPattern, "Select"), (_EXPAND, U.IUIAutomationExpandCollapsePattern, "Expand")):
        try:
            pat = e.GetCurrentPattern(pid)
            if pat:
                getattr(pat.QueryInterface(iface), act)()
                return True
        except comtypes.COMError:
            continue
    return False


def locate(name, app):
    """(window, (control name, type, element)) or an error message."""
    hits = [w for w in win.find_windows(app) if w[2] not in win.PROTECTED or app.lower() in ("file explorer", "explorer")]
    if not hits:
        return f"{app} doesn't seem to be open."
    ctl = find(hits[0][0], name)
    if not ctl:
        return f"I couldn't find a {name} button in {app}. Some apps, like Spotify, don't let Windows see their buttons."
    return hits[0], ctl


def press(name, app):
    found = locate(name, app)
    if isinstance(found, str):
        return found
    _, (label, _, e) = found
    return f"Pressed {label} in {app}." if _press(e) else f"Found {label} in {app}, but it wouldn't press."
