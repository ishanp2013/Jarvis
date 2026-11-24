"""Plain AI requests for background work (no tools, no chat history), plus the daily AI budget.

Free AI plans have a daily request limit (OpenRouter's free models: about 50 a day, reset at midnight UTC).
Every request Jarvis makes to an online model is counted here. Your own chat is never blocked; the
background agent stops at its share (Settings -> Agent) and always leaves room for you."""
import datetime as dt
import json
import re
import threading
import time

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
    if data.get("day") != _day():
        data = {"day": _day(), "chat": 0, "agent": 0, "exhausted": False, "agents": {}}
    data.setdefault("down", {})       # provider -> unix time it may be tried again
    data.setdefault("providers", {})  # provider -> requests today
    return data


def _write(d):
    USAGE_FILE.write_text(json.dumps(d), encoding="utf-8")


def _all_down(d):
    """True when every provider in the chain is resting (no backup left)."""
    chain = providers.chain()
    now = time.time()
    return bool(chain) and all(d["down"].get(n, 0) > now for n in chain)


def usage():
    with _lock:
        d = _read()
    limit = int(settings.get("ai_daily_limit") or 50)
    return {"chat": d["chat"], "agent": d["agent"], "total": d["chat"] + d["agent"], "limit": limit,
            "agent_budget": int(settings.get("agent_daily_budget") or 25),
            "exhausted": _all_down(d) if providers.chain() else d["exhausted"],
            "by_agent": dict(d.get("agents") or {}), "by_provider": dict(d["providers"]),
            "resting": {n: int(t) for n, t in d["down"].items() if t > time.time()}, "active": active()}


def count(kind="chat", agent=None):
    """Counts one request: as your chat or background work, and under the team member who made it."""
    if not providers.is_cloud():
        return  # a model on this PC has no daily limit
    with _lock:
        d = _read()
        d[kind] = d.get(kind, 0) + 1
        who = agent or ("jarvis" if kind == "chat" else "scholar")
        agents = d.setdefault("agents", {})  # usage files from before the team have no per-agent counts yet
        agents[who] = agents.get(who, 0) + 1
        pn = providers.name()
        d["providers"][pn] = d["providers"].get(pn, 0) + 1
        _write(d)


def _midnight_utc():
    now = dt.datetime.now(dt.timezone.utc)
    return (now + dt.timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0).timestamp()


def mark_exhausted(provider_name=None, seconds=None):
    """A provider hit its limit: rest it until midnight UTC (when free plans reset), or for `seconds`."""
    with _lock:
        d = _read()
        d["down"][provider_name or providers.name()] = time.time() + seconds if seconds else _midnight_utc()
        d["exhausted"] = _all_down(d)
        _write(d)


def is_down(provider_name):
    with _lock:
        return _read()["down"].get(provider_name, 0) > time.time()


def order():
    """Providers to try for the next request: the chain minus the resting ones (the main one if all rest)."""
    chain = providers.chain()
    up = [n for n in chain if not is_down(n)]
    return up or chain[:1] or [settings.get("llm_provider")]


def active():
    """The provider the next request goes to."""
    return order()[0]


def failure_kind(err):
    """Why a request failed, as far as switching to a backup goes: "daily" (limit for today), "limit" (too many
    requests just now), "credit", "key", "model", "network", or None (anything else: no switching)."""
    msg = str(err)
    low = msg.lower()
    if "429" in msg or "resource_exhausted" in low or "rate limit" in low or "rate-limit" in low or "too many requests" in low:
        return "daily" if ("per-day" in low or "daily" in low or "per day" in low or "free-models-per-day" in low) else "limit"
    if "402" in msg or "credit" in low or "insufficient" in low or "quota" in low:
        return "credit"
    if "api key" in low or "401" in msg or "403" in msg or "permission_denied" in low or "authentication" in low             or "unauthorized" in low:
        return "key"
    if "404" in msg and "model" in low:
        return "model"
    if isinstance(err, (httpx.ConnectError, httpx.TimeoutException)) or "getaddrinfo" in low or "couldn't reach" in low:
        return "network"
    return None


# How long a provider rests after each kind of failure (None = until midnight UTC).
REST = {"daily": None, "limit": 90, "credit": 6 * 3600, "key": 1800, "model": 1800, "network": 60}


def rest(provider_name, kind):
    if kind in REST:
        mark_exhausted(provider_name, REST[kind])


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
def complete(system, prompt, kind="agent", max_tokens=6000, agent=None):
    """Send one request to the chosen AI model and return its text. Raises OutOfBudget when the agent's
    share is used up, or RuntimeError with a readable message on any other failure. `agent` is the team
    member asking (scholar, forge...), for the per-agent count."""
    if not providers.chain():
        raise RuntimeError("No AI model is set up. Add one in Settings.")
    if kind == "agent" and not agent_may_use():
        raise OutOfBudget("The agent's share of today's free AI requests is used up; it continues after midnight UTC.")
    names = order()
    for i, n in enumerate(names):
        with providers.use(n):
            try:
                return _complete_one(system, prompt, kind, max_tokens, agent)
            except Exception as e:
                why = failure_kind(e)
                if why is None:
                    raise
                rest(n, why)
                if i == len(names) - 1:
                    if why in ("daily", "limit"):
                        raise OutOfBudget("Every AI model you've set up has reached its limit; the agent waits until "
                                          "one resets.") from e
                    raise


def _complete_one(system, prompt, kind, max_tokens, agent):
    p = providers.current()
    count(kind, agent)
    try:
        if p["kind"] == "anthropic":
            import anthropic
            model = providers.model(providers.current())
            extra = {"output_config": {"effort": settings["anthropic_effort"]}} \
                if re.match(r"claude-(?:opus|sonnet|haiku|fable)-5|claude-opus-4-[5-8]|claude-sonnet-4-6", model) else {}
            client = anthropic.Anthropic(api_key=providers.key(providers.current()), timeout=300)
            with client.messages.stream(model=model, max_tokens=max_tokens, system=system,
                                        messages=[{"role": "user", "content": prompt}], **extra) as s:
                resp = s.get_final_message()
            if resp.stop_reason == "refusal":
                raise RuntimeError("The AI declined this request.")
            return "".join(b.text for b in resp.content if b.type == "text")
        if p["kind"] == "gemini":
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=providers.key(providers.current()))
            resp = client.models.generate_content(model=providers.model(providers.current()), contents=prompt,
                                                  config=types.GenerateContentConfig(system_instruction=system, temperature=0.3))
            return resp.text or ""
        if p["kind"] == "ollama":
            r = httpx.post(settings["ollama_url"] + "/api/chat", timeout=600, json={
                "model": providers.model(providers.current()), "stream": False,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
            r.raise_for_status()
            return r.json()["message"].get("content", "")
        headers = {"Content-Type": "application/json", "X-Title": "Jarvis"}
        if key := providers.key(p):
            headers["Authorization"] = f"Bearer {key}"
        r = httpx.post(providers.base_url(p) + "/chat/completions", headers=headers, timeout=300, json={
            "model": providers.model(p), "temperature": 0.3, "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        if r.status_code == 429:
            raise RuntimeError(f"{p['label']}'s limit has been reached (429): {r.text[:200]}")
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
