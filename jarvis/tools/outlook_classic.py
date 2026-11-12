"""Classic Outlook desktop (Outlook Object Model over COM).

Reads every account configured in classic Outlook's profile, including a Gmail account added over
IMAP, without any cloud app registration. Requires classic Outlook to be installed and set up; the
"new Outlook" app has no COM interface.
"""
import datetime as dt
import functools

import pythoncom
import win32com.client

from ..config import settings

INBOX, CALENDAR = 6, 9


def _com(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        pythoncom.CoInitialize()
        try:
            return fn(*a, **kw)
        except pythoncom.com_error as e:
            raise RuntimeError(f"Classic Outlook error: {e.excepinfo[2] if e.excepinfo else e}") from None
        finally:
            pythoncom.CoUninitialize()
    return wrapper


def _ns():
    return win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")


def available():
    try:
        import winreg
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "Outlook.Application").Close()
        return True
    except OSError:
        return False


def connected():
    return settings["outlook_classic_enabled"] and available()


def _inboxes(ns):
    for store in ns.Stores:
        try:
            yield store.DisplayName, store.GetDefaultFolder(INBOX)
        except pythoncom.com_error:
            continue  # stores without an inbox (archives, public folders)


def _row(item, account):
    return {"id": item.EntryID, "subject": item.Subject or "(no subject)", "from": item.SenderName,
            "from_address": getattr(item, "SenderEmailAddress", ""), "received": str(item.ReceivedTime)[:16],
            "preview": (item.Body or "")[:300].replace("\r", " ").replace("\n", " "),
            "important": item.Importance == 2 or item.FlagStatus == 2, "account": account}


@_com
def accounts():
    return [a.SmtpAddress for a in _ns().Accounts]


@_com
def unread(limit=10):
    rows = []
    for account, inbox in _inboxes(_ns()):
        items = inbox.Items.Restrict("[UnRead] = True")
        items.Sort("[ReceivedTime]", True)
        for i, item in enumerate(items):
            if i >= limit:
                break
            if item.Class == 43:  # MailItem
                rows.append(_row(item, account))
    rows.sort(key=lambda r: r["received"], reverse=True)
    return rows[:limit]


@_com
def search_mail(query, limit=10):
    q = query.replace("'", "''")
    dasl = f"@SQL=(\"urn:schemas:httpmail:subject\" LIKE '%{q}%' OR \"urn:schemas:httpmail:fromname\" LIKE '%{q}%' OR \"urn:schemas:httpmail:textdescription\" LIKE '%{q}%')"
    rows = []
    for account, inbox in _inboxes(_ns()):
        items = inbox.Items.Restrict(dasl)
        items.Sort("[ReceivedTime]", True)
        for i, item in enumerate(items):
            if i >= limit:
                break
            if item.Class == 43:
                rows.append(_row(item, account))
    rows.sort(key=lambda r: r["received"], reverse=True)
    return rows[:limit]


@_com
def read_mail(msg_id):
    item = _ns().GetItemFromID(msg_id)
    row = _row(item, "")
    row["body"] = (item.Body or "")[:8000]
    return row


@_com
def send_mail(to, subject, body, account=None):
    ns = _ns()
    mail = win32com.client.Dispatch("Outlook.Application").CreateItem(0)
    mail.To, mail.Subject, mail.Body = to, subject, body
    if account:
        for a in ns.Accounts:
            if a.SmtpAddress.lower() == account.lower():
                mail._oleobj_.Invoke(*(64209, 0, 8, 0, a))  # SendUsingAccount
    mail.Send()
    return "Email sent."


@_com
def reply_mail(msg_id, body):
    reply = _ns().GetItemFromID(msg_id).Reply()
    reply.Body = body + "\n\n" + reply.Body
    reply.Send()
    return "Reply sent."


@_com
def events(days=7):
    cal = _ns().GetDefaultFolder(CALENDAR).Items
    cal.IncludeRecurrences = True
    cal.Sort("[Start]")
    start = dt.datetime.now()
    end = start + dt.timedelta(days=days)
    f = f"[Start] >= '{start:%m/%d/%Y %H:%M}' AND [Start] <= '{end:%m/%d/%Y %H:%M}'"
    out = []
    for i, e in enumerate(cal.Restrict(f)):
        if i >= 25:
            break
        out.append({"subject": e.Subject, "start": str(e.Start)[:16], "end": str(e.End)[:16],
                    "location": e.Location or "", "all_day": bool(e.AllDayEvent)})
    return out
