"""The AI models Jarvis can talk to. Pick one in Settings → AI model and paste its API key.

API keys are separate from chat subscriptions: a ChatGPT Plus or Claude Pro plan does not include API
use, and most APIs bill per use. Free options: Gemini's free tier, Groq's and OpenRouter's free models,
Mistral's free tier, and Ollama or LM Studio running on your own PC."""
from .config import get_secret, settings

# kind: how to talk to it. "openai" = the OpenAI chat-completions format, which most providers accept.
PROVIDERS = {
    "gemini":     {"label": "Google Gemini", "kind": "gemini", "key": "gemini_api_key", "model": "gemini_model"},
    "anthropic":  {"label": "Anthropic Claude", "kind": "anthropic", "key": "anthropic_api_key", "model": "anthropic_model"},
    "openai":     {"label": "OpenAI ChatGPT", "kind": "openai", "key": "openai_api_key", "model": "openai_model",
                   "url": "https://api.openai.com/v1"},
    "openrouter": {"label": "OpenRouter (hundreds of models)", "kind": "openai", "key": "openrouter_api_key",
                   "model": "openrouter_model", "url": "https://openrouter.ai/api/v1"},
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
API_KEYS = tuple(p["key"] for p in PROVIDERS.values() if "key" in p)


def current():
    return PROVIDERS.get(settings.get("llm_provider"))


def available():
    p = current()
    if not p:
        return False
    return p.get("local") or p.get("key_optional") and bool(base_url(p)) or bool(get_secret(p["key"]))


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
