"""Plain AI requests for background work (no tools, no chat history), plus the daily AI budget.

Free AI plans have a daily request limit (OpenRouter's free models: about 50 a day, reset at midnight UTC).
Every request Jarvis makes to an online model is counted here. Your own chat is never blocked; the
background agent stops at its share (Settings -> Agent) and always leaves room for you."""
import datetime as dt
import json
import re
import threading

import httpx

from . import providers
from .config import HOME, get_secret, settings

USAGE_FILE = HOME / "ai_usage.json"
_lock = threading.Lock()


class OutOfBudget(RuntimeError):
    pass


# ------------------------------------------------------------------ budget
def _day():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")  # free plans reset at midnight UTC


def _read():
    try:
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if data.get("day") == _day() else {"day": _day(), "chat": 0, "agent": 0, "exhausted": False}


def usage():
    with _lock:
        d = _read()
    limit = int(settings.get("ai_daily_limit") or 50)
    return {"chat": d["chat"], "agent": d["agent"], "total": d["chat"] + d["agent"], "limit": limit,
            "agent_budget": int(settings.get("agent_daily_budget") or 25), "exhausted": d["exhausted"]}


def count(kind="chat"):
    if not providers.is_cloud():
        return  # a model on this PC has no daily limit
    with _lock:
        d = _read()
        d[kind] = d.get(kind, 0) + 1
        USAGE_FILE.write_text(json.dumps(d), encoding="utf-8")


def mark_exhausted():
    with _lock:
        d = _read()
        d["exhausted"] = True
        USAGE_FILE.write_text(json.dumps(d), encoding="utf-8")


def agent_may_use(n=1):
    """Whether the background agent may make n more requests today."""
    if not providers.available():
        return False
    if not providers.is_cloud():
        return True
    u = usage()
    reserve = int(settings.get("ai_chat_reserve") or 15)
    return not u["exhausted"] and u["agent"] + n <= u["agent_budget"] and u["total"] + n <= u["limit"] - reserve


# ------------------------------------------------------------------ one-shot requests
def complete(system, prompt, kind="agent", max_tokens=6000):
    """Send one request to the chosen AI model and return its text. Raises OutOfBudget when the agent's
    share is used up, or RuntimeError with a readable message on any other failure."""
    p = providers.current()
    if not p or not providers.available():
        raise RuntimeError("No AI model is set up. Add one in Settings.")
    if kind == "agent" and not agent_may_use():
        raise OutOfBudget("The agent's share of today's free AI requests is used up; it continues after midnight UTC.")
    count(kind)
    try:
        if p["kind"] == "anthropic":
            import anthropic
            model = settings["anthropic_model"]
            extra = {"output_config": {"effort": settings["anthropic_effort"]}} \
                if re.match(r"claude-(?:opus|sonnet|haiku|fable)-5|claude-opus-4-[5-8]|claude-sonnet-4-6", model) else {}
            client = anthropic.Anthropic(api_key=get_secret("anthropic_api_key"), timeout=300)
            with client.messages.stream(model=model, max_tokens=max_tokens, system=system,
                                        messages=[{"role": "user", "content": prompt}], **extra) as s:
                resp = s.get_final_message()
            if resp.stop_reason == "refusal":
                raise RuntimeError("The AI declined this request.")
            return "".join(b.text for b in resp.content if b.type == "text")
        if p["kind"] == "gemini":
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=get_secret("gemini_api_key"))
            resp = client.models.generate_content(model=settings["gemini_model"], contents=prompt,
                                                  config=types.GenerateContentConfig(system_instruction=system, temperature=0.3))
            return resp.text or ""
        if p["kind"] == "ollama":
            r = httpx.post(settings["ollama_url"] + "/api/chat", timeout=600, json={
                "model": settings["ollama_model"], "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["message"].get("content", "")
        headers = {"Content-Type": "application/json", "X-Title": "Jarvis"}
        if key := get_secret(p["key"]):
            headers["Authorization"] = f"Bearer {key}"
        r = httpx.post(providers.base_url(p) + "/chat/completions", headers=headers, timeout=300, json={
            "model": providers.model(p), "temperature": 0.3, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        if r.status_code == 429:
            mark_exhausted()
            raise OutOfBudget("The AI service's free daily limit has been reached; the agent waits until it resets.")
        if r.status_code >= 400:
            raise RuntimeError(f"AI request failed ({r.status_code}): {r.text[:200]}")
        return r.json()["choices"][0]["message"].get("content") or ""
    except httpx.HTTPError as e:
        raise RuntimeError(f"Couldn't reach the AI service: {e}") from e


def parse_json(text):
    """The first JSON object or array in an AI reply (models sometimes wrap it in prose or ``` fences)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    if not starts:
        raise ValueError("no JSON in the reply")
    start = min(starts)
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return _loads(text[start:i + 1])
    raise ValueError("the JSON in the reply was cut off")


def _loads(s):
    """json.loads, forgiving the slips models often make: line breaks inside strings, trailing commas."""
    try:
        return json.loads(s, strict=False)
    except ValueError:
        return json.loads(re.sub(r",\s*([\]}])", r"\1", s), strict=False)
