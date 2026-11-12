"""Core tests. Run:  run_tests.bat   (no apps are opened or closed: desktop actions are mocked)."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from jarvis import speech
from jarvis.brain import Brain, TOOLS
from jarvis.config import settings
from jarvis.storage import Store, redact
from jarvis.tools import windows as win


class FakeListener:
    stopped = False

    def stop(self):
        self.stopped = True


def make_brain():
    store = Store(Path(tempfile.mkdtemp()) / "t.db")
    events, spoken = [], []
    b = Brain(store, lambda k, d=None: events.append((k, d)), spoken.append, lambda: FakeListener())
    return b, events, spoken


class RouterBase(unittest.TestCase):
    """Desktop actions mocked, AI off."""

    def setUp(self):
        self.calls = []
        rec = lambda name: (lambda *a, **k: self.calls.append((name, a)) or f"{name} ok")
        self.patches = [mock.patch.object(win, n, rec(n)) for n in
                        ("open_app", "open_url", "youtube", "switch_to", "close_app", "media_key", "lock_pc")]
        self.patches.append(mock.patch.object(win, "close_target", lambda n: [(1, "Discord", "discord", 1)]))
        self.patches.append(mock.patch.object(settings, "get", lambda k, d=None: "off" if k == "llm_provider" else settings._data.get(k, d)))
        for p in self.patches:
            p.start()
        self.brain, self.events, self.spoken = make_brain()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def ask(self, text):
        self.brain.handle(text)
        return self.spoken[-1] if self.spoken else ""


class RouterTests(RouterBase):
    def test_open_app(self):
        self.ask("Hey Jarvis, open Opera GX.")
        self.assertEqual(self.calls[-1], ("open_app", ("opera gx",)))
        self.ask("launch discord")
        self.assertEqual(self.calls[-1], ("open_app", ("discord",)))

    def test_youtube(self):
        self.assertIn("YouTube", self.ask("Open YouTube"))
        self.assertEqual(self.calls[-1], ("youtube", (None,)))
        self.ask("open youtube and search for lofi beats")
        self.assertEqual(self.calls[-1], ("youtube", ("lofi beats",)))

    def test_website(self):
        self.ask("open github.com")
        self.assertEqual(self.calls[-1], ("open_url", ("github.com",)))

    def test_close_requires_confirmation(self):
        settings._data["confirm_close"] = True
        self.addCleanup(settings._data.pop, "confirm_close", None)
        reply = self.ask("close discord")
        self.assertIn("Close discord?", reply)
        self.assertFalse(any(c[0] == "close_app" for c in self.calls), "must not close before confirmation")
        self.assertEqual(len(self.brain.pending), 1)
        self.ask("yes")
        self.assertEqual(self.calls[-1], ("close_app", ("discord",)))
        self.assertEqual(self.brain.pending, {})

    def test_small_talk(self):
        self.assertRegex(self.ask("Hey Jarvis, hi."), r"^Good (morning|afternoon|evening)")
        self.assertIn("I'm Jarvis", self.ask("who are you"))
        self.assertIn("Spotify", self.ask("what can you do"))
        self.assertTrue(self.ask("thank you"))
        self.assertTrue(self.ask("tell me a joke"))
        self.ask("hi, open notepad")  # longer requests aren't small talk
        self.assertEqual(self.calls[-1], ("open_app", ("notepad",)))

    def test_close_without_confirmation(self):
        self.ask("close discord")
        self.assertEqual(self.calls[-1], ("close_app", ("discord",)))
        self.assertEqual(self.brain.pending, {})

    def test_sends_without_confirmation_only_when_asked(self):
        b = self.brain
        b.request = "email bob that I'll be late"
        self.assertTrue(b._auto_ok("email_compose"))
        b.request = "summarise my unread emails"  # the AI read something that told it to send: card instead
        self.assertFalse(b._auto_ok("email_compose"))
        b.request = "send hi in general on discord"
        with mock.patch.dict(settings._data, {"confirm_sends": True}):
            self.assertFalse(b._auto_ok("discord_post"))
        sent = []
        with mock.patch.dict(TOOLS["discord_post"], fn=lambda **a: sent.append(a) or "posted"):
            b.request = "summarise the announcements"
            out = b._run_tool("discord_post", {"channel": "general", "text": "x"}, [])
            self.assertEqual(out["status"], "awaiting_user_approval")
            b.request = "post hello in general"
            self.assertEqual(b._run_tool("discord_post", {"channel": "general", "text": "hello"}, []), "posted")
        self.assertEqual(sent, [{"channel": "general", "text": "hello"}])

    def test_new_connections_route(self):
        from jarvis.tools import github, weather, whatsapp as wa
        with mock.patch.object(weather, "forecast", lambda p="": f"weather:{p}"), \
             mock.patch.object(wa, "send_to", lambda n, t: f"sent:{n}:{t}"), \
             mock.patch.object(github, "notifications", lambda: [{"repo": "a/b", "title": "Fix it"}]):
            self.assertIn("weather:dubai", self.ask("what's the weather in Dubai"))
            self.assertIn("weather:", self.ask("will it rain tomorrow"))
            self.assertIn("sent:sam:hi", self.ask("send hi to sam on whatsapp"))
            self.assertIn("a/b: Fix it", self.ask("check my github notifications"))

    def test_close_cancel(self):
        settings._data["confirm_close"] = True
        self.addCleanup(settings._data.pop, "confirm_close", None)
        self.ask("close discord")
        self.ask("no")
        self.assertFalse(any(c[0] == "close_app" for c in self.calls))

    def test_send_needs_button_not_voice(self):
        pid = self.brain._request_approval("discord_post", {"channel": "general", "text": "hi"})
        with mock.patch.dict(TOOLS["discord_post"], fn=lambda **a: self.calls.append(("sent", a)) or "sent"):
            reply = self.ask("yes send it")
            self.assertIn("press the approve button", reply)
            self.assertFalse(any(c[0] == "sent" for c in self.calls))
            self.brain.approve(pid, {"text": "hi (edited)"})
            self.assertEqual(self.calls[-1], ("sent", {"channel": "general", "text": "hi (edited)"}))

    def test_running_and_sysinfo(self):
        self.assertIn("apps open", self.ask("what's running on my computer?"))
        self.assertIn("CPU at", self.ask("system status"))

    def test_memory(self):
        self.ask("remember that my exam is on Friday")
        self.assertIn("exam is on Friday", self.ask("what do you remember"))

    def test_whatsapp_honest(self):
        self.assertIn("official", self.ask("read my whatsapp messages"))

    def test_whatsapp_draft_offline(self):
        from jarvis.tools import whatsapp as wa
        cases = {
            "send hi to sam in whatsapp": ("sam", "hi"),
            "Hey Jarvis, send hi to Sam on WhatsApp.": ("Sam", "hi"),
            "send good morning to sam on whats app": ("sam", "good morning"),
            "message sam on whatsapp saying I'll be late": ("sam", "I'll be late"),
            "send sam a whatsapp saying see you at 5": ("sam", "see you at 5"),
            "text are you coming to Amma on WhatsApp": ("Amma", "are you coming"),
        }
        for said, expected in cases.items():
            self.assertEqual(wa.parse(said.replace("Hey Jarvis, ", "")), expected, said)
        self.assertIsNone(wa.parse("open whatsapp"))
        opened = []
        with mock.patch.object(wa.os, "startfile", opened.append), \
             mock.patch.dict(settings._data, {"whatsapp_contacts": {"Sam": "971500000000"}, "whatsapp_enabled": True, "confirm_sends": True}):
            reply = self.ask("send hi to sam in whatsapp")
            self.assertEqual(opened[-1], "whatsapp://send?phone=971500000000&text=hi")
            self.assertIn("press Send", reply)
            self.ask("send hello there to Unknown Person on whatsapp")
            self.assertEqual(opened[-1], "whatsapp://send?text=hello%20there")
            self.assertIn("don't have a number", self.spoken[-1])
        with mock.patch.object(wa.os, "startfile", opened.append), mock.patch.dict(settings._data, {"whatsapp_enabled": False, "confirm_sends": True}):
            n = len(opened)
            self.assertIn("turned off", self.ask("send hi to sam on whatsapp"))
            self.assertEqual(len(opened), n)

    def test_spotify_commands(self):
        from jarvis.tools import spotify as sp
        cases = {
            "play any song in spotify": ("any", ""), "play some music": ("any", ""), "play something": ("any", ""),
            "play my liked songs": ("liked", ""), "play my liked songs on spotify": ("liked", ""),
            "play my favourite songs": ("liked", ""),
            "play the song dracula": ("song", "dracula"), "play dracula": ("song", "dracula"),
            "play dracula by tame impala on spotify": ("song", "dracula by tame impala"),
            "play the song blinding lights in spoitfy": ("song", "blinding lights"),
        }
        for said, expected in cases.items():
            self.assertEqual(sp.parse(said), expected, said)
        for other in ("play music", "play pause", "play lofi on youtube", "open spotify"):
            self.assertIsNone(sp.parse(other), other)
        played = []
        with mock.patch.object(sp, "play", lambda *a: played.append(a) or "Playing."):
            self.ask("Hey Jarvis, play the song Dracula.")
            self.ask("play any song in spotify")
            self.ask("play my liked songs")
            self.ask("play music")  # stays the media key (resume)
        self.assertEqual(played, [("song", "dracula"), ("any", ""), ("liked", "")])
        self.assertEqual(self.calls[-1], ("media_key", ("play pause",)))

    def test_atticus_style_commands(self):
        from jarvis.tools import files, layout, uia
        got = []
        rec = lambda name: (lambda *a: got.append((name, a)) or f"{name} done")
        with mock.patch.object(layout, "arrange", rec("arrange")), mock.patch.object(uia, "press", rec("press")), \
             mock.patch.object(files, "find", rec("find")), mock.patch.dict(settings._data, {"routines": {}}):
            self.ask("put notepad on the left and calculator on the right")
            self.assertEqual(got[-1], ("arrange", ([("notepad", "left", None), ("calculator", "right", None)],)))
            self.ask("maximise discord")
            self.assertEqual(got[-1][1][0], [("discord", "maximise", None)])
            self.ask("press seven in calculator")
            self.assertEqual(got[-1], ("press", ("seven", "calculator")))
            n = len(got)
            self.assertIn("press approve", self.ask("click send in outlook"))
            self.assertEqual(len(got), n, "risky buttons wait for the card")
            self.ask("yes")  # a spoken yes isn't enough for a risky button
            self.assertEqual(len(got), n)
            self.ask("find my notes about the tokyo trip")
            self.assertEqual(got[-1], ("find", ("notes about the tokyo trip",)))
            self.assertIsNone(files.parse("search the web for cats"))
            self.assertIsNone(files.parse("find a good restaurant"))
            # routines
            reply = self.ask("when I say focus mode, close discord and open notepad")
            self.assertIn("focus mode", reply)
            self.assertEqual(settings._data["routines"]["focus mode"], ["close discord", "open notepad"])
            self.brain.pending.clear()
            self.ask("focus mode")
            self.assertEqual([c[0] for c in self.calls[-2:]], ["close_app", "open_app"])
            self.assertIn("focus mode", self.ask("what routines do I have"))
            self.ask("forget the focus mode routine")
            self.assertEqual(settings._data["routines"], {})

    def test_says_sir(self):
        with mock.patch.dict(settings._data, {"honorific": "sir"}):
            a = Brain._address
            self.assertEqual(a("Opening YouTube."), "Opening YouTube, sir.")
            self.assertEqual(a("Yes?"), "Yes, sir?")
            self.assertEqual(a("Done"), "Done, sir.")
            self.assertEqual(a("Very good, sir. Opening it now."), "Very good, sir. Opening it now.")
            self.assertIn("on the card, sir.", self.ask("click delete in calculator"))
            self.ask("")
            self.assertEqual(self.spoken[-1], "Yes, sir?")
        with mock.patch.dict(settings._data, {"honorific": ""}):
            self.assertEqual(Brain._address("Opening YouTube."), "Opening YouTube.")

    def test_mute(self):
        self.ask("mute the microphone")
        self.assertFalse(settings._data["mic_enabled"])
        settings.update({"mic_enabled": True})

    def test_no_llm_message(self):
        self.assertIn("isn't configured", self.ask("write me a poem about the sea"))

    def test_private_mode_keeps_mail_local(self):
        from jarvis import brain as B
        fake_mail = mock.Mock(unread=lambda n: [{"from": "Ann", "subject": "Hi"}])
        with mock.patch.object(settings, "get", lambda k, d=None: {"llm_provider": "gemini", "private_mode": True}.get(k, settings._data.get(k, d))), \
             mock.patch.object(B, "mail", lambda: fake_mail), \
             mock.patch.object(self.brain, "_llm", side_effect=AssertionError("cloud AI must not be called")):
            self.assertIn("From Ann: Hi", self.ask("read my emails"))
            names = {t["name"] for t in self.brain._tools()}
            self.assertFalse(names & B.PERSONAL_TOOLS)
            self.assertIn("error", self.brain._run_tool("email_unread", {}, []))

    def test_stop_is_silent(self):
        n = len(self.spoken)
        self.ask("stop")
        self.assertEqual(len(self.spoken), n)


class SafetyTests(unittest.TestCase):
    def test_redaction(self):
        self.assertNotIn("abc123secret", redact("token=abc123secret"))
        self.assertNotIn("AIzaSyD", redact("key AIzaSyD" + "x" * 33))
        self.assertIn("[REDACTED]", redact("Authorization: Bearer eyJhbGciOi.payload.sig"))

    def test_approval_tools(self):
        for name in ("email_compose", "email_reply", "discord_post"):
            self.assertEqual(TOOLS[name]["approval"], "button", name)
        self.assertEqual(TOOLS["close_app"]["approval"], "voice")

    def test_protected_processes(self):
        with mock.patch.object(win, "_windows", lambda: [(1, "File Explorer", "explorer", 1)]):
            self.assertEqual(win.close_target("explorer"), [])


class ProviderTests(unittest.TestCase):
    """Each AI provider's request format, against a fake server: a tool call, then a final answer."""

    def setUp(self):
        self.brain, _, _ = make_brain()
        self.ran = []
        self.patch = mock.patch.dict(TOOLS["system_info"], fn=lambda: self.ran.append("system_info") or {"cpu_percent": 5})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def use(self, provider):
        values = {"llm_provider": provider, "private_mode": False}
        p = mock.patch.object(settings, "get", lambda k, d=None: values.get(k, settings._data.get(k, d)))
        p.start()
        self.addCleanup(p.stop)
        k = mock.patch("jarvis.brain.get_secret", lambda name: "test-key")
        k.start()
        self.addCleanup(k.stop)

    def test_openai_compatible(self):
        from jarvis import providers
        self.use("groq")
        replies = iter([
            {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "system_info", "arguments": "{}"}}]}}]},
            {"choices": [{"message": {"role": "assistant", "content": "CPU is at 5%."}}]},
        ])
        sent = []

        def fake_post(url, json=None, headers=None, timeout=None):
            sent.append((url, json, headers))
            return mock.Mock(status_code=200, json=lambda: next(replies))
        with mock.patch("jarvis.brain.httpx.post", fake_post):
            reply, _ = self.brain._llm("how's my cpu")
        self.assertEqual(reply, "CPU is at 5%.")
        self.assertEqual(self.ran, ["system_info"])
        self.assertEqual(sent[0][0], providers.PROVIDERS["groq"]["url"] + "/chat/completions")
        self.assertEqual(sent[0][2]["Authorization"], "Bearer test-key")
        self.assertEqual(sent[1][1]["messages"][-2], {"role": "tool", "tool_call_id": "c1", "content": '{"cpu_percent": 5}'})

    def test_anthropic(self):
        import anthropic
        self.use("anthropic")
        from types import SimpleNamespace as Block  # (mock.Mock treats name= specially)
        responses = iter([
            mock.Mock(stop_reason="tool_use", content=[Block(type="tool_use", id="t1", name="system_info", input={})]),
            mock.Mock(stop_reason="end_turn", content=[Block(type="text", text="CPU is at 5%.")]),
        ])
        calls = []
        client = mock.Mock()
        client.beta.messages.create = lambda **kw: calls.append(kw) or next(responses)
        with mock.patch.object(anthropic, "Anthropic", lambda **kw: client):
            reply, _ = self.brain._llm("how's my cpu")
        self.assertEqual(reply, "CPU is at 5%.")
        self.assertEqual(self.ran, ["system_info"])
        self.assertEqual(calls[0]["model"], "claude-opus-5-5")
        self.assertEqual(calls[0]["fallbacks"], "default")
        result = calls[1]["messages"][-2]["content"][0]
        self.assertEqual((result["type"], result["tool_use_id"], result["is_error"]), ("tool_result", "t1", False))

    def test_cloud_vs_local(self):
        from jarvis import providers
        for name, cloud in (("anthropic", True), ("ollama", False), ("custom", False)):
            with mock.patch.object(settings, "get", lambda k, d=None, n=name: n if k == "llm_provider" else settings._data.get(k, d)):
                self.assertEqual(providers.is_cloud(), cloud, name)


class WebModeTests(unittest.TestCase):
    """Browser mode server: serves the page, and only the page's own token can call Jarvis."""

    def test_server_security(self):
        import http.client
        from http.server import ThreadingHTTPServer
        from jarvis import web

        class FakeApi:
            calls = []

            def send_text(self, text):
                self.calls.append(text)
                return "ok"

        api, hub = FakeApi(), web.Hub()
        ui = Path(__file__).resolve().parent.parent / "ui"
        srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = srv.server_address[1]
        srv.RequestHandlerClass = web.make_handler(api, ui.resolve(), port, hub)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def req(method, path, body=None, headers=None):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request(method, path, body, {"Host": f"127.0.0.1:{port}", **(headers or {})})
                r = c.getresponse()
                return r.status, r.read()

            status, page = req("GET", "/")
            self.assertEqual(status, 200)
            self.assertIn(web.TOKEN.encode(), page)
            self.assertIn(b"web-bridge.js", page)
            self.assertEqual(req("POST", "/api/send_text", b'["hi"]')[0], 403)  # no token
            self.assertEqual(req("POST", "/api/send_text", b'["hi"]', {"Host": f"evil.example:{port}", "X-Jarvis-Token": web.TOKEN})[0], 403)
            self.assertEqual(req("POST", "/api/_secret", b"[]", {"X-Jarvis-Token": web.TOKEN})[0], 404)
            self.assertEqual(req("GET", "/../jarvis/config.py")[0], 404)
            self.assertEqual(req("GET", "/events?token=wrong")[0], 403)
            self.assertEqual(req("POST", "/api/send_text", b'["hi"]', {"X-Jarvis-Token": web.TOKEN}), (200, b'"ok"'))
            self.assertEqual(api.calls, ["hi"])
        finally:
            srv.shutdown()
            srv.server_close()


class SpotifyScreenTests(unittest.TestCase):
    """The Play button is found in a capture of the Spotify window; these use drawn stand-ins."""

    def page(self, icon, shuffle_on=None):
        img = np.full((600, 1000, 3), 18, np.uint8)
        yy, xx = np.mgrid[:600, :1000]
        img[(xx - 120) ** 2 + (yy - 300) ** 2 <= 36 ** 2] = (30, 215, 96)
        if icon == "play":
            img[(xx >= 110) & (xx <= 134) & (abs(yy - 300) <= (134 - xx) // 2)] = (0, 0, 0)
        else:
            img[285:316, 106:115] = img[285:316, 126:135] = (0, 0, 0)
        img[290:296, 360:366] = (30, 215, 96)  # a small green icon elsewhere must be ignored
        if shuffle_on is not None:
            img[292:309, 200:226] = (30, 215, 96) if shuffle_on else (180, 180, 180)
        return img

    def test_button_state(self):
        from jarvis.tools import spotify as sp
        spot = sp.find_play_button(self.page("play"))
        self.assertLess(abs(spot[0] - 120) + abs(spot[1] - 300), 6)
        self.assertFalse(sp.shows_pause(self.page("play"), spot))
        self.assertTrue(sp.shows_pause(self.page("pause"), sp.find_play_button(self.page("pause"))))
        self.assertIsNone(sp.find_play_button(np.full((600, 1000, 3), 18, np.uint8)))

    def test_shuffle_toggle(self):
        from jarvis.tools import spotify as sp
        for on in (False, True):
            img = self.page("play", shuffle_on=on)
            x, y, state = sp.find_shuffle(img, sp.find_play_button(img))
            self.assertEqual(state, on)
            self.assertLess(abs(x - 213), 6)

    def test_song_choice(self):
        from jarvis.tools import spotify as sp
        hits = [("Dracula - Sped Up - song and lyrics by Someone | Spotify", "a" * 22),
                ("Dracula - song and lyrics by Tame Impala | Spotify", "b" * 22),
                ("Drama - song and lyrics by Other | Spotify", "c" * 22)]
        sp._found.clear()
        with mock.patch.object(sp, "_track_hits", lambda q: hits):
            self.assertEqual(sp.find_track("dracula")[0], "b" * 22)
            self.assertEqual(sp.find_track("dracula by tame impala")[0], "b" * 22)
        sp._found.clear()


class VoicePipelineTests(unittest.TestCase):
    """Synthesises 'Hey Jarvis, open YouTube' and pushes it through the real wake word + listener."""

    @classmethod
    def setUpClass(cls):
        audio, rate = speech.synth_edge("Hey Jarvis.")
        cmd, _ = speech.synth_edge("Open YouTube.")
        def to16k(a):  # 24 kHz -> 16 kHz
            return np.interp(np.arange(0, len(a), 1.5), np.arange(len(a)), a).astype(np.int16)
        silence = np.zeros(16000, dtype=np.int16)
        cls.clip = np.concatenate([silence, to16k(audio), np.zeros(3200, np.int16), to16k(cmd), silence, silence])

    def test_wake_and_transcribe(self):
        from jarvis.listener import Listener
        got, woke = [], threading.Event()
        lst = Listener(speech.WakeWord(), got.append, woke.set, lambda *a: None)
        lst.stream = True  # pretend the mic is open; frames are fed by hand below
        for i in range(0, len(self.clip) - 1280, 1280):
            lst.frames.put(self.clip[i:i + 1280])
            time.sleep(0.004)
        deadline = time.time() + 10
        while not got and time.time() < deadline:
            time.sleep(0.1)
        self.assertTrue(woke.is_set(), "wake word not detected")
        self.assertTrue(got, "utterance not captured")
        text = speech.STT().transcribe(got[0]).lower()
        self.assertIn("youtube", text)

    def test_follow_up_and_interrupt(self):
        from jarvis.app import Jarvis
        from jarvis.listener import Listener
        j = Jarvis()
        j.listener = Listener(speech.WakeWord(), lambda a: None, j._on_wake, lambda *a: None)
        j.listener.stream = True
        j.voice_turn = True
        j._on_speaking(False)  # a spoken reply just finished
        self.assertEqual(j.listener.mode, "listening", "should keep listening for a follow-up")
        j.stop_all()
        self.assertEqual(j.listener.mode, "idle")
        gen = j.brain.cancel_gen
        with mock.patch.object(speech, "chime", lambda: None):
            j._on_wake()  # "Hey Jarvis" while busy cancels the current reply
        self.assertGreater(j.brain.cancel_gen, gen)

    def test_tts_providers(self):
        a, r = speech.synth_edge("Testing.")
        self.assertGreater(len(a), 1000)
        a, r = speech.synth_windows("Testing.")
        self.assertGreater(len(a), 1000)

    def test_sentence_split(self):
        self.assertEqual(len(speech._sentences("Hello there. This is a much longer second sentence that goes on. Ok.")), 2)


class NewFeatureRouteTests(RouterBase):
    """Games, YouTube, screen, clipboard, game mode, smart home, Notion and Telegram routes (all mocked)."""

    def test_games(self):
        from jarvis.tools import games
        fake = {"name": "Rocket League®", "store": "Epic", "launch": "x", "folder": ""}
        with mock.patch.object(games, "find", lambda q: fake if "rocket" in q else None), \
                mock.patch.object(games, "launch", lambda q: f"Launching {q}."):
            self.assertEqual(self.ask("play rocket league"), "Launching rocket league, sir.")
            self.ask("open notepad")  # not a game: still opens the app
            self.assertEqual(self.calls[-1], ("open_app", ("notepad",)))

    def test_youtube_plays_top_result(self):
        from jarvis.tools import youtube
        played = []
        with mock.patch.object(youtube, "play", lambda q, music=False: played.append((q, music)) or "Playing."):
            self.ask("play dracula on youtube")
            self.ask("play blinding lights on youtube music")
        self.assertEqual(played, [("dracula", False), ("blinding lights", True)])

    def test_game_mode_by_voice(self):
        seen = []
        self.brain.set_game_mode = lambda on: seen.append(on) or "ok"
        self.ask("game mode on")
        self.ask("turn off game mode")
        self.assertEqual(seen, [True, False])

    def test_screen_and_clipboard_need_ai(self):
        from jarvis.tools import screen
        self.assertIn("needs an AI model", self.ask("what's on my screen"))
        with mock.patch.object(screen, "get_clipboard", lambda: "hola amigo"):
            self.assertIn("needs an AI model", self.ask("translate what I copied into English"))
            self.assertIn("hola amigo", self.ask("read my clipboard"))

    def test_screen_and_clipboard_with_ai(self):
        from jarvis.tools import screen
        with mock.patch.object(self.brain, "_llm_available", lambda: True), \
                mock.patch.object(self.brain, "_vision", lambda q, address=True: "A code editor with an error."), \
                mock.patch.object(self.brain, "_llm", lambda text: (f"LLM<{text}>", [])), \
                mock.patch.object(screen, "get_clipboard", lambda: "hola amigo"):
            self.assertIn("code editor", self.ask("explain this error"))
            reply = self.ask("translate what I copied into English")
        self.assertIn("translate the following text from my clipboard into english", reply)
        self.assertIn("hola amigo", reply)

    def test_smart_home(self):
        from jarvis.tools import home
        done = []
        with mock.patch.object(home, "connected", lambda: True), \
                mock.patch.object(home, "find", lambda n: {"name": n} if "light" in n or "fan" in n else None), \
                mock.patch.object(home, "control", lambda d, a, v=None: done.append((d, a, v)) or "ok"):
            self.ask("turn on the bedroom light")
            self.ask("turn the fan off")
            self.ask("dim the desk light to 30%")
        self.assertEqual(done, [("bedroom light", "on", None), ("fan", "off", None), ("desk light", "brightness", 30)])

    def test_notion_and_telegram(self):
        from jarvis.tools import notion, telegram
        with mock.patch.object(notion, "add_note", lambda t, title="": f"noted {t}"), \
                mock.patch.object(telegram, "updates", lambda n=20: [{"from": "Sam", "chat": "Sam", "text": "hi"}]):
            self.assertIn("noted buy milk", self.ask("add buy milk to notion"))
            self.assertIn("Sam: hi", self.ask("check telegram"))


class StreamingTests(unittest.TestCase):
    def test_sentence_stream(self):
        st = speech.SentenceStream()
        for piece in ["Tokyo is the capital of Japan, home to millions. ", "It has great food", ". And trains."]:
            st.feed(piece)
        self.assertTrue(st.started)  # the first sentence is ready before the reply ends
        st.finish(lambda last: last[:-1] + ", sir.")
        out = list(st)
        self.assertEqual(out[0], "Tokyo is the capital of Japan, home to millions.")
        self.assertEqual(out[-1], "It has great food. And trains, sir.")

    def test_openai_stream_round(self):
        """Streamed text and a tool call split over several chunks are put back together."""
        brain, _, _ = make_brain()
        got = []
        brain._live = got.append
        lines = [
            'data: {"choices":[{"delta":{"content":"Checking. "}}]}',
            ": OPENROUTER PROCESSING",
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"system_","arguments":""}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"info","arguments":"{}"}}]}}]}',
            "data: [DONE]",
        ]

        class Resp:
            status_code = 200
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def iter_lines(self): return iter(lines)
        with mock.patch("jarvis.brain.httpx.stream", lambda *a, **k: Resp()):
            msg = brain._openai_stream("u", {}, {"model": "m"})
        self.assertEqual(got, ["Checking. "])
        self.assertEqual(msg["content"], "Checking. ")
        self.assertEqual(msg["tool_calls"][0]["function"], {"name": "system_info", "arguments": "{}"})

    def test_handle_speaks_while_streaming(self):
        """The first sentences are spoken before the AI finishes, and 'sir' is added once at the end."""
        brain, events, spoken = make_brain()

        def fake_llm(text):
            for piece in ["The weather in Dubai is hot and sunny today. ", "Expect highs of thirty five. ", "Stay cool."]:
                brain._emit_text(piece)
            return "Stay cool.", []
        values = {"honorific": "sir", "stream_replies": True}
        with mock.patch.object(settings, "get", lambda k, d=None: values.get(k, settings._data.get(k, d))), \
                mock.patch.object(brain, "_quick", lambda t: None), mock.patch.object(brain, "_llm", fake_llm):
            brain.handle("what's the weather like")
        self.assertEqual(len(spoken), 1)
        self.assertIsInstance(spoken[0], speech.SentenceStream)
        said = list(spoken[0])
        self.assertEqual(said[0], "The weather in Dubai is hot and sunny today.")
        self.assertEqual(said[-1], "Expect highs of thirty five. Stay cool, sir.")  # short endings join the one before
        final = [d for k, d in events if k == "message" and d["role"] == "assistant"][-1]["text"]
        self.assertTrue(final.endswith("Stay cool, sir."))
        self.assertEqual(final.count("sir"), 1)


class NewSafetyTests(unittest.TestCase):
    def test_screen_only_when_asked(self):
        brain, _, _ = make_brain()
        brain.request = "summarise my emails"
        self.assertIn("error", brain._run_tool("look_at_screen", {"question": "x"}, []))

    def test_new_sends_follow_the_rules(self):
        from jarvis.brain import SEND_TOOLS, PERSONAL_TOOLS
        self.assertTrue({"slack_post", "telegram_send"} <= SEND_TOOLS)
        self.assertTrue({"notion_search", "drive_read", "slack_read", "telegram_messages"} <= PERSONAL_TOOLS)
        self.assertEqual(TOOLS["slack_post"]["approval"], "button")

    def test_png_encoder(self):
        import zlib
        from jarvis.tools import screen
        img = np.zeros((4, 6, 3), dtype=np.uint8)
        img[1, 2] = (255, 128, 0)
        data = screen.png(img)
        self.assertTrue(data.startswith(b"\x89PNG"))
        raw = zlib.decompress(data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8])
        self.assertEqual(len(raw), 4 * (1 + 6 * 3))
        self.assertEqual(raw[1 * 19 + 1 + 2 * 3:1 * 19 + 1 + 2 * 3 + 3], bytes([255, 128, 0]))

    def test_game_matching_is_strict(self):
        from jarvis.tools import games
        lib = [{"name": n, "store": "Steam", "launch": "x", "folder": ""} for n in
               ("Rocket League®", "Fall Guys", "Five Nights at Freddy's: Into the Pit", "Grand Theft Auto V")]
        with mock.patch.object(games, "installed", lambda refresh=False: lib):
            self.assertEqual(games.find("rocket league")["name"], "Rocket League®")
            self.assertEqual(games.find("fnaf")["name"], "Five Nights at Freddy's: Into the Pit")
            self.assertEqual(games.find("gta")["name"], "Grand Theft Auto V")
            self.assertIsNone(games.find("notepad"))
            self.assertIsNone(games.find("calculator"))

    def test_service_token_restored_on_failure(self):
        from jarvis import app as appmod
        saved = {}
        with mock.patch.object(appmod.config, "get_secret", lambda n: saved.get(n, "")), \
                mock.patch.object(appmod.config, "set_secret", lambda n, v: saved.__setitem__(n, v)):
            saved["notion_token"] = "good"
            bad = lambda: (_ for _ in ()).throw(RuntimeError("401"))
            with self.assertRaises(RuntimeError):
                appmod.Api._try_token("notion_token", "wrong", bad)
            self.assertEqual(saved["notion_token"], "good")


class PhoneAccessTests(unittest.TestCase):
    """The phone reaches Jarvis through Tailscale: it must pair first, then may only use the phone methods."""

    def setUp(self):
        import http.client
        from http.server import ThreadingHTTPServer
        from jarvis import web

        class FakeApi:
            calls = []

            def send_text(self, text, source="text"):
                self.calls.append((text, source))
                return "ok"

            def init(self):
                return {"ok": True}

            def set_secret(self, name, value):
                self.calls.append(("set_secret", name))
                return {}

        self.web, self.api = web, FakeApi()
        self.store = Store(Path(tempfile.mkdtemp()) / "t.db")
        self.pairing = web.Pairing()
        ui = Path(__file__).resolve().parent.parent / "ui"
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
        self.port = self.srv.server_address[1]
        self.srv.RequestHandlerClass = web.make_handler(self.api, ui.resolve(), self.port, web.Hub(), self.store, self.pairing)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        values = {"remote_host": "laptop.tail123.ts.net"}
        p = mock.patch.object(settings, "get", lambda k, d=None: values.get(k, settings._data.get(k, d)))
        p.start()
        self.addCleanup(p.stop)

        def req(method, path, body=None, headers=None, remote=True):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            h = {"Host": "laptop.tail123.ts.net", "X-Forwarded-For": "100.64.0.2", "X-Forwarded-Proto": "https"} if remote \
                else {"Host": f"127.0.0.1:{self.port}"}
            c.request(method, path, body, {**h, **(headers or {})})
            r = c.getresponse()
            return r.status, r.read(), r.getheader("Set-Cookie") or ""
        self.req = req

    def test_unpaired_phone_gets_only_the_app_shell(self):
        status, page, _ = self.req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Pair this phone", page)
        self.assertNotIn(self.web.TOKEN.encode(), page)  # the laptop's own token never goes to the phone
        self.assertEqual(self.req("GET", "/index.html")[0], 403)
        self.assertEqual(self.req("GET", "/events")[0], 403)
        self.assertEqual(self.req("POST", "/api/init", b"[]")[0], 403)
        # the laptop's per-run token doesn't work from outside either
        self.assertEqual(self.req("POST", "/api/init", b"[]", {"X-Jarvis-Token": self.web.TOKEN})[0], 403)
        self.assertEqual(self.req("GET", "/", headers={"Host": "evil.example"})[0], 403)

    def test_pairing_then_phone_methods_only(self):
        self.assertEqual(self.req("POST", "/pair", b'{"code": "000000"}')[0], 403)  # no code started
        code = self.pairing.start()
        status, body, cookie = self.req("POST", "/pair", json_body({"code": code, "name": "Test phone"}))
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Secure", cookie)
        token_pair = cookie.split(";")[0]
        self.assertEqual(self.req("POST", "/pair", json_body({"code": code}))[0], 403)  # codes work once
        h = {"Cookie": token_pair}
        self.assertEqual(self.req("POST", "/api/init", b"[]", h)[:2], (200, b'{"ok": true}'))
        self.req("POST", "/api/send_text", b'["open opera"]', h)
        self.assertEqual(self.api.calls[-1], ("open opera", "phone"))  # replies to the phone stay on the phone
        self.assertEqual(self.req("POST", "/api/set_secret", b'["x", "y"]', h)[0], 403)  # not a phone method
        self.assertEqual(self.req("GET", "/index.html", headers=h)[0], 200)
        # the stored key is a hash, and removing the device locks the phone out
        dev = self.store.devices()[0]
        raw = self.store._query("SELECT token_hash FROM devices")[0][0]
        self.assertNotIn(raw, token_pair)
        self.store.remove_device(dev["id"])
        self.assertEqual(self.req("POST", "/api/init", b"[]", h)[0], 403)

    def test_local_dashboard_still_uses_its_token(self):
        status, page, _ = self.req("GET", "/", remote=False)
        self.assertIn(self.web.TOKEN.encode(), page)
        self.assertEqual(self.req("POST", "/api/set_secret", b'["x", "y"]', {"X-Jarvis-Token": self.web.TOKEN}, remote=False)[0], 200)


def json_body(d):
    import json
    return json.dumps(d).encode()


class LaptopFromPhoneTests(RouterBase):
    def test_power_needs_approval_and_can_be_cancelled(self):
        with mock.patch.object(win, "power_action", lambda a, d=30: self.calls.append(("power", a)) or "Restarting."), \
                mock.patch.object(win, "cancel_power", lambda: "Cancelled the restart or shutdown."):
            self.assertIn("Say yes", self.ask("restart my laptop"))
            self.assertNotIn(("power", "restart"), self.calls)  # nothing happens before approval
            self.ask("yes")
            self.assertIn(("power", "restart"), self.calls)
            self.assertIn("Cancelled", self.ask("cancel shutdown"))
            self.assertIn("Shut down the laptop?", self.ask("shut down my laptop"))

    def test_screenshot_goes_to_the_phone(self):
        from jarvis.tools import screen
        with mock.patch.object(screen, "capture", lambda max_width=1600, region=None: b"PNGDATA"):
            self.brain.handle("take a screenshot of my laptop and show it to me", "phone")
        img = [d for k, d in self.events if k == "image"]
        self.assertTrue(img and img[0]["data"].startswith("data:image/png;base64,"))

    def test_phone_phrasing(self):
        self.ask("open google classroom and leave it running on my laptop")
        self.assertEqual(self.calls[-1], ("open_url", ("https://classroom.google.com",)))
        with mock.patch.object(win, "running_apps", lambda: [{"app": "Opera GX"}, {"app": "Discord"}]):
            self.assertIn("Opera GX", self.ask("tell me what's currently running on my laptop"))
        self.ask("open opera on my laptop")
        self.assertEqual(self.calls[-1], ("open_app", ("opera",)))

    def test_discord_class_group_needs_the_bot(self):
        from jarvis.tools import discord
        with mock.patch.object(discord, "connected", lambda: False):
            self.assertIn("bot", self.ask("open discord and check my class group"))
        self.assertEqual(self.calls[-1], ("open_app", ("discord",)))
        with mock.patch.object(discord, "connected", lambda: True), \
                mock.patch.object(discord, "selected_channels", lambda: ["general", "class-10b"]), \
                mock.patch.object(discord, "read_channel", lambda n, k=20: {"messages": [{"author": "Ms Rao", "text": "Test on Friday"}]}):
            self.assertIn("Test on Friday", self.ask("check my class group on discord"))

    def test_recent_files_phrase(self):
        from jarvis.tools import files
        self.assertEqual(files.parse("find the presentation i was working on yesterday"), "the presentation i was working on yesterday")
        self.assertIsNotNone(files._since("the presentation i was working on yesterday"))
        self.assertIsNone(files._since("my tokyo notes"))


class BackgroundTests(unittest.TestCase):
    def test_autostart_shortcut(self):
        from jarvis import autostart
        tmp = Path(tempfile.mkdtemp()) / "Jarvis.lnk"
        with mock.patch.object(autostart, "SHORTCUT", tmp):
            self.assertFalse(autostart.enabled())
            autostart.enable()
            self.assertTrue(tmp.exists())
            autostart.disable()
            self.assertFalse(tmp.exists())

    def test_keep_awake_only_when_plugged_in(self):
        from jarvis import power
        with mock.patch.object(power.psutil, "sensors_battery", lambda: mock.Mock(percent=80, power_plugged=False)):
            self.assertFalse(power.plugged_in())
        with mock.patch.object(power.psutil, "sensors_battery", lambda: None):
            self.assertTrue(power.plugged_in())  # a desktop PC


class PhoneControlTests(RouterBase):
    """Phone commands go to KDE Connect (mocked here); nothing tries to get around Android's security."""

    def setUp(self):
        super().setUp()
        from jarvis.tools import phone
        self.phone, self.sent = phone, []

        def fake_run(*args, timeout=20):
            self.sent.append(args)
            if args == ("-l",):
                return 0, "- POCO F1: abc123 on 192.168.0.5 via LAN (paired and reachable)\n- Old phone: def456 (paired)", ""
            if "--list-notifications" in args:
                return 0, "- WhatsApp: Sam\n- WhatsApp: Class 10B group\n- Gmail: Science homework\n- YouTube: New video", ""
            return 0, "", ""
        p = mock.patch.object(phone, "_run", fake_run)
        p.start()
        self.addCleanup(p.stop)
        phone._cache.update(at=0, devices=[])

    def test_devices_parsed(self):
        self.assertEqual(self.phone.devices(refresh=True), [{"id": "abc123", "name": "POCO F1", "reachable": True},
                                                            {"id": "def456", "name": "Old phone", "reachable": False}])

    def test_unlock_is_refused(self):
        self.assertIn("can't unlock", self.ask("unlock my phone"))
        self.assertFalse(any("--unlock" in a for a in self.sent))

    def test_find_and_open(self):
        self.assertIn("Ringing your POCO F1", self.ask("find my phone"))
        self.assertIn(("-d", "abc123", "--ring"), self.sent)
        self.assertIn("Opening WhatsApp on your POCO F1", self.ask("open whatsapp on my phone"))
        self.ask("open youtube on my phone")
        self.assertEqual(self.sent[-1], ("-d", "abc123", "--share", "https://www.youtube.com"))
        self.assertNotIn("youtube", [c[0] for c in self.calls])  # the laptop didn't open YouTube
        self.ask("open youtube and search for lofi beats on my phone")
        self.assertEqual(self.sent[-1][-1], "https://www.youtube.com/results?search_query=lofi+beats")

    def test_calls_open_the_chat(self):
        with mock.patch.dict(settings._data, {"whatsapp_contacts": {"Sam": "971500000000"}}):
            reply = self.ask("call sam on whatsapp")
        self.assertIn("Tap the call button", reply)
        self.assertEqual(self.sent[-1][-1], "https://wa.me/971500000000")
        self.assertIn("isn't in your saved WhatsApp contacts", self.ask("call alex on whatsapp"))
        self.assertIn("Discord doesn't let other apps start calls", self.ask("call alex on discord"))

    def test_notifications(self):
        self.assertIn("4 notifications", self.ask("check my latest notifications"))
        reply = self.ask("who messaged me recently")
        self.assertIn("WhatsApp: Sam, Class 10B group", reply)
        self.assertIn("Gmail: Science homework", reply)
        self.assertNotIn("New video", reply)  # only messaging apps

    def test_unreachable_phone_is_reported(self):
        def offline(*args, timeout=20):
            return (0, "- POCO F1: abc123 (paired)", "") if args == ("-l",) else (0, "", "")
        with mock.patch.object(self.phone, "_run", offline):
            self.phone._cache.update(at=0, devices=[])
            self.assertIn("can't reach your POCO F1", self.ask("find my phone"))


class AgentTests(unittest.TestCase):
    """The background agent, with every source and the AI faked."""

    def setUp(self):
        import datetime as dt
        from jarvis.agent import core, sources, triage
        self.dt, self.core, self.sources, self.triage = dt, core, sources, triage
        self.store = Store(Path(tempfile.mkdtemp()) / "t.db")
        self.notes, self.cards, self.sent_to_ai = [], [], []
        self.agent = core.Agent(self.store, lambda text, important=False: self.notes.append((text, important)),
                                lambda item, text: self.cards.append((item["ext_id"], text)))
        values = {"agent_school_senders": "@school.edu\nClass 10B", "agent_last_run": 0}
        p = mock.patch.object(settings, "get", lambda k, d=None: values.get(k, settings._data.get(k, d)))
        p.start()
        self.addCleanup(p.stop)
        u = mock.patch.object(settings, "update", lambda v: values.update(v))
        u.start()
        self.addCleanup(u.stop)
        self.items = [
            {"source": "gmail", "ext_id": "m1", "sender": "Ms Rao", "address": "rao@school.edu", "title": "Science project",
             "text": "Prepare a 10-slide presentation about renewable energy for next Thursday."},
            {"source": "gmail", "ext_id": "m2", "sender": "Shop", "address": "deals@shop.com", "title": "50% off", "text": "Sale!"},
            {"source": "phone", "ext_id": "WhatsApp|Class 10B|d", "sender": "Class 10B", "group": "Class 10B",
             "title": "WhatsApp: Class 10B", "text": ""},
        ]

        def fake_triage(batch, today=None):
            self.sent_to_ai.append([it["ext_id"] for it in batch])
            return {0: {"category": "assignment", "importance": 4, "summary": "Science presentation on renewable energy",
                        "deadline": "2026-11-19", "needs_reply": True, "reply": "Thank you, I'll have it ready.",
                        "task": {"title": "Science presentation: renewable energy", "type": "presentation",
                                 "requirements": "10 slides", "due": "2026-11-19"}},
                    1: {"category": "announcement", "importance": 2, "summary": "Class group chat", "deadline": None,
                        "needs_reply": False, "reply": None, "task": None}}
        self.patches = [mock.patch.object(sources, "COLLECTORS", {"fake": (lambda: True, lambda: [dict(i) for i in self.items])}),
                        mock.patch.object(triage, "triage", fake_triage),
                        mock.patch.object(core.ai, "agent_may_use", lambda n=1: True),
                        mock.patch.object(core.google, "read_mail", lambda i: {"body": "full text"})]
        for x in self.patches:
            x.start()
            self.addCleanup(x.stop)

    def test_only_school_items_reach_the_ai(self):
        summary = self.agent.run()
        self.assertEqual(self.sent_to_ai, [["m1", "WhatsApp|Class 10B|d"]])  # the shop email never goes to the AI
        self.assertIn("3 new items", summary)
        self.assertIn("2 from school", summary)
        tasks = self.store.tasks()
        self.assertEqual([(t["title"], t["kind"], t["due"]) for t in tasks],
                         [("Science presentation: renewable energy", "presentation", "2026-11-19")])
        self.assertEqual(self.cards, [("m1", "Thank you, I'll have it ready.")])  # a draft card, never sent by itself
        self.assertTrue(any("New task" in n and imp for n, imp in self.notes))
        # a second run sees nothing new and adds nothing twice
        self.agent.run()
        self.assertEqual(len(self.sent_to_ai), 1)
        self.assertEqual(len(self.store.tasks()), 1)

    def test_out_of_budget_waits(self):
        with mock.patch.object(self.core.ai, "agent_may_use", lambda n=1: False):
            summary = self.agent.run()
        self.assertEqual(self.sent_to_ai, [])
        self.assertIn("2 waiting for AI budget", summary)
        self.assertFalse(self.store.seen("gmail", "m1"))  # retried later
        self.assertTrue(self.store.seen("gmail", "m2"))   # non-school: just counted

    def test_reminders_once(self):
        tomorrow = (self.dt.date(2026, 11, 13)).isoformat()
        self.store.add_task("Maths worksheet", due=tomorrow)
        at = self.dt.datetime(2026, 11, 12, 17, 0)
        self.agent.reminders(at)
        self.agent.reminders(at)
        self.assertEqual([n for n, _ in self.notes], ["Reminder: Maths worksheet is due tomorrow."])

    def test_school_matching(self):
        pats = ["@school.edu", "class 10b"]
        self.assertTrue(self.sources.is_school({"source": "gmail", "address": "x@school.edu"}, pats))
        self.assertTrue(self.sources.is_school({"source": "classroom"}, []))
        self.assertFalse(self.sources.is_school({"source": "gmail", "address": "x@gmail.com", "sender": "Bob"}, pats))


class TriageParsingTests(unittest.TestCase):
    def test_dates(self):
        import datetime as dt
        from jarvis.agent import dates
        today = dt.date(2026, 11, 12)  # a Thursday
        self.assertEqual(dates.parse("by Thursday", today), "2026-11-19")
        self.assertEqual(dates.parse("tomorrow", today), "2026-11-13")
        self.assertEqual(dates.parse("next week", today), "2026-11-16")
        self.assertEqual(dates.parse("20 Nov", today), "2026-11-20")
        self.assertEqual(dates.parse("Dec 3rd", today), "2026-12-03")
        self.assertEqual(dates.parse("5/1", today), "2026-01-05")
        self.assertIsNone(dates.parse("the sun is a star", today))
        self.assertEqual(dates.say("2026-11-13", today), "tomorrow")
        self.assertTrue(dates.say("2026-11-10", today).startswith("overdue"))
        self.assertGreater(dates.priority({"due": "2026-11-13", "importance": 3}, today),
                           dates.priority({"due": "2026-12-20", "importance": 3}, today))

    def test_json_from_messy_replies(self):
        from jarvis import ai
        self.assertEqual(ai.parse_json('Sure!\n```json\n[{"i": 1, "summary": "say \\"hi\\" [ok]"}]\n```'),
                         [{"i": 1, "summary": 'say "hi" [ok]'}])
        with self.assertRaises(ValueError):
            ai.parse_json("no json here")
        with self.assertRaises(ValueError):
            ai.parse_json('[{"i": 1, "summary": "cut')

    def test_bad_results_are_dropped(self):
        from jarvis.agent import triage
        out = triage._clean([{"i": 1, "category": "assignment", "importance": 9, "deadline": "2026-11-19",
                              "task": {"title": "Essay", "type": "poem", "due": None}},
                             {"i": 7, "category": "test"}, "junk", {"i": 2, "category": "weird", "needs_reply": True}], 2)
        self.assertEqual(out[1]["importance"], 5)
        self.assertEqual(out[1]["task"]["type"], "other")
        self.assertEqual(out[1]["task"]["due"], "2026-11-19")  # falls back to the item's deadline
        self.assertEqual(out[2]["category"], "info")
        self.assertIsNone(out[2]["reply"])
        self.assertNotIn(7, out)

    def test_budget(self):
        from jarvis import ai
        tmp = Path(tempfile.mkdtemp()) / "usage.json"
        values = {"ai_daily_limit": 50, "agent_daily_budget": 25, "ai_chat_reserve": 15}
        with mock.patch.object(ai, "USAGE_FILE", tmp), mock.patch.object(ai.providers, "is_cloud", lambda: True), \
                mock.patch.object(ai.providers, "available", lambda: True), \
                mock.patch.object(settings, "get", lambda k, d=None: values.get(k, settings._data.get(k, d))):
            self.assertTrue(ai.agent_may_use())
            for _ in range(25):
                ai.count("agent")
            self.assertFalse(ai.agent_may_use())  # its own share used up
            values["agent_daily_budget"] = 100
            for _ in range(10):
                ai.count("chat")
            self.assertFalse(ai.agent_may_use())  # 35 used: the last 15 stay for chat
            values["ai_daily_limit"] = 1000
            self.assertTrue(ai.agent_may_use())
            ai.mark_exhausted()
            self.assertFalse(ai.agent_may_use())


class TaskCommandTests(RouterBase):
    def setUp(self):
        super().setUp()
        from jarvis.agent.core import Agent
        self.brain.agent = Agent(self.brain.store, lambda *a, **k: None)

    def test_add_list_and_finish(self):
        self.assertIn("due", self.ask("add a task maths worksheet by friday"))
        self.assertIn("Added Call gran", self.ask("remind me to call gran tomorrow"))
        reply = self.ask("what's due")
        self.assertIn("2 open tasks", reply)
        self.assertIn("Maths worksheet", reply)
        self.assertIn("Marked Maths worksheet as done", self.ask("mark the maths worksheet as done"))
        self.assertIn("1 open task", self.ask("what are my tasks"))
        self.assertIn("couldn't find a task", self.ask("i've finished the history essay"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
