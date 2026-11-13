"""Settings (plain JSON) and secrets (Windows Credential Manager via keyring)."""
import json
import os
import threading
from pathlib import Path

import keyring

APP_NAME = "JarvisAssistant"
HOME = Path(os.environ.get("LOCALAPPDATA", Path.home())) / APP_NAME
HOME.mkdir(parents=True, exist_ok=True)
SETTINGS_FILE = HOME / "settings.json"

SECRET_KEYS = ("gemini_api_key", "anthropic_api_key", "openai_api_key", "openrouter_api_key", "groq_api_key",
               "mistral_api_key", "deepseek_api_key", "xai_api_key", "custom_api_key",
               "elevenlabs_api_key", "discord_bot_token", "google_client_secret", "github_token",
               "notion_token", "slack_bot_token", "telegram_bot_token", "home_token")

DEFAULTS = {
    "assistant_name": "Jarvis",
    "user_name": "",
    "honorific": "sir",              # added to the end of every reply; empty = off
    "confirm_close": False,          # ask before closing apps
    "confirm_sends": False,          # ask before sending messages/emails the user asked for
    "routines": {},                # "focus mode": ["close discord", "open notepad"]
    # voice input
    "mic_enabled": True,
    "wake_word_enabled": True,
    "wake_threshold": 0.5,
    "wake_model": "hey_jarvis",      # hey_jarvis | alexa | hey_mycroft | hey_rhasspy | path to your own .onnx model
    "wake_phrase_label": "",         # what to call a custom wake word on screen, e.g. "Hey Friday"
    "stt_model": "base.en",          # tiny.en is faster, small.en more accurate
    "follow_up_seconds": 6,          # keep listening after a reply without the wake word
    "silence_end_ms": 900,
    # voice output
    "tts_provider": "edge",          # edge | elevenlabs | windows
    "edge_voice": "en-GB-RyanNeural",
    "edge_rate": "-5%",
    "edge_pitch": "-8Hz",
    "elevenlabs_voice_id": "",
    "elevenlabs_model": "eleven_flash_v2_5",
    "elevenlabs_stability": 0.55,
    "elevenlabs_similarity": 0.75,
    "elevenlabs_style": 0.1,
    "tts_volume": 1.0,
    # brain
    "llm_provider": "gemini",        # a key of providers.PROVIDERS, or "off"
    "gemini_model": "gemini-2.5-flash-lite",
    "anthropic_model": "claude-opus-5-5",
    "anthropic_effort": "low",       # low = quickest replies; medium/high think harder
    "openai_model": "gpt-5-mini",
    "openrouter_model": "openrouter/auto",
    "groq_model": "llama-3.3-70b-versatile",
    "mistral_model": "mistral-small-latest",
    "deepseek_model": "deepseek-chat",
    "xai_model": "grok-4",
    "custom_model": "",
    "custom_url": "http://127.0.0.1:1234/v1",
    "ollama_model": "qwen2.5:3b",
    "ollama_url": "http://127.0.0.1:11434",
    "history_turns": 8,
    "stream_replies": True,          # start speaking while the AI is still writing its answer
    "vision_model": "",              # model for "what's on my screen"; empty = the chat model (OpenRouter picks a free one)
    # background agent
    "agent_enabled": True,
    "agent_interval_min": 45,        # how often it checks Classroom, Gmail and phone notifications
    "agent_school_senders": "",      # one per line: teacher emails, @school-domain, WhatsApp group names
    "agent_daily_budget": 25,        # AI requests per day the agent may use
    "ai_daily_limit": 50,            # your AI plan's daily request limit (OpenRouter free: about 50)
    "ai_chat_reserve": 15,           # requests always kept for your own chat
    "agent_last_run": 0,
    "agent_auto_prepare": True,      # prepare drafts of new assignments (presentations, documents, notes) by itself
    "agent_output_dir": "",          # where prepared work is saved; empty = Documents\School Projects
    "classroom_enabled": False,
    # welcome-back briefing
    "briefing_enabled": True,        # brief me when I come back to the laptop
    "briefing_away_min": 30,         # how long away counts as "away"
    "briefing_speak": True,          # say it out loud (otherwise just show it)
    "last_briefing": 0,
    "quiet_hours": "22-7",           # no spoken reminders between these hours
    # background core and remote access
    "port": 8765,                    # local server for the dashboard, the orb and the phone
    "keep_awake_on_ac": True,        # stop idle sleep while plugged in, so background work and the phone keep working
    "remote_host": "",               # this laptop's Tailscale name, e.g. laptop.tail1234.ts.net (filled in automatically)
    # desktop extras
    "game_mode_auto": True,          # pause wake-word listening while a game is in the foreground
    "overlay_enabled": False,        # small always-on-top orb
    "private_mode": True,            # never send mail/calendar/tasks/Discord content to a cloud AI
    # desktop
    "browser_path": str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Opera GX" / "opera.exe"),
    # integrations (each must be enabled explicitly)
    "ms_client_id": "",
    "ms_enabled": False,
    "google_client_id": "",
    "google_enabled": False,
    "github_enabled": False,
    "weather_place": "",             # e.g. "Dubai"; empty = ask each time
    "outlook_classic_enabled": False,
    "discord_enabled": False,
    "discord_channels": [],          # [{"id": "...", "name": "announcements"}]
    "whatsapp_enabled": True,
    "whatsapp_contacts": {},         # {"Sam": "971500000000"}: stays on this PC
    "notion_enabled": False,
    "notion_page_id": "",            # page notes are added to; empty = most recently edited shared page
    "slack_enabled": False,
    "telegram_enabled": False,
    "telegram_chats": {},            # chats that have messaged the bot: {"Sam": 12345}
    "home_enabled": False,
    "home_url": "",                  # e.g. http://homeassistant.local:8123
}


class Settings:
    def __init__(self):
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        if SETTINGS_FILE.exists():
            try:
                self._data.update(json.loads(SETTINGS_FILE.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    def get(self, key, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def __getitem__(self, key):
        return self.get(key)

    def update(self, values: dict):
        with self._lock:
            for k, v in values.items():
                if k in DEFAULTS:
                    self._data[k] = v
            tmp = SETTINGS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            tmp.replace(SETTINGS_FILE)

    def public(self):
        return dict(self._data)


def get_secret(name: str) -> str:
    try:
        return keyring.get_password(APP_NAME, name) or ""
    except Exception:
        return ""


def set_secret(name: str, value: str):
    if name not in SECRET_KEYS:
        raise ValueError("unknown secret")
    if value:
        keyring.set_password(APP_NAME, name, value)
    else:
        try:
            keyring.delete_password(APP_NAME, name)
        except Exception:
            pass


def secret_status():
    return {k: bool(get_secret(k)) for k in SECRET_KEYS}


settings = Settings()
