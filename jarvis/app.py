"""Jarvis desktop app: wires the mic, brain, voice and dashboard together."""
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

import subprocess

import psutil
import webview

from . import config, providers, speech
from .brain import Brain
from .config import secret_status, settings
from .listener import Listener
from .storage import Store, setup_logging
from .tools import (discord, gamemode, games, github, google, home, microsoft, notion, outlook_classic, routines, slack,
                    telegram, whatsapp)
from .tools import windows as win

log = logging.getLogger("app")
ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui" / "index.html"
OVERLAY = ROOT / "ui" / "overlay.html"
OVERLAY_TITLE = "Jarvis Orb"
OVERLAY_SIZE = 200  # pywebview won't make a window narrower than 200
OVERLAY_EVENTS = {"state", "level", "voice_level", "mic", "game_mode", "wake"}

# Token-based connections: secret name, a check that returns who you're connected as, the on/off setting.
SERVICES = {
    "notion": ("notion_token", notion.whoami, "notion_enabled"),
    "slack": ("slack_bot_token", slack.whoami, "slack_enabled"),
    "telegram": ("telegram_bot_token", telegram.whoami, "telegram_enabled"),
    "home": ("home_token", home.whoami, "home_enabled"),
}


class Jarvis:
    def __init__(self):
        self.window = None
        self.on_event = None  # browser mode's event fan-out (web.py)
        self.store = Store()
        self.state = "starting"
        self.voice_turn = False
        self.listener = None
        self.stt = speech.STT()
        self.speaker = speech.Speaker(self._on_speaking, lambda m: self.emit("warning", {"text": m}),
                                      lambda v: self.emit("voice_level", {"rms": round(v, 3)}))
        self.brain = Brain(self.store, self.emit, self.speak, lambda: self.listener)
        self.brain.set_game_mode = lambda on: self.set_game_mode(on)
        self.ready = {"wake": False, "stt": False}
        self.game_mode, self._game_auto, self._game_off_checks, self._mic_before_game = False, False, 0, False
        self.overlay = None        # pywebview window (desktop mode) or subprocess (browser mode)
        self.api = None
        self.port = None           # browser mode's port

    # ---------- events to the UI
    def emit(self, kind, data=None):
        if kind == "state":
            self.state = data["state"]
        if kind == "activity":
            self.store.log("activity", data.get("text", ""))
        if self.on_event:
            self.on_event(kind, data)
        js = f"window.onJarvis && window.onJarvis({json.dumps(kind)}, {json.dumps(data, default=str)})"
        for w in (self.window, self.overlay if kind in OVERLAY_EVENTS and isinstance(self.overlay, webview.Window) else None):
            if w:
                try:
                    w.evaluate_js(js)
                except Exception:
                    pass

    # ---------- game mode: stop listening for the wake word while a game runs
    def set_game_mode(self, on, auto=False, game=""):
        if on == self.game_mode:
            self._game_auto = self._game_auto and auto
            return "Game mode is already " + ("on." if on else "off.")
        self.game_mode, self._game_auto, self._game_off_checks = on, auto and on, 0
        if on:
            self._mic_before_game = bool(self.listener and self.listener.stream)
            if self.listener:
                self.listener.stop()
        elif self._mic_before_game and settings["mic_enabled"] and self.listener:
            self.listener.start()
        self.emit("game_mode", {"on": on, "auto": auto, "game": game})
        self.store.log("settings", f"Game mode {'on' if on else 'off'}" + (f" ({game} detected)" if game else ""))
        if on:
            return ("Game mode on. I've stopped listening so your game runs smoothly. "
                    + ("I'll come back when you close it." if auto else "Type game mode off, or press the Game mode chip, to bring me back."))
        return "Game mode off. Listening again." if self._mic_before_game else "Game mode off."

    def _check_game(self):
        if not settings.get("game_mode_auto", True):
            return
        playing, name = gamemode.detect()
        if playing and not self.game_mode:
            self.set_game_mode(True, auto=True, game=name)
        elif not playing and self.game_mode and self._game_auto:
            self._game_off_checks += 1
            if self._game_off_checks >= 2:  # ~6 s outside the game, so a quick alt-tab doesn't wake the mic
                self.set_game_mode(False, auto=True)
        else:
            self._game_off_checks = 0

    # ---------- floating orb
    def show_overlay(self, on):
        if on == bool(self.overlay):
            return
        if not on:
            o, self.overlay = self.overlay, None
            try:
                o.destroy() if isinstance(o, webview.Window) else o.terminate()
            except Exception:
                pass
            return
        x, y = _overlay_corner()
        if self.window:  # desktop mode: a second window in this process
            self.overlay = webview.create_window(OVERLAY_TITLE, str(OVERLAY), js_api=self.api, width=OVERLAY_SIZE,
                                                 height=OVERLAY_SIZE, x=x, y=y, frameless=True, on_top=True,
                                                 transparent=True, easy_drag=True, resizable=False,
                                                 min_size=(OVERLAY_SIZE, OVERLAY_SIZE), background_color="#090603")
            self.overlay.events.shown += lambda: threading.Thread(target=_round_window, daemon=True).start()
        elif self.port:  # browser mode: a small helper process showing the same page from the local server
            self.overlay = subprocess.Popen([sys.executable, "-m", "jarvis", "--overlay", str(self.port), str(x), str(y),
                                             str(os.getpid())],
                                            cwd=str(ROOT), creationflags=subprocess.CREATE_NO_WINDOW)

    def show_dashboard(self):
        if self.window:
            try:
                self.window.restore()
                self.window.show()
            except Exception:
                pass
        elif self.port:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{self.port}/")

    # ---------- startup
    def boot(self):
        try:
            self.listener = Listener(speech.WakeWord(), self._on_utterance, self._on_wake, self.emit)
            self.ready["wake"] = True
            if settings["mic_enabled"]:
                self.listener.start()
        except Exception as e:
            log.exception("wake word init")
            self.emit("warning", {"text": f"Wake word unavailable: {e}"})
        if settings["tts_provider"] == "edge":  # first request pays a ~2 s connection setup; do it now
            threading.Thread(target=lambda: speech.synth_edge("Ready."), daemon=True).start()
        self.emit("state", {"state": "loading speech model"})
        try:
            self.stt.warm()
            self.ready["stt"] = True
        except Exception as e:
            log.exception("stt init")
            self.emit("warning", {"text": f"Speech recognition unavailable: {e}"})
        self.emit("state", {"state": "idle"})
        self.emit("ready", self.ready)
        if settings.get("overlay_enabled"):
            self.show_overlay(True)
        threading.Thread(target=self._monitor, daemon=True).start()

    def _monitor(self):
        me = psutil.Process(os.getpid())
        me.cpu_percent()
        while True:
            time.sleep(3)
            try:
                self._check_game()
            except Exception:
                log.exception("game check")
            try:
                rss = me.memory_info().rss + sum(c.memory_info().rss for c in me.children(recursive=True))
                vm = psutil.virtual_memory()
                self.emit("system", {"cpu": psutil.cpu_percent(), "ram": vm.percent,
                                     "jarvis_cpu": round(me.cpu_percent() / psutil.cpu_count(), 1),
                                     "jarvis_mb": round(rss / 2**20)})
            except psutil.Error:
                pass

    # ---------- voice flow
    def _on_wake(self):
        self.speaker.stop()
        self.brain.interrupt()
        speech.chime()
        self.emit("wake", {})

    def _on_utterance(self, audio):
        if not self.ready["stt"]:
            self.emit("warning", {"text": "Speech model still loading."})
            return
        self.emit("state", {"state": "transcribing"})
        t = time.time()
        text = self.stt.transcribe(audio)
        log.info("stt %.2fs: %r", time.time() - t, text[:80])
        if not text:
            self.emit("state", {"state": "idle"})
            return
        self.voice_turn = True
        self.brain.handle(text, "voice")

    def speak(self, text):
        if not text:
            return
        self.emit("state", {"state": "speaking"})
        self.speaker.say(text)

    def _on_speaking(self, speaking):
        if speaking:
            return
        self.emit("state", {"state": "idle"})
        # Continuous conversation: after answering a spoken request, listen briefly without the wake word.
        if self.voice_turn and self.listener and self.listener.stream and settings["follow_up_seconds"] > 0:
            time.sleep(0.25)  # let the speaker's tail die away so we don't hear ourselves
            self.listener.listen_now(window=float(settings["follow_up_seconds"]))
        self.voice_turn = False

    def stop_all(self):
        self.speaker.stop()
        self.brain.interrupt()
        if self.listener:
            self.listener.cancel_listen()
        self.voice_turn = False
        self.emit("state", {"state": "idle"})


class Api:
    """Methods callable from the dashboard (window.pywebview.api.*)."""

    def __init__(self, j: Jarvis):
        self._j = j

    def init(self):
        j = self._j
        return {"settings": settings.public(), "secrets": secret_status(), "state": j.state, "ready": j.ready,
                "mic": bool(j.listener and j.listener.stream), "history": j.store.recent_messages(40),
                "memories": j.store.memories(), "activity": j.store.activity(60),
                "pending": list(j.brain.pending.values()), "integrations": self.integrations()}

    def integrations(self):
        return {
            "microsoft": {"configured": bool(settings["ms_client_id"]), "connected": microsoft.connected()},
            "outlook_classic": {"available": outlook_classic.available(), "connected": outlook_classic.connected()},
            "discord": {"token": bool(config.get_secret("discord_bot_token")), "connected": discord.connected(),
                        "channels": settings["discord_channels"]},
            "whatsapp": {"connected": settings["whatsapp_enabled"]},
            "google": {"configured": bool(settings["google_client_id"] and config.get_secret("google_client_secret")),
                       "connected": google.connected()},
            "github": {"connected": github.connected()},
            "gemini": {"key": bool(config.get_secret("gemini_api_key"))},
            "ai": {"provider": settings["llm_provider"], "ready": providers.available()},
            "elevenlabs": {"key": bool(config.get_secret("elevenlabs_api_key"))},
            **{name: {"connected": bool(settings.get(flag) and config.get_secret(secret))}
               for name, (secret, _, flag) in SERVICES.items()},
            "games": {"count": len(games.installed())},
            "game_mode": {"on": self._j.game_mode},
            "overlay": {"on": bool(self._j.overlay)},
            "wake": {"model": settings.get("wake_model"), "phrase": speech.wake_phrase()},
        }

    # ---------- token connections (Notion, Slack, Telegram, Home Assistant)
    def connect_service(self, name, token=None, url=None):
        if name not in SERVICES:
            return {"ok": False, "error": "unknown service"}
        secret, check, flag = SERVICES[name]
        old_url = settings.get("home_url")
        if name == "home" and url:
            settings.update({"home_url": url.strip().rstrip("/")})
        try:
            who = self._try_token(secret, token, check)
            settings.update({flag: True})
            self._j.store.log("integration", f"{name.title()} connected")
            return {"ok": True, "who": who}
        except Exception as e:
            if name == "home" and url:
                settings.update({"home_url": old_url})
            return {"ok": False, "error": str(e)}

    def disconnect_service(self, name):
        if name in SERVICES:
            secret, _, flag = SERVICES[name]
            config.set_secret(secret, "")
            settings.update({flag: False})
            self._j.store.log("integration", f"{name.title()} disconnected")
        return self.integrations()

    # ---------- extras
    def game_mode(self, on):
        return self._j.set_game_mode(bool(on))

    def set_overlay(self, on):
        settings.update({"overlay_enabled": bool(on)})
        self._j.show_overlay(bool(on))
        return bool(self._j.overlay)

    def show_dashboard(self):
        self._j.show_dashboard()

    def set_wake_model(self, model, label=""):
        """Switch the wake word. model: a built-in name or the path to your own .onnx model."""
        model = (model or "hey_jarvis").strip().strip('"')
        try:
            ww = speech.WakeWord(model)
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}
        settings.update({"wake_model": model, "wake_phrase_label": label.strip()})
        j = self._j
        if j.listener:
            j.listener.wake = ww
        else:
            j.listener = Listener(ww, j._on_utterance, j._on_wake, j.emit)
            if settings["mic_enabled"]:
                j.listener.start()
        j.ready["wake"] = True
        j.store.log("settings", f"Wake word set to {speech.wake_phrase()}")
        return {"ok": True, "phrase": speech.wake_phrase()}

    def send_text(self, text):
        threading.Thread(target=self._j.brain.handle, args=(text, "text"), daemon=True).start()

    def push_to_talk(self):
        j = self._j
        j.speaker.stop()
        j.brain.interrupt()
        if not (j.listener and j.listener.stream):
            return "Microphone is off."
        j.listener.listen_now(window=6.0)
        return "ok"

    def stop(self):
        self._j.stop_all()

    def set_mic(self, on):
        j = self._j
        settings.update({"mic_enabled": bool(on)})
        if j.listener:
            j.listener.start() if on else j.listener.stop()
        j.store.log("privacy", f"Microphone {'enabled' if on else 'disabled'}")
        return bool(j.listener and j.listener.stream)

    def approve(self, pid, edits=None):
        return str(self._j.brain.approve(pid, edits))

    def reject(self, pid):
        return self._j.brain.reject(pid)

    def save_settings(self, values):
        settings.update(values)
        self._j.store.log("settings", "Updated: " + ", ".join(sorted(values)))
        return settings.public()

    def set_secret(self, name, value):
        config.set_secret(name, value.strip())
        self._j.store.log("settings", f"{'Saved' if value else 'Removed'} {name}")
        return secret_status()

    def test_voice(self, text=None):
        self._j.speak(text or self._j.brain._address("Good evening. All systems are online and at your service."))

    def elevenlabs_info(self):
        try:
            return {"ok": True, "voices": speech.elevenlabs_voices(), "usage": speech.elevenlabs_usage()}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def edge_voices(self):
        return ["en-GB-RyanNeural", "en-GB-ThomasNeural", "en-GB-SoniaNeural", "en-GB-LibbyNeural", "en-US-GuyNeural", "en-US-AndrewNeural"]

    def ms_connect(self):
        try:
            name = microsoft.connect()
            self._j.store.log("integration", "Microsoft account connected")
            return {"ok": True, "account": name}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def ms_disconnect(self):
        microsoft.disconnect()
        self._j.store.log("integration", "Microsoft account disconnected")
        return self.integrations()

    def google_connect(self):
        try:
            name = google.connect()
            self._j.store.log("integration", "Google account connected")
            return {"ok": True, "account": name}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def google_disconnect(self):
        google.disconnect()
        self._j.store.log("integration", "Google account disconnected")
        return self.integrations()

    @staticmethod
    def _try_token(name, token, check):
        """Save a pasted token, run check(), and put the old token back if the check fails."""
        old = config.get_secret(name)
        if token and token.strip():
            config.set_secret(name, token.strip())
        try:
            return check()
        except Exception:
            if token and token.strip():
                config.set_secret(name, old or "")
            raise

    def github_connect(self, token=None):
        try:
            user = self._try_token("github_token", token, github.whoami)
            settings.update({"github_enabled": True})
            self._j.store.log("integration", "GitHub connected")
            return {"ok": True, "user": user}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def github_disconnect(self):
        config.set_secret("github_token", "")
        settings.update({"github_enabled": False})
        self._j.store.log("integration", "GitHub disconnected")
        return self.integrations()

    def classic_outlook(self, on):
        settings.update({"outlook_classic_enabled": bool(on)})
        self._j.store.log("integration", f"Classic Outlook {'enabled' if on else 'disabled'}")
        if on:
            try:
                return {"ok": True, "accounts": outlook_classic.accounts()}
            except Exception as e:
                settings.update({"outlook_classic_enabled": False})
                return {"ok": False, "error": str(e)}
        return {"ok": True}

    def discord_connect(self, token=None):
        try:
            name = self._try_token("discord_bot_token", token, discord.whoami)
            settings.update({"discord_enabled": True})
            self._j.store.log("integration", "Discord bot connected")
            return {"ok": True, "bot": name, "channels": discord.list_channels()}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def discord_set_channels(self, channels):
        settings.update({"discord_channels": channels})
        return channels

    def discord_disconnect(self):
        config.set_secret("discord_bot_token", "")
        settings.update({"discord_enabled": False, "discord_channels": []})
        self._j.store.log("integration", "Discord disconnected")
        return self.integrations()

    def whatsapp_contacts(self):
        return whatsapp.contacts()

    def whatsapp_save_contact(self, name, phone):
        try:
            book = whatsapp.save_contact(name, phone)
            self._j.store.log("settings", f"Saved WhatsApp contact {name.strip()}")
            return {"ok": True, "contacts": book}
        except ValueError as e:
            return {"ok": False, "error": str(e)}

    def whatsapp_remove_contact(self, name):
        self._j.store.log("settings", f"Removed WhatsApp contact {name}")
        return whatsapp.remove_contact(name)

    def routines(self):
        return routines.routines()

    def delete_routine(self, name):
        routines.remove(name)
        self._j.store.log("settings", f"Deleted routine {name}")
        return routines.routines()

    def set_integration(self, name, on):
        key = {"whatsapp": "whatsapp_enabled"}.get(name)
        if key:
            settings.update({key: bool(on)})
        return self.integrations()

    def clear_history(self):
        self._j.store.clear_messages()
        self._j.store.log("privacy", "Conversation history cleared")

    def forget(self, mem_id):
        self._j.store.forget(int(mem_id))
        return self._j.store.memories()

    def activity(self):
        return self._j.store.activity(100)

    def open_link(self, url):
        if str(url).startswith(("http://", "https://")):
            win.open_url(url)


def _overlay_corner():
    import win32api
    left, top, right, bottom = win32api.GetMonitorInfo(win32api.MonitorFromPoint((0, 0), 1))["Work"]
    return right - OVERLAY_SIZE - 24, bottom - OVERLAY_SIZE - 24


def _round_window():
    """Make the orb window an exact circle, so it floats on the desktop with no square frame."""
    import ctypes
    import win32con
    import win32gui
    ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # real pixels
    for _ in range(50):
        hwnd = win32gui.FindWindow(None, OVERLAY_TITLE)
        if hwnd and win32gui.IsWindowVisible(hwnd):
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            side = min(r - l, b - t)
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, l, t, side, side, win32con.SWP_NOACTIVATE)
            win32gui.SetWindowRgn(hwnd, win32gui.CreateEllipticRgnIndirect((0, 0, side + 1, side + 1)), True)
            return
        time.sleep(0.1)


def run_overlay(port, x, y, parent=None):
    """Browser mode's floating orb: its own small window showing /overlay.html from the local server.
    Closes itself if Jarvis stops."""
    def watch():
        while parent and psutil.pid_exists(parent):
            time.sleep(2)
        os._exit(0)
    if parent:
        threading.Thread(target=watch, daemon=True).start()
    webview.create_window(OVERLAY_TITLE, f"http://127.0.0.1:{port}/overlay.html", width=OVERLAY_SIZE, height=OVERLAY_SIZE,
                          x=x, y=y, frameless=True, on_top=True, transparent=True, easy_drag=True, resizable=False,
                          min_size=(OVERLAY_SIZE, OVERLAY_SIZE), background_color="#090603")
    webview.start(_round_window)


def main():
    import win32api
    import win32event
    import winerror

    if "--overlay" in sys.argv:
        i = sys.argv.index("--overlay")
        run_overlay(*(int(a) for a in sys.argv[i + 1:i + 5]))
        return
    mutex = win32event.CreateMutex(None, False, "JarvisAssistantSingleInstance")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        print("Jarvis is already running.")
        return
    setup_logging()
    log.info("starting")
    j = Jarvis()
    j.api = Api(j)
    if "--web" in sys.argv:
        from . import web
        j.port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8765
        web.serve(j, j.api, UI.parent, j.port, open_browser="--no-browser" not in sys.argv)
    else:
        j.window = webview.create_window("Jarvis", str(UI), js_api=j.api, width=1320, height=840,
                                         min_size=(980, 640), background_color="#090603")
        webview.start(j.boot, debug="--debug" in sys.argv)
    j.show_overlay(False)
    j.speaker.stop()
    if j.listener:
        j.listener.stop()
    del mutex
