"""Smart home through Home Assistant's official REST API (your own Home Assistant server).

Needs the server address (e.g. http://homeassistant.local:8123) and a long-lived access token
(Home Assistant -> your profile -> Security -> Long-lived access tokens). Only lights, switches, fans,
covers, climate, media players, scenes and scripts are controlled; locks and alarms are left out."""
import re

import httpx

from ..config import get_secret, settings

DOMAINS = ("light", "switch", "fan", "cover", "climate", "media_player", "scene", "script", "input_boolean")


def connected():
    return bool(settings.get("home_enabled") and settings.get("home_url") and get_secret("home_token"))


def _req(method, path, **kw):
    url, token = settings.get("home_url", "").rstrip("/"), get_secret("home_token")
    if not url or not token:
        raise RuntimeError("Home Assistant isn't connected. Add its address and a token under Connections.")
    r = httpx.request(method, url + "/api" + path, headers={"Authorization": f"Bearer {token}"}, timeout=15, **kw)
    if r.status_code >= 400:
        raise RuntimeError(f"Home Assistant error {r.status_code}: {r.text[:150]}")
    return r.json() if r.content else {}


def whoami():
    _req("GET", "/")
    cfg = _req("GET", "/config")
    return cfg.get("location_name") or "Home Assistant"


def devices():
    out = []
    for s in _req("GET", "/states"):
        domain = s["entity_id"].split(".")[0]
        if domain in DOMAINS:
            out.append({"entity": s["entity_id"], "name": s["attributes"].get("friendly_name", s["entity_id"]),
                        "state": s["state"]})
    return out


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", s.lower().replace("_", " ")).replace("the ", "").strip()


def find(name):
    want = _norm(name)
    devs = devices()
    for d in devs:
        if _norm(d["name"]) == want or d["entity"] == name:
            return d
    # "bedroom light" matches "Bedroom Ceiling Light" when it's the only device with all those words
    words = set(want.split()) - {"my"}
    hits = [d for d in devs if words and words <= set(_norm(d["name"]).split())]
    return hits[0] if len(hits) == 1 else None


def control(name, action, value=None):
    d = find(name)
    if not d:
        raise RuntimeError(f"I couldn't find a device called {name} in Home Assistant.")
    domain = d["entity"].split(".")[0]
    data = {"entity_id": d["entity"]}
    action = action.lower().strip()
    if domain in ("scene", "script"):
        service = "turn_on"
    elif action in ("on", "turn on", "open", "start"):
        service = "open_cover" if domain == "cover" else "turn_on"
    elif action in ("off", "turn off", "close", "stop"):
        service = "close_cover" if domain == "cover" else "turn_off"
    elif action == "toggle":
        service = "toggle"
    elif action in ("brightness", "dim") and domain == "light":
        service, data["brightness_pct"] = "turn_on", max(1, min(100, int(value or 50)))
    elif action in ("temperature", "set temperature") and domain == "climate":
        service, data["temperature"] = "set_temperature", float(value)
    else:
        raise RuntimeError(f"I can't {action} the {d['name']}.")
    _req("POST", f"/services/{domain}/{service}", json=data)
    verb = {"turn_on": "on", "turn_off": "off", "toggle": "toggled", "open_cover": "opening", "close_cover": "closing",
            "set_temperature": f"set to {value} degrees"}.get(service, "done")
    if "brightness_pct" in data:
        verb = f"at {data['brightness_pct']}%"
    return f"{d['name']} {verb}." if domain not in ("scene", "script") else f"Running {d['name']}."
