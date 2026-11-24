"""Jarvis desktop app: wires the mic, brain, voice and dashboard together."""
import json
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path

import subprocess

import psutil
import webview

from . import ai, autostart, config, power, providers, speech, team
from . import brain as brain_module
from .agent.core import Agent
from .agent.worker import Worker
from .brain import Brain
from .config import secret_status, settings
from .listener import Listener
from .storage import Store, setup_logging
from .tools import (discord, gamemode, games, github, google, home, microsoft, notion, outlook_classic, phone, routines, slack,
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
        self.worker = Worker(self.store, self.notify)
        self.agent = Agent(self.store, self.notify, self._reply_card, self._agent_paused, self._auto_prepare)
        self.brain.worker = self.worker
        self.brain.briefing_fn = lambda: self.give_briefing("asked", speak=False)["spoken"]  # the brain speaks it
        self.brain.agent = self.agent
        brain_module._AGENT[0] = self.agent  # for the AI's task tools
        brain_module._WORKER[0] = self.worker
        self.ready = {"wake": False, "stt": False}
        self.game_mode, self._game_auto, self._game_off_checks, self._mic_before_game = False, False, 0, False
        self.overlay = None        # pywebview window (desktop mode) or subprocess (browser mode)
        self.api = None
        self.port = None           # the local server's port
        self.awake = None          # power.KeepAwake once booted

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

    # ---------- the agent's voice: dashboard, phone, and a spoken line if you're here
    def notify(self, text, important=False):
        self.emit("notification", {"text": text, "important": important, "ts": time.time()})
        self.store.log("notify", text)
        if not important:
            return
        if not self.game_mode and _user_present() and not _quiet_hours() and self.state == "idle":
            self.emit("state", {"state": "speaking"})
            self.speaker.say(self.brain._address(text))
        try:  # also on the phone, through KDE Connect, when it's reachable
            if phone.cli() and any(d["reachable"] for d in phone.devices()):
                phone.ping("Jarvis: " + text)
        except Exception:
            pass

    # ---------- the welcome-back briefing
    def briefing(self, since=None):
        from .agent import briefing as brief
        from .brain import calendar as cal
        if since is None:
            last = settings.get("last_briefing") or 0
            since = last if time.time() - last < 24 * 3600 else time.time() - 24 * 3600
        def events():  # the calendar is slow to ask; five minutes old is fresh enough
            cache = getattr(self, "_cal_cache", (0, None))
            if time.time() - cache[0] > 300:
                self._cal_cache = cache = (time.time(), cal().events(2))
            return cache[1]
        return brief.compose(self.store, self.agent, self.worker, since=since, pending=len(self.brain.pending),
                             calendar=events)

    def give_briefing(self, reason="asked", speak=True):
        b = self.briefing()
        settings.update({"last_briefing": time.time()})
        self.emit("briefing", b)
        self.store.log("briefing", f"Briefing ({reason}): {b['spoken'][:300]}")
        if reason != "asked" and b["empty"]:
            return b  # came back to nothing new: show it, but don't talk
        if speak and settings.get("briefing_speak", True) and not self.game_mode and not _quiet_hours():
            self.emit("state", {"state": "speaking"})
            self.speaker.say(self.brain._address(b["spoken"]))
        return b

    def _watch_presence(self):
        """Notices when you come back (no keyboard or mouse for a while, then activity) and briefs you."""
        time.sleep(90)  # after starting up, give a briefing once things have settled
        if settings.get("briefing_enabled", True) and time.time() - (settings.get("last_briefing") or 0) > 3 * 3600:
            if _idle_seconds() < 120:
                self.give_briefing("startup")
        away = False
        while True:
            time.sleep(10)
            try:
                idle = _idle_seconds()
                if idle >= int(settings.get("briefing_away_min") or 30) * 60:
                    away = True
                elif away and idle < 15:
                    away = False
                    if settings.get("briefing_enabled", True):
                        self.give_briefing("returned")
            except Exception:
                log.exception("presence")

    def _auto_prepare(self, task):
        """Scholar found an assignment: hand it to Forge to prepare a draft."""
        if settings.get("agent_auto_prepare", True) and task and self.worker.queue_task(task):
            hid = self.store.add_handoff("scholar", "forge", f"Prepare {task['title']}")
            self.store.log("handoff", f"Scholar handed {task['title']} to Forge", "scholar")
            self.emit("handoff", {"from": "scholar", "to": "forge", "what": f"Prepare {task['title']}", "status": "working", "id": hid})

    def _reply_card(self, item, text):
        self.brain._request_approval("email_reply", {"id": item["ext_id"], "body": text})

    def _agent_paused(self):
        if self.game_mode:
            return "game mode is on"
        b = power.battery()
        if b and not b["plugged"] and b["percent"] < 20:
            return "battery below 20%"
        return None

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
        """Opens (or brings forward) the dashboard window, a separate small process."""
        if self.port:
            subprocess.Popen([_pythonw(), "-W", "ignore", "-m", "jarvis", "--window", "--port", str(self.port)],
                             cwd=str(ROOT), creationflags=subprocess.CREATE_NO_WINDOW)

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
        self.awake = power.KeepAwake(lambda on: self.store.log(
            "power", "Keeping the laptop awake while plugged in" if on else "Normal sleep allowed (on battery or setting off)"))
        self.agent.start()
        self.worker.start()
        threading.Thread(target=self._watch_presence, daemon=True, name="presence").start()
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
        if self.brain.source == "phone":  # the phone shows (and can read out) the reply; the laptop stays quiet
            if not isinstance(text, str):
                for _ in text:  # drain a streamed reply so its producer finishes
                    pass
            self.emit("state", {"state": "idle"})
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
                "mic": bool(j.listener and j.listener.stream), "history": j.store.recent_messages(40, "jarvis"),
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
            "phone": self._phone_info(),
            "classroom": {"connected": google.connected("school")},
            "autostart": {"on": autostart.enabled()},
            "remote": {"host": settings.get("remote_host") or "", "devices": len(self._j.store.devices())},
            "power": {"keep_awake": bool(self._j.awake and self._j.awake.active), "battery": power.battery()},
        }

    @staticmethod
    def _phone_info():
        if not phone.cli():
            return {"installed": False, "devices": []}
        try:
            return {"installed": True, "devices": phone.devices()}
        except Exception as e:
            return {"installed": True, "devices": [], "error": str(e)[:150]}

    # ---------- the phone, from the laptop dashboard (KDE Connect)
    def phone_ring(self):
        try:
            return phone.ring()
        except RuntimeError as e:
            return str(e)

    def phone_notifications(self):
        try:
            return phone.summary()
        except RuntimeError as e:
            return str(e)

    def phone_open(self, what):
        try:
            return phone.open_app(what) or f"I don't have a link for {what}."
        except RuntimeError as e:
            return str(e)

    # ---------- tasks and the background agent
    def tasks(self):
        return self._j.agent.task_list()

    def add_task(self, title, due_text=""):
        from .agent import dates
        title = (title or "").strip()
        if not title:
            return {"ok": False, "error": "Give the task a name."}
        tid = self._j.store.add_task(title, due=dates.parse(due_text) if due_text else None, source="you")
        self._j.store.log("task", f"Added task: {title}")
        return {"ok": True, "id": tid, "tasks": self.tasks()}

    def complete_task(self, task_id):
        self._j.store.update_task(task_id, status="done")
        self._j.store.log("task", f"Done: task #{task_id}")
        return self.tasks()

    def dismiss_task(self, task_id):
        self._j.store.update_task(task_id, status="dismissed")
        self._j.store.log("task", f"Dismissed: task #{task_id}")
        return self.tasks()

    def agent_status(self):
        return self._j.agent.status()

    # ---------- Today view and briefings
    def today(self):
        j = self._j
        b = j.briefing()
        return {"briefing": b, "status": self.laptop_status(), "phone": self._phone_info(),
                "approvals": list(j.brain.pending.values()),
                "activity": [a for a in j.store.activity(80) if a["kind"] in ("agent", "notify", "task", "remote", "briefing")][:12],
                "agent": j.agent.status()}

    def brief_me(self, source="text"):
        """A briefing now: spoken on the laptop when asked there, or returned for the phone to read out."""
        return self._j.give_briefing("asked", speak=source != "phone")["spoken"]

    # ---------- prepared work
    def jobs(self):
        return self._j.worker.jobs()

    def prepare_task(self, task_id, kind=None):
        task = self._j.store.task(task_id)
        if not task:
            return "That task no longer exists."
        kind = kind or {"presentation": "presentation", "document": "document", "notes": "notes", "revision": "revision",
                        "spreadsheet": "spreadsheet"}.get(task["kind"], "notes")
        job = self._j.worker.queue_task(task, kind)
        return f"Preparing a {kind} for {task['title']}. I'll tell you when it's ready." if job else \
            "That's already prepared or on its way."

    def open_result(self, job_id):
        """Opens a file Jarvis prepared, on the laptop (only files from Jarvis's own jobs)."""
        job = self._j.store.job(job_id)
        if not job or not job["result_path"] or not os.path.exists(job["result_path"]):
            return "That file isn't there any more."
        os.startfile(job["result_path"])
        return f"Opened {os.path.basename(job['result_path'])} on the laptop."

    def agent_run_now(self):
        if self._j.agent.running:
            return "Already checking."
        threading.Thread(target=self._j.agent.run, args=("manual",), daemon=True).start()
        return "Checking your school sources now."

    def classroom_connect(self):
        from .tools import classroom
        try:
            who = classroom.connect()
            self._j.store.log("integration", "Google Classroom connected (school account)")
            return {"ok": True, "account": who, "classes": len(classroom.courses())}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def classroom_disconnect(self):
        from .tools import classroom
        classroom.disconnect()
        self._j.store.log("integration", "Google Classroom disconnected")
        return self.integrations()

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

    def send_text(self, text, source="text"):
        threading.Thread(target=self._j.brain.handle, args=(text, source), daemon=True).start()

    # ---------- the team (Team view and direct chats)
    def team(self):
        """Every agent: profile, what it's doing now, AI used today and its latest action."""
        j = self._j
        used = ai.usage().get("by_agent", {})
        recent = j.store.activity(400)
        day_start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        out = []
        for name, a in team.AGENTS.items():
            mine = [x for x in recent if x["agent"] == name]
            busy = (j.brain._working == name or (name == "forge" and j.worker.current is not None)
                    or (name == "scholar" and j.agent.running) or (name == "jarvis" and j.state in ("thinking", "speaking")))
            out.append({**a.profile(), "status": "off" if not a.enabled else "working" if busy else "idle",
                        "used_today": used.get(name, 0), "done_today": sum(1 for x in mine if x["ts"] >= day_start),
                        "last": mine[0]["text"][:160] if mine else "", "last_ts": mine[0]["ts"] if mine else None})
        return out

    def set_agent(self, name, on):
        if name in team.AGENTS and name != "jarvis":  # Jarvis leads; he can't be switched off
            settings.update({f"agent_{name}_on": bool(on)})
            self._j.store.log("settings", f"{team.agent(name).title} switched {'on' if on else 'off'}", name)
        return self.team()

    def ask_agent(self, name, text, source="text"):
        """A direct chat with one specialist: Jarvis isn't asked first, which saves an AI request."""
        threading.Thread(target=self._j.brain.handle, args=(text, source, name), daemon=True).start()

    def chat_history(self, channel="jarvis"):
        return self._j.store.recent_messages(60, channel)

    def team_feed(self):
        """The #team channel: handoffs between team members and what each one did, newest last."""
        j = self._j
        feed = [{"ts": h["ts"], "kind": "handoff", "from": h["from"], "to": h["to"], "text": h["what"], "status": h["status"],
                 "result": h["result"]} for h in j.store.handoffs(40)]
        feed += [{"ts": x["ts"], "kind": x["kind"], "from": x["agent"], "text": x["text"]}
                 for x in j.store.activity(200) if x["agent"] and x["kind"] in ("agent", "quick", "blocked", "notify")]
        return sorted(feed, key=lambda x: x["ts"])[-80:]

    def voice(self, audio_b64, source="phone"):
        """A voice note recorded on the phone: transcribed here with the same on-device Whisper."""
        import base64
        import io
        from faster_whisper.audio import decode_audio
        if not self._j.ready["stt"]:
            return {"ok": False, "error": "Speech recognition is still loading on the laptop."}
        audio = decode_audio(io.BytesIO(base64.b64decode(audio_b64.split(",")[-1])), sampling_rate=16000)
        text = self._j.stt.transcribe((audio * 32767).astype("int16"))
        if text:
            self.send_text(text, source)
        return {"ok": bool(text), "text": text}

    # ---------- the laptop, as seen from the phone
    def ping(self):
        return {"ok": True, "time": time.time()}

    def laptop_status(self):
        j = self._j
        vm = psutil.virtual_memory()
        return {"name": os.environ.get("COMPUTERNAME", "Laptop"), "cpu": psutil.cpu_percent(interval=0.2), "ram": vm.percent,
                "battery": power.battery(), "keep_awake": bool(j.awake and j.awake.active), "game_mode": j.game_mode,
                "state": j.state, "mic": bool(j.listener and j.listener.stream),
                "uptime_h": round((time.time() - psutil.boot_time()) / 3600, 1)}

    def screenshot(self):
        """The laptop's screen as an image the phone can show. Nothing is saved."""
        import base64
        from .tools import screen
        self._j.store.log("remote", "Screenshot sent to a paired phone or the dashboard")
        return "data:image/png;base64," + base64.b64encode(screen.capture(max_width=1280)).decode()

    def running_apps(self):
        return win.running_apps()

    def lock_laptop(self):
        self._j.store.log("remote", "Laptop locked remotely")
        return win.lock_pc()

    def power(self, action):
        """Restart or shut down after a 30-second countdown (the phone asks you to confirm first)."""
        self._j.store.log("remote", f"{action} requested")
        return win.power_action(action, 30)

    def cancel_power(self):
        return win.cancel_power()

    # ---------- phones
    def pair_start(self):
        code = self._pairing.start() if getattr(self, "_pairing", None) else None
        host = settings.get("remote_host") or ""
        url = f"https://{host}/" if host else ""
        qr = ""
        if url:
            try:
                import segno
                qr = segno.make(f"{url}#pair={code}", error="m").svg_inline(scale=5, dark="#ffcf7a", light="#0b0703")
            except Exception:
                qr = ""
        return {"code": code, "url": url, "qr": qr, "minutes": 5}

    def _on_paired(self, name):
        self._j.store.log("remote", f"Paired a new device: {name}")
        self._j.emit("paired", {"name": name})

    def devices(self):
        return self._j.store.devices()

    def remove_device(self, dev_id):
        self._j.store.remove_device(dev_id)
        self._j.store.log("remote", f"Removed paired device #{dev_id}")
        return self._j.store.devices()

    def remote_status(self):
        """Is Tailscale installed and running here, and what's this laptop's private address?"""
        exe = _tailscale()
        out = {"installed": bool(exe), "host": settings.get("remote_host") or "", "running": False}
        if exe:
            try:
                st = json.loads(subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=8,
                                               creationflags=subprocess.CREATE_NO_WINDOW).stdout or "{}")
                out["running"] = st.get("BackendState") == "Running"
                dns = (st.get("Self") or {}).get("DNSName", "").rstrip(".")
                if dns:
                    out["host"] = dns
                    if dns != settings.get("remote_host"):
                        settings.update({"remote_host": dns})
            except (OSError, ValueError, subprocess.TimeoutExpired):
                pass
        return out

    def set_autostart(self, on):
        autostart.set_enabled(bool(on))
        self._j.store.log("settings", f"Start at sign-in {'on' if on else 'off'}")
        return autostart.enabled()

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

    def ai_status(self):
        """The AI models in order (main, then backups): labels, which are resting after a limit, which need a key."""
        u = ai.usage()
        slots = [settings.get("llm_provider")] + [f"backup:{b['id']}" for b in providers.backups()]
        chain = providers.chain()
        return {"chain": [{"slot": s, "label": providers.label(s), "resting": u["resting"].get(s, 0)} for s in chain],
                "active": u["active"], "active_label": providers.label(u["active"]),
                "backups": [{**b, "label": providers.label(f"backup:{b['id']}"),
                             "own_key": bool(config.get_secret(providers.own_key_name(b["id"]))),
                             "ready": providers.ready(f"backup:{b['id']}"),
                             "in_use": f"backup:{b['id']}" in chain,
                             "resting": u["resting"].get(f"backup:{b['id']}", 0)} for b in providers.backups()]}

    def save_backups(self, items):
        """The backup list from Settings, in order. Keys of removed backups are deleted from Credential Manager."""
        clean = []
        for b in items or []:
            bid = re.sub(r"[^a-z0-9]", "", str(b.get("id", "")).lower())[:16]
            if len(bid) >= 4 and b.get("provider") in providers.PROVIDERS:
                clean.append({"id": bid, "provider": b["provider"], "model": str(b.get("model") or "").strip()[:200]})
        gone = {b["id"] for b in providers.backups()} - {b["id"] for b in clean}
        for bid in gone:
            config.set_secret(providers.own_key_name(bid), "")
        settings.update({"llm_backups": clean})
        self._j.store.log("settings", f"AI backups: {len(clean)}")
        return self.ai_status()

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


def _idle_seconds():
    """Seconds since the last keyboard or mouse input on this PC."""
    import ctypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
        return 0
    return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000


def _user_present(seconds=120):
    """True if someone used the keyboard or mouse in the last two minutes."""
    return _idle_seconds() < seconds


def _quiet_hours(now=None):
    try:
        start, end = (int(x) for x in str(settings.get("quiet_hours") or "22-7").split("-"))
    except ValueError:
        return False
    h = (now or time.localtime()).tm_hour
    return (start <= h or h < end) if start > end else (start <= h < end)


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


def _pythonw():
    w = Path(sys.executable).with_name("pythonw.exe")
    return str(w if w.exists() else sys.executable)


def _tailscale():
    for p in (os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale", "tailscale.exe"),):
        if os.path.isfile(p):
            return p
    import shutil
    return shutil.which("tailscale")


def _core_running():
    import win32api
    import win32event
    import winerror
    h = win32event.CreateMutex(None, False, "JarvisAssistantSingleInstance")
    running = win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS
    win32api.CloseHandle(h)
    return running


def _wait_for_server(port, seconds=40):
    import httpx
    end = time.time() + seconds
    while time.time() < end:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/", timeout=2).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


def run_window(port):
    """The dashboard window: a client of the background core, starting the core first if needed."""
    import win32con
    import win32gui
    hwnd = win32gui.FindWindow(None, "Jarvis")
    if hwnd:  # already open: bring it forward
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return
    if not _core_running():
        subprocess.Popen([_pythonw(), "-W", "ignore", "-m", "jarvis", "--service", "--port", str(port)], cwd=str(ROOT),
                         creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
    if not _wait_for_server(port):
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, "Jarvis didn't start. See %LOCALAPPDATA%\\JarvisAssistant\\jarvis.log.", "Jarvis", 0x10)
        return
    webview.create_window("Jarvis", f"http://127.0.0.1:{port}/", width=1320, height=840, min_size=(980, 640),
                          background_color="#090603")
    webview.start(debug="--debug" in sys.argv)


def main():
    import win32api
    import win32event
    import winerror

    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else int(settings.get("port") or 8765)
    if "--overlay" in sys.argv:
        i = sys.argv.index("--overlay")
        run_overlay(*(int(a) for a in sys.argv[i + 1:i + 5]))
        return
    if not ({"--service", "--web"} & set(sys.argv)):  # plain "python -m jarvis" or --window: open the dashboard
        run_window(port)
        return
    # The core: mic, brain, background work and the local server. One per PC.
    mutex = win32event.CreateMutex(None, False, "JarvisAssistantSingleInstance")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        print("Jarvis is already running.")
        if "--web" in sys.argv and "--no-browser" not in sys.argv:
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{port}/")
        return
    setup_logging()
    log.info("starting core (%s)", "service" if "--service" in sys.argv else "browser")
    j = Jarvis()
    j.api = Api(j)
    j.port = port
    from . import web
    web.serve(j, j.api, UI.parent, port, open_browser="--web" in sys.argv and "--no-browser" not in sys.argv)
    j.show_overlay(False)
    j.speaker.stop()
    if j.listener:
        j.listener.stop()
    del mutex
