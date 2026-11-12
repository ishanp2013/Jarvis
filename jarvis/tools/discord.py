"""Discord through an official bot account (REST API only, no always-on gateway connection).

The bot can read only the server channels it has been invited to and given access to. It cannot
read your personal DMs. Using your own user token (a "self-bot") breaks Discord's terms, so this
module only ever uses a bot token.
"""
import httpx

from ..config import get_secret, settings

API = "https://discord.com/api/v10"


def _headers():
    token = get_secret("discord_bot_token")
    if not token:
        raise RuntimeError("Discord isn't connected. Add a bot token in Integrations.")
    return {"Authorization": f"Bot {token}", "User-Agent": "JarvisAssistant (personal, 1.0)"}


def _get(path, **params):
    r = httpx.get(API + path, headers=_headers(), params=params, timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(f"Discord error {r.status_code}: {r.json().get('message', r.text[:100])}")
    return r.json()


def connected():
    return settings["discord_enabled"] and bool(get_secret("discord_bot_token"))


def whoami():
    return _get("/users/@me")["username"]


def list_channels():
    """Text channels in every server the bot is in (for the channel picker)."""
    out = []
    for g in _get("/users/@me/guilds"):
        for c in _get(f"/guilds/{g['id']}/channels"):
            if c.get("type") in (0, 5):  # text, announcement
                out.append({"id": c["id"], "name": c["name"], "guild": g["name"]})
    return out


def _channel(name_or_id):
    chosen = settings["discord_channels"] or []
    key = str(name_or_id).lower().lstrip("#")
    for c in chosen:
        if key in (c["id"], c["name"].lower()):
            return c
    if not chosen:
        raise RuntimeError("No Discord channels selected yet. Pick channels in Integrations.")
    raise RuntimeError(f"#{key} isn't one of your selected channels.")


def read_channel(name_or_id, limit=20):
    c = _channel(name_or_id)
    msgs = _get(f"/channels/{c['id']}/messages", limit=min(limit, 50))
    rows = [{"author": m["author"].get("global_name") or m["author"]["username"], "time": m["timestamp"][:16],
             "text": m.get("content") or "[embed/attachment]"} for m in reversed(msgs)]
    return {"channel": c["name"], "messages": rows}


def selected_channels():
    return [c["name"] for c in settings["discord_channels"] or []]


def send(name_or_id, text):
    c = _channel(name_or_id)
    r = httpx.post(f"{API}/channels/{c['id']}/messages", headers=_headers(), json={"content": text[:2000]}, timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(f"Discord error {r.status_code}: {r.json().get('message', '')}")
    return f"Posted in #{c['name']}."
