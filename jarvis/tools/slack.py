"""Slack through the official Web API with your own Slack app's bot token (xoxb-...).

The bot only sees channels it was added to (/invite @YourBot in the channel), and posts as the bot,
never as you. Token kept in Windows Credential Manager."""
import httpx

from ..config import get_secret, settings

API = "https://slack.com/api/"


def connected():
    return bool(settings.get("slack_enabled") and get_secret("slack_bot_token"))


def _call(method, http="GET", **kw):
    token = get_secret("slack_bot_token")
    if not token:
        raise RuntimeError("Slack isn't connected. Add a bot token under Connections.")
    headers = {"Authorization": f"Bearer {token}"}
    if http == "POST":
        r = httpx.post(API + method, headers=headers, json=kw, timeout=20)
    else:
        r = httpx.get(API + method, headers=headers, params=kw, timeout=20)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(f"Slack error: {j.get('error', r.status_code)}")
    return j


def whoami():
    j = _call("auth.test")
    return f"{j.get('user')} in {j.get('team')}"


def channels():
    j = _call("users.conversations", types="public_channel,private_channel", exclude_archived="true", limit=200)
    return [{"id": c["id"], "name": c["name"]} for c in j.get("channels", [])]


def _channel(name):
    name = name.lstrip("#").lower()
    for c in channels():
        if c["name"].lower() == name or c["id"] == name:
            return c
    raise RuntimeError(f"The Jarvis bot isn't in a Slack channel called #{name}. Invite it there first.")


_names = {}


def _user(uid):
    if uid not in _names:
        try:
            u = _call("users.info", user=uid)["user"]
            _names[uid] = u.get("real_name") or u.get("name") or uid
        except RuntimeError:
            _names[uid] = uid
    return _names[uid]


def read(channel, limit=15):
    c = _channel(channel)
    msgs = _call("conversations.history", channel=c["id"], limit=limit).get("messages", [])
    return {"channel": c["name"], "messages": [{"author": _user(m["user"]) if m.get("user") else m.get("username", "bot"),
                                                "text": m.get("text", "")[:500]} for m in reversed(msgs)]}


def post(channel, text):
    c = _channel(channel)
    _call("chat.postMessage", http="POST", channel=c["id"], text=text[:3500])
    return f"Posted in #{c['name']} on Slack."
