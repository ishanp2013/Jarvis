"""The AI models Jarvis can talk to. Pick one in Settings → AI model and paste its API key.

API keys are separate from chat subscriptions: a ChatGPT Plus or Claude Pro plan does not include API
use, and most APIs bill per use. Free options: Gemini's free tier, Groq's, OpenRouter's, BazaarLink's and
OrcaRouter's free models, Mistral's free tier, and Ollama or LM Studio running on your own PC.

Backups: as many as you like, in order, each with its own key and model. When one hits its limit (or runs out of credit, or its key
is rejected), Jarvis carries on with the next. The conversation lives in Jarvis's own database, so every
model gets the same chat history and memories."""
import contextlib
import re
import threading

from .config import get_secret, settings

# kind: how to talk to it. "openai" = the OpenAI chat-completions format, which most providers accept.
PROVIDERS = {
    "gemini":     {"label": "Google Gemini", "kind": "gemini", "key": "gemini_api_key", "model": "gemini_model"},
    "anthropic":  {"label": "Anthropic Claude", "kind": "anthropic", "key": "anthropic_api_key", "model": "anthropic_model"},
    "openai":     {"label": "OpenAI ChatGPT", "kind": "openai", "key": "openai_api_key", "model": "openai_model",
                   "url": "https://api.openai.com/v1"},
    "openrouter": {"label": "OpenRouter", "kind": "openai", "key": "openrouter_api_key",
                   "model": "openrouter_model", "url": "https://openrouter.ai/api/v1"},
    "bazaarlink": {"label": "BazaarLink", "kind": "openai", "key": "bazaarlink_api_key",
                   "model": "bazaarlink_model", "url": "https://api.bazaarlink.ai/v1"},
    "orcarouter": {"label": "OrcaRouter", "kind": "openai", "key": "orcarouter_api_key",
                   "model": "orcarouter_model", "url": "https://api.orcarouter.ai/v1"},
    "groq":       {"label": "Groq", "kind": "openai", "key": "groq_api_key", "model": "groq_model",
                   "url": "https://api.groq.com/openai/v1"},
    "mistral":    {"label": "Mistral", "kind": "openai", "key": "mistral_api_key", "model": "mistral_model",
                   "url": "https://api.mistral.ai/v1"},
    "deepseek":   {"label": "DeepSeek", "kind": "openai", "key": "deepseek_api_key", "model": "deepseek_model",
                   "url": "https://api.deepseek.com/v1"},
    "xai":        {"label": "xAI Grok", "kind": "openai", "key": "xai_api_key", "model": "xai_model", "url": "https://api.x.ai/v1"},
    "ollama":     {"label": "Ollama (on this PC)", "kind": "ollama", "model": "ollama_model", "local": True},
    "custom":     {"label": "Other OpenAI-compatible (LM Studio, …)", "kind": "openai", "key": "custom_api_key",
                   "model": "custom_model", "url_setting": "custom_url", "key_optional": True},
}
for _n, _p in PROVIDERS.items():
    _p["name"] = _p["provider"] = _n
API_KEYS = tuple(p["key"] for p in PROVIDERS.values() if "key" in p)
BACKUP_KEY = re.compile(r"^backup_[a-z0-9]{4,16}_api_key$")  # each backup's own key in Credential Manager

_local = threading.local()


def backups():
    """The backups from Settings, in order: [{"id", "provider", "model"}]. Older settings had three fixed slots."""
    items = settings.get("llm_backups")
    if items is None:
        items = [{"id": f"old{i}", "provider": settings.get(k), "model": ""}
                 for i, k in enumerate(("llm_backup_1", "llm_backup_2", "llm_backup_3"), 1) if settings.get(k)]
    return [b for b in (items or []) if isinstance(b, dict) and b.get("provider") in PROVIDERS and b.get("id")]


def own_key_name(backup_id):
    return f"backup_{backup_id}_api_key"


def resolve(slot):
    """A provider by slot: the main choice ("openrouter") or a backup ("backup:<id>"), with that backup's own key
    (or the provider's usual key if it has none) and model (or the provider's usual model)."""
    if not slot or not slot.startswith("backup:"):
        return PROVIDERS.get(slot)
    bid = slot.split(":", 1)[1]
    items = backups()
    for i, b in enumerate(items, 1):
        if b["id"] == bid:
            p = dict(PROVIDERS[b["provider"]])
            own = own_key_name(bid)
            if "key" in p and get_secret(own):
                p["key"] = own
            p.update(name=slot, label=f"{p['label']} (backup {i})", model_value=(b.get("model") or "").strip())
            return p
    return None


def name():
    """The slot this request is using: a backup while one is standing in, otherwise the main choice."""
    return getattr(_local, "name", None) or settings.get("llm_provider")


@contextlib.contextmanager
def use(slot):
    """Run the requests inside this block (on this thread) with another provider."""
    prev = getattr(_local, "name", None)
    _local.name = slot
    try:
        yield resolve(slot)
    finally:
        _local.name = prev


def current():
    return resolve(name())


def label(slot):
    p = resolve(slot)
    return p["label"] if p else str(slot)


def available(provider_name=None):
    return ready(provider_name or name())


def ready(slot):
    """Whether a provider is set up: it runs on this PC, or has its key (or needs none)."""
    p = resolve(slot)
    if not p:
        return False
    return bool(p.get("local") or p.get("key_optional") and bool(base_url(p)) or key(p))


def key(p):
    return get_secret(p["key"]) if p and "key" in p else ""


def chain():
    """The main provider, then the backups, in order: only ones that are set up. A backup that is exactly the
    same as one before it (same service, key and model) is skipped."""
    out, seen = [], set()
    for slot in [settings.get("llm_provider")] + [f"backup:{b['id']}" for b in backups()]:
        p = resolve(slot)
        if not p or not ready(slot):
            continue
        sig = (p["provider"], p.get("key"), model(p))
        if sig not in seen:
            seen.add(sig)
            out.append(slot)
    return out


def is_cloud():
    """True when requests leave this PC (private mode then keeps personal data away from the AI)."""
    p = current()
    if not p or p.get("local"):
        return False
    url = base_url(p)
    return not url.startswith(("http://127.", "http://localhost", "http://[::1]"))


def base_url(p):
    return (settings.get(p["url_setting"], "") if "url_setting" in p else p.get("url", "")).rstrip("/")


def model(p):
    return (p.get("model_value") if p else "") or (settings.get(p["model"]) if p else "")
