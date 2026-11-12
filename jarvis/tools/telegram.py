"""Telegram through the official Bot API with a bot you create with @BotFather.

A bot can't read or send as your personal account: it sees messages people send to the bot (or to
groups it's in) and can reply to chats that have messaged it first. Jarvis remembers those chats by
name so "send hi to Sam on Telegram" works after Sam has messaged your bot once."""
import httpx

from ..config import get_secret, settings


def connected():
    return bool(settings.get("telegram_enabled") and get_secret("telegram_bot_token"))


def _call(method, **params):
    token = get_secret("telegram_bot_token")
    if not token:
        raise RuntimeError("Telegram isn't connected. Add a bot token under Connections.")
    r = httpx.post(f"https://api.telegram.org/bot{token}/{method}", json=params, timeout=20)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"Telegram error: {j.get('description', r.status_code)}")
    return j["result"]


def whoami():
    return "@" + _call("getMe")["username"]


def _chat_name(chat):
    return chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x) or chat.get("username", "")


_recent = []  # messages already fetched this run (Telegram hands each one out only once)


def updates(limit=20):
    """Recent messages sent to the bot. Also learns which chats it may reply to."""
    res = _call("getUpdates", limit=100, timeout=0, allowed_updates=["message"])
    known = dict(settings.get("telegram_chats") or {})
    for u in res:
        m = u.get("message") or {}
        chat = m.get("chat") or {}
        if not chat:
            continue
        known[_chat_name(chat)] = chat["id"]
        _recent.append({"from": _chat_name(m.get("from") or chat), "chat": _chat_name(chat), "text": m.get("text", "")[:500]})
    if res:  # acknowledge, so Telegram stops resending them
        _call("getUpdates", offset=res[-1]["update_id"] + 1, limit=1, timeout=0)
        settings.update({"telegram_chats": known})
    del _recent[:-50]
    return _recent[-limit:]


def chats():
    return sorted((settings.get("telegram_chats") or {}).keys())


def send(chat, text):
    book = settings.get("telegram_chats") or {}
    if not book:
        updates()
        book = settings.get("telegram_chats") or {}
    key = next((k for k in book if k.lower() == chat.lower()), None) or \
        next((k for k in book if chat.lower() in k.lower()), None)
    if not key:
        raise RuntimeError(f"{chat} hasn't messaged your Telegram bot yet, so it can't message them. "
                           f"Ask them to send your bot any message first.")
    _call("sendMessage", chat_id=book[key], text=text[:4000])
    return f"Sent to {key} on Telegram."
