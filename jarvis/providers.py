"""The AI models Jarvis can talk to. Pick one in Settings → AI model and paste its API key.

API keys are separate from chat subscriptions: a ChatGPT Plus or Claude Pro plan does not include API
use, and most APIs bill per use. Free options: Gemini's free tier, Groq's, OpenRouter's, BazaarLink's and
OrcaRouter's free models, Mistral's free tier, and Ollama or LM Studio running on your own PC.

Backups: up to three more providers, in order. When one hits its limit (or runs out of credit, or its key
is rejected), Jarvis carries on with the next. The conversation lives in Jarvis's own database, so every
model gets the same chat history and memories."""
import contextlib
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
    _p["name"] = _n
API_KEYS = tuple(p["key"] for p in PROVIDERS.values() if "key" in p)
BACKUP_SETTINGS = ("llm_backup_1", "llm_backup_2", "llm_backup_3")

_local = threading.local()


def name():
    """The provider this request is using: a backup while one is standing in, otherwise the main choice."""
    return getattr(_local, "name", None) or settings.get("llm_provider")


@contextlib.contextmanager
def use(provider_name):
    """Run the requests inside this block (on this thread) with another provider."""
    prev = getattr(_local, "name", None)
    _local.name = provider_name
    try:
        yield PROVIDERS.get(provider_name)
    finally:
        _local.name = prev


def current():
    return PROVIDERS.get(name())


def available(provider_name=None):
    return ready(provider_name or name())


def ready(provider_name):
    """Whether a provider is set up: it runs on this PC, or has its key (or needs none)."""
    p = PROVIDERS.get(provider_name)
    if not p:
        return False
    return bool(p.get("local") or p.get("key_optional") and bool(base_url(p)) or get_secret(p["key"]))


def chain():
    """The main provider, then the backups, in order: only ones that are set up, each once."""
    out = []
    for n in [settings.get("llm_provider")] + [settings.get(k) for k in BACKUP_SETTINGS]:
        if n in PROVIDERS and n not in out and ready(n):
            out.append(n)
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
    return settings.get(p["model"])
