"""Notion through its official API with your own internal integration token (Connections -> Notion).

Notion only shows an integration the pages you share with it (page menu -> Connections -> add your
integration), so Jarvis can't see anything else in your workspace. Token kept in Credential Manager."""
import re

import httpx

from ..config import get_secret, settings

API = "https://api.notion.com/v1"


def connected():
    return bool(settings.get("notion_enabled") and get_secret("notion_token"))


def _req(method, path, **kw):
    token = get_secret("notion_token")
    if not token:
        raise RuntimeError("Notion isn't connected. Add an integration token under Connections.")
    r = httpx.request(method, API + path, timeout=20, headers={
        "Authorization": f"Bearer {token}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}, **kw)
    if r.status_code >= 400:
        try:
            msg = r.json().get("message", "")
        except ValueError:
            msg = r.text[:150]
        raise RuntimeError(f"Notion error {r.status_code}: {msg}")
    return r.json()


def whoami():
    me = _req("GET", "/users/me")
    return me.get("name") or me.get("bot", {}).get("workspace_name") or "Notion integration"


def _title(obj):
    props = obj.get("properties", {})
    for p in props.values():
        if p.get("type") == "title" and p.get("title"):
            return "".join(t.get("plain_text", "") for t in p["title"])
    if obj.get("title"):  # databases
        return "".join(t.get("plain_text", "") for t in obj["title"])
    return "Untitled"


def search(query="", limit=10):
    res = _req("POST", "/search", json={"query": query, "page_size": limit,
                                         "sort": {"direction": "descending", "timestamp": "last_edited_time"}})
    return [{"id": o["id"], "type": o["object"], "title": _title(o), "url": o.get("url", ""),
             "edited": o.get("last_edited_time", "")[:10]} for o in res.get("results", [])]


def _text(block):
    b = block.get(block.get("type"), {})
    txt = "".join(t.get("plain_text", "") for t in b.get("rich_text", []))
    kind = block.get("type")
    if kind == "to_do":
        return ("[x] " if b.get("checked") else "[ ] ") + txt
    if kind in ("bulleted_list_item", "numbered_list_item"):
        return "- " + txt
    if kind and kind.startswith("heading"):
        return "## " + txt
    return txt


def read_page(page_id, max_chars=6000):
    page = _req("GET", f"/pages/{page_id}")
    blocks = _req("GET", f"/blocks/{page_id}/children", params={"page_size": 100}).get("results", [])
    body = "\n".join(t for t in (_text(b) for b in blocks) if t)
    return {"title": _title(page), "url": page.get("url", ""), "text": body[:max_chars]}


def _para(text):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:1900]}}]}}


def add_note(text, title=""):
    """Appends to the page named in Settings (or the most recently edited shared page). With a title,
    creates a new sub-page there instead."""
    parent = settings.get("notion_page_id", "").strip()
    if found := re.search(r"[0-9a-f]{32}|[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}", parent.lower()):
        parent = found.group(0)  # accepts a pasted page link as well as a bare ID
    if not parent:
        pages = [p for p in search("", 20) if p["type"] == "page"]
        if not pages:
            raise RuntimeError("Share at least one Notion page with your Jarvis integration first.")
        parent = pages[0]["id"]
    if title:
        page = _req("POST", "/pages", json={"parent": {"page_id": parent},
                                            "properties": {"title": {"title": [{"text": {"content": title[:200]}}]}},
                                            "children": [_para(p) for p in text.split("\n\n") if p.strip()][:50]})
        return f"Created the Notion page \"{title}\"."
    _req("PATCH", f"/blocks/{parent}/children", json={"children": [_para(text)]})
    return "Added that to Notion."
