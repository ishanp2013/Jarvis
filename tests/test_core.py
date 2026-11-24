"""Core tests. Run:  run_tests.bat   (no apps are opened or closed: desktop actions are mocked)."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from jarvis import ai, speech
from jarvis.brain import Brain, TOOLS
from jarvis.config import settings
from jarvis.storage import Store, redact
from jarvis.tools import windows as win

# Tests never touch your real daily AI count (they used to add to it and shrink your free budget).
ai.USAGE_FILE = Path(tempfile.mkdtemp()) / "ai_usage.json"


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

    def test_whatsapp_read_questions(self):
        from jarvis.tools import whatsapp as wa
        cases = {
            "has sam send any replies to my message in whatsapp?": ("reply", "sam"),
            "has Sam replied on WhatsApp": ("reply", "Sam"),
            "did ms rao text me back on whatsapp": ("reply", "ms rao"),
            "any reply from Sam Lee on whatsapp?": ("reply", "Sam Lee"),
            "what did sam say on whats app": ("chat", "sam"),
            "read my chat with Sam on whatsapp": ("chat", "Sam"),
            "has sam seen my message on whatsapp": ("seen", "sam"),
            "did sam read my message on whatsapp": ("seen", "sam"),
            "read my whatsapp messages": ("summary", None),
            "check whatsapp": ("summary", None),
            "do i have any new messages on whatsapp": ("summary", None),
            "has anyone messaged me on whatsapp": ("summary", None),
        }
        for text, want in cases.items():
            self.assertEqual(wa.parse_read(text), want, text)
        for text in ("send hi to sam on whatsapp", "has sam replied to my email", "open whatsapp"):
            self.assertIsNone(wa.parse_read(text), text)

    def test_whatsapp_chat_rows(self):
        from jarvis.tools import whatsapp as wa
        r = wa.parse_row("2 unread messages Sam Lee 9:41 PM", ["2 unread messages", "Sam Lee", "9:41 PM", "see you at 5"])
        self.assertEqual((r["chat"], r["time"], r["unread"], r["sender"], r["text"], r["from_me"]),
                         ("Sam Lee", "9:41 PM", 2, "", "see you at 5", False))
        r = wa.parse_row("Mum 🌸 21/11/2026", ["Mum ", "🌸", "21/11/2026", "You", ": ", "ok"])
        self.assertEqual((r["chat"], r["time"], r["from_me"], r["text"]), ("Mum 🌸", "21/11/2026", True, "ok"))
        r = wa.parse_row("Class 9B 10:02 AM", ["Class 9B", "10:02 AM", "~ Ana", ": ", "Note: test ", "🔥"])
        self.assertEqual((r["sender"], r["text"]), ("Ana", "Note: test 🔥"))
        r = wa.parse_row("Sam Yesterday", ["Sam", "Yesterday", "Note: bring a pen"])  # a colon in a 1:1 message
        self.assertEqual((r["sender"], r["text"], r["time"]), ("", "Note: bring a pen", "Yesterday"))
        # the latest thing can be a reaction to your message, not a reply
        r = wa.parse_row("Sam Yesterday", ["Sam", "Yesterday", "Reacted ", "👍", " to:", "\xa0", '"', 'see you at 5"'])
        self.assertEqual((r["reaction"], r["reacted_to"], r["from_me"]), ("👍", "see you at 5", False))
        self.assertTrue(wa.reply_status("sam", [r]).startswith("No written reply, but Sam reacted 👍"))

    def test_whatsapp_whole_chat(self):
        from jarvis.tools import whatsapp as wa
        tokens = [("t", "Today"), ("t", "~ "), ("t", "hello there"), ("t", "9:01 PM"),
                  ("me", "You:"), ("t", "hi! "), ("t", "😀"), ("t", "9:02 PM"), ("status", " Read "),
                  ("t", "are you coming?"), ("t", "9:05 PM"),
                  ("me", "You:"), ("t", "yes"), ("t", "9:06 PM"), ("status", " Delivered ")]
        msgs = wa.parse_messages(tokens)
        self.assertEqual([(m["me"], m["text"], m["time"], m["status"]) for m in msgs], [
            (False, "hello there", "9:01 PM", ""), (True, "hi! 😀", "9:02 PM", "Read"),
            (False, "are you coming?", "9:05 PM", ""), (True, "yes", "9:06 PM", "Delivered")])
        self.assertEqual(msgs[0]["day"], "Today")
        data = {"chat": "Sam", "messages": msgs, "was_unread": 0, "row": {}}
        self.assertTrue(wa.chat_reply_status("sam", data).startswith("No reply yet. Your last message at 9:06 PM"))
        self.assertIn("delivered but not read", wa.chat_reply_status("sam", data))
        self.assertTrue(wa.chat_seen_status("sam", data).startswith("Not yet: it's delivered but not read"))
        replied = dict(data, messages=msgs[:3])
        self.assertTrue(wa.chat_reply_status("sam", replied).startswith('Yes. Sam replied at 9:05 PM: "are you coming?"'))
        self.assertTrue(wa.chat_seen_status("sam", replied).startswith("Yes, they've read it"))
        reacted = dict(data, row={"reaction": "👍", "from_me": False})
        self.assertIn("They reacted 👍 to it", wa.chat_reply_status("sam", reacted))
        self.assertIn('Sam at 9:05 PM: "are you coming?"', wa.chat_recap("sam", data))

    def test_whatsapp_reply_answers(self):
        from jarvis.tools import whatsapp as wa
        row = lambda chat, sender="", text="hi", unread=0: {"chat": chat, "time": "9:41 PM", "unread": unread, "sender": sender,
                                                             "text": text, "from_me": sender == "You"}
        chats = [row("Sam Lee", text="see you at 5", unread=1), row("Surya Ma'am", "You", "did you check it?"), row("Class 9B", "Ana")]
        self.assertTrue(wa.reply_status("sam", chats).startswith("Yes. The latest message is from Sam Lee at 9:41 PM"))
        self.assertIn("1 unread", wa.reply_status("Sam Lee", chats))
        self.assertTrue(wa.reply_status("suriya mam", chats).startswith("Not yet."))
        self.assertIn("don't see a chat with Bob", wa.reply_status("Bob", chats))
        self.assertIn("1 unread WhatsApp message in 1 chat", wa.summary(chats))
        self.assertIn("No unread", wa.summary([row("Sam")]))
        # the quick route answers locally (no AI) and never reads when switched off
        with mock.patch.object(wa, "recent_chats", lambda: chats):
            self.assertIn("Sam Lee", self.ask("check my whatsapp"))
        chat = {"chat": "Sam Lee", "was_unread": 0, "row": {}, "messages": [
            {"me": True, "text": "free tomorrow?", "time": "9:00 PM", "day": "", "status": "Read"},
            {"me": False, "text": "yes", "time": "9:41 PM", "day": "", "status": ""}]}
        with mock.patch.object(wa, "read_chat", lambda name: chat):
            self.assertIn('Sam Lee replied at 9:41 PM: "yes"', self.ask("has sam replied on whatsapp?"))
            self.assertIn("they've read it", self.ask("has sam seen my message on whatsapp?"))
        with mock.patch.dict(settings._data, {"whatsapp_read": False}):
            self.assertIn("turned off", self.ask("has sam replied on whatsapp?"))
        team_mod = __import__("jarvis.team", fromlist=["x"])
        self.assertEqual((team_mod.owner_of("whatsapp_chats"), team_mod.owner_of("whatsapp_read_chat")), ("herald", "herald"))

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


class FishVoiceTests(unittest.TestCase):
    """Fish Audio's text-to-speech request, against a fake server."""

    def test_request_and_errors(self):
        sent = []

        def fake_post(url, json=None, headers=None, timeout=None):
            sent.append((url, json, headers))
            return mock.Mock(status_code=200, content=b"mp3")
        values = {"fish_voice_id": "https://fish.audio/m/0123456789abcdef0123456789ABCDEF/", "fish_model": "s2.1-pro-free",
                  "fish_speed": 1.1}
        with mock.patch.object(speech, "get_secret", lambda n: "fish-key" if n == "fish_api_key" else ""), \
                mock.patch.object(settings, "get", lambda k, d=None: values.get(k, settings._data.get(k, d))), \
                mock.patch.object(speech.httpx, "post", fake_post), \
                mock.patch.object(speech, "_decode_mp3", lambda b: ("audio", 24000)):
            self.assertEqual(speech.synth_fish("Good evening."), ("audio", 24000))
            url, body, headers = sent[0]
            self.assertEqual(url, "https://api.fish.audio/v1/tts")
            self.assertEqual((headers["Authorization"], headers["model"]), ("Bearer fish-key", "s2.1-pro-free"))
            self.assertEqual((body["text"], body["reference_id"], body["format"]),
                             ("Good evening.", "0123456789abcdef0123456789abcdef", "mp3"))
            self.assertEqual(body["prosody"], {"speed": 1.1})
            values["fish_voice_id"] = ""  # no voice chosen: Fish's default
            speech.synth_fish("hi")
            self.assertNotIn("reference_id", sent[-1][1])
            with mock.patch.object(speech.httpx, "post", lambda *a, **k: mock.Mock(status_code=402, text="")):
                with self.assertRaisesRegex(RuntimeError, "free credits are used up"):
                    speech.synth_fish("hi")
        with mock.patch.object(speech, "get_secret", lambda n: ""):
            with self.assertRaisesRegex(RuntimeError, "key not set"):
                speech.synth_fish("hi")
        self.assertIn("fish", speech.PROVIDERS)


class BackupTests(unittest.TestCase):
    """When a model hits its limit, Jarvis carries on with the next backup, with the same conversation."""

    def setUp(self):
        from jarvis import providers
        self.providers = providers
        ai.USAGE_FILE.unlink(missing_ok=True)
        self.addCleanup(lambda: ai.USAGE_FILE.unlink(missing_ok=True))
        self.values = {"llm_provider": "openrouter", "private_mode": False, "team_mode": False, "llm_backups": [
            {"id": "aaaa1", "provider": "bazaarlink", "model": ""}, {"id": "bbbb2", "provider": "orcarouter", "model": ""},
            {"id": "cccc3", "provider": "groq", "model": ""}]}
        self.keys = {"openrouter_api_key", "bazaarlink_api_key", "orcarouter_api_key"}  # groq has no key
        for p in (mock.patch.object(settings, "get", lambda k, d=None: self.values.get(k, settings._data.get(k, d))),
                  mock.patch.object(providers, "get_secret", lambda n: "k" if n in self.keys else "")):
            p.start()
            self.addCleanup(p.stop)
        self.brain, self.events, _ = make_brain()
        self.brain.store.add_message("user", "my exam is on friday")
        self.brain.store.add_message("assistant", "Noted.")
        self.brain.store.add_message("user", "when is my exam?")
        self.calls = []
        self.fail = {"openrouter": RuntimeError("429: Rate limit exceeded: free-models-per-day")}

        def loop(text, sources):
            n = providers.name()
            self.calls.append((n, text, [m["text"] for m in self.brain._history()]))
            if n in self.fail:
                raise self.fail[n]
            return f"Friday (from {n})"
        p = mock.patch.object(self.brain, "_provider_loop", lambda: loop)
        p.start()
        self.addCleanup(p.stop)

    def test_chain_order_skips_missing_keys(self):
        self.assertEqual(self.providers.chain(), ["openrouter", "backup:aaaa1", "backup:bbbb2"])
        # the same service again with the same key and model: skipped; with its own key: a separate backup
        self.values["llm_backups"].append({"id": "dddd4", "provider": "openrouter", "model": ""})
        self.assertEqual(self.providers.chain(), ["openrouter", "backup:aaaa1", "backup:bbbb2"])
        self.keys.add("backup_dddd4_api_key")
        self.assertEqual(self.providers.chain()[-1], "backup:dddd4")
        p = self.providers.resolve("backup:dddd4")
        self.assertEqual((p["key"], p["label"], p["provider"]), ("backup_dddd4_api_key", "OpenRouter (backup 4)", "openrouter"))
        # a backup's own model
        self.values["llm_backups"][0]["model"] = "qwen/qwen3.7-flash:free"
        self.assertEqual(self.providers.model(self.providers.resolve("backup:aaaa1")), "qwen/qwen3.7-flash:free")
        self.assertEqual(self.providers.model(self.providers.resolve("backup:bbbb2")), settings._data.get("orcarouter_model", "orcarouter/free"))

    def test_switches_with_the_same_conversation(self):
        reply, _ = self.brain._llm("when is my exam?")
        self.assertEqual(reply, "Friday (from backup:aaaa1)")
        self.assertEqual([c[0] for c in self.calls], ["openrouter", "backup:aaaa1"])
        self.assertEqual(self.calls[0][1:], self.calls[1][1:])  # same request, same history
        self.assertIn("my exam is on friday", self.calls[1][2])
        self.assertTrue(ai.is_down("openrouter"))
        self.assertEqual(ai.active(), "backup:aaaa1")
        self.calls.clear()
        self.brain._llm("thanks")  # the resting one isn't tried again today
        self.assertEqual([c[0] for c in self.calls], ["backup:aaaa1"])
        self.assertTrue(any("Switching to BazaarLink (backup 1)" in str(e[1]) for e in self.events if e[0] == "activity"))

    def test_all_resting_says_limit(self):
        self.fail.update({n: RuntimeError("429 too many requests") for n in ("backup:aaaa1", "backup:bbbb2")})
        reply, _ = self.brain._llm("hi")
        self.assertIn("usage limit", reply)
        self.assertEqual([c[0] for c in self.calls], ["openrouter", "backup:aaaa1", "backup:bbbb2"])
        self.assertTrue(ai.usage()["exhausted"])

    def test_no_switch_for_other_errors_or_after_a_tool_ran(self):
        self.fail["openrouter"] = RuntimeError("something odd")
        reply, _ = self.brain._llm("hi")
        self.assertIn("failed", reply)
        self.assertEqual([c[0] for c in self.calls], ["openrouter"])
        # a tool already ran (it may have sent or changed something): no repeat on a backup
        self.calls.clear()

        def acted(text, sources):
            self.brain._tool_runs = 1
            raise RuntimeError("402 insufficient credits")
        with mock.patch.object(self.brain, "_provider_loop", lambda: acted):
            reply, _ = self.brain._llm("send it")
        self.assertIn("switched to BazaarLink", reply)
        self.assertTrue(ai.is_down("openrouter"))

    def test_background_requests_use_backups(self):
        def one(system, prompt, kind, max_tokens, agent):
            if self.providers.name() == "openrouter":
                raise RuntimeError("OpenRouter's limit has been reached (429): per-day")
            return "summary by " + self.providers.name()
        with mock.patch.object(ai, "_complete_one", one):
            self.assertEqual(ai.complete("s", "p", kind="chat"), "summary by backup:aaaa1")
            self.values["llm_backups"] = []
            ai.USAGE_FILE.unlink(missing_ok=True)
            with self.assertRaises(ai.OutOfBudget):
                ai.complete("s", "p", kind="chat")

    def test_old_three_slot_settings_still_work(self):
        self.values.pop("llm_backups")
        self.values.update({"llm_backups": None, "llm_backup_1": "orcarouter", "llm_backup_2": ""})
        self.assertEqual(self.providers.chain(), ["openrouter", "backup:old1"])

    def test_backup_keys_are_allowed_secrets(self):
        from jarvis import config
        with mock.patch.object(config.keyring, "set_password", lambda *a: None):
            config.set_secret("backup_ab12cd34_api_key", "x")
            with self.assertRaises(ValueError):
                config.set_secret("backup_../evil_api_key", "x")

    def test_failure_kinds(self):
        import httpx
        cases = {"429: free-models-per-day": "daily", "Error 429 Too Many Requests": "limit", "402 Payment Required": "credit",
                 "401 invalid API key": "key", "404 model not found": "model", "boom": None}
        for msg, kind in cases.items():
            self.assertEqual(ai.failure_kind(RuntimeError(msg)), kind, msg)
        self.assertEqual(ai.failure_kind(httpx.ConnectError("x")), "network")


class ProviderTests(unittest.TestCase):
    """Each AI provider's request format, against a fake server: a tool call, then a final answer."""

    def setUp(self):
        self.brain, _, _ = make_brain()
        self.ran = []
        self.patch = mock.patch.dict(TOOLS["system_info"], fn=lambda: self.ran.append("system_info") or {"cpu_percent": 5})
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def use(self, provider):
        values = {"llm_provider": provider, "private_mode": False, "team_mode": False}  # each provider's format, one AI
        p = mock.patch.object(settings, "get", lambda k, d=None: values.get(k, settings._data.get(k, d)))
        p.start()
        self.addCleanup(p.stop)
        k = mock.patch("jarvis.providers.get_secret", lambda name: "test-key")
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
        with mock.patch.dict(settings._data, {"follow_up_seconds": 6}):  # not your own setting, which may be off
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
        fake = {"name": "Rocket LeagueÂ®", "store": "Epic", "launch": "x", "folder": ""}
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

        def fake_llm(text, direct=None):
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
               ("Rocket LeagueÂ®", "Fall Guys", "Five Nights at Freddy's: Into the Pit", "Grand Theft Auto V")]
        with mock.patch.object(games, "installed", lambda refresh=False: lib):
            self.assertEqual(games.find("rocket league")["name"], "Rocket LeagueÂ®")
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
                return 0, "- Pixel 8: abc123 on 192.168.0.5 via LAN (paired and reachable)\n- Old phone: def456 (paired)", ""
            if "--list-notifications" in args:
                return 0, "- WhatsApp: Sam\n- WhatsApp: Class 10B group\n- Gmail: Science homework\n- YouTube: New video", ""
            return 0, "", ""
        p = mock.patch.object(phone, "_run", fake_run)
        p.start()
        self.addCleanup(p.stop)
        phone._cache.update(at=0, devices=[])

    def test_devices_parsed(self):
        self.assertEqual(self.phone.devices(refresh=True), [{"id": "abc123", "name": "Pixel 8", "reachable": True},
                                                            {"id": "def456", "name": "Old phone", "reachable": False}])

    def test_unlock_is_refused(self):
        self.assertIn("can't unlock", self.ask("unlock my phone"))
        self.assertFalse(any("--unlock" in a for a in self.sent))

    def test_find_and_open(self):
        self.assertIn("Ringing your Pixel 8", self.ask("find my phone"))
        self.assertIn(("-d", "abc123", "--ring"), self.sent)
        self.assertIn("Opening WhatsApp on your Pixel 8", self.ask("open whatsapp on my phone"))
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
            return (0, "- Pixel 8: abc123 (paired)", "") if args == ("-l",) else (0, "", "")
        with mock.patch.object(self.phone, "_run", offline):
            self.phone._cache.update(at=0, devices=[])
            self.assertIn("can't reach your Pixel 8", self.ask("find my phone"))


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

    def test_personal_todos_reach_the_task_list(self):
        self.items = [
            {"source": "gmail", "ext_id": "p1", "sender": "Sam", "address": "sam@gmail.com", "title": "photos",
             "text": "Can you send me the trip photos by Friday?"},
            {"source": "whatsapp", "ext_id": "Mum|9:41 PM|buy milk", "sender": "Mum", "group": "Mum",
             "title": "WhatsApp: Mum", "text": "Buy milk on the way home"},
            {"source": "gmail", "ext_id": "p3", "sender": "GitHub", "address": "notifications@github.com", "title": "PR", "text": "x"},
        ]
        prepared = []
        self.agent.on_task = prepared.append

        def fake_triage(batch, today=None):
            self.sent_to_ai.append([it["ext_id"] for it in batch])
            self.assertEqual([it["school"] for it in batch], [False, False])
            return {i: {"category": "request", "importance": 3, "summary": "", "deadline": None, "needs_reply": True,
                        "reply": "ok", "task": {"title": t, "type": "other", "requirements": "", "due": None}}
                    for i, t in enumerate(["Send Sam the trip photos", "Buy milk"])}
        with mock.patch.object(self.triage, "triage", fake_triage):
            summary = self.agent.run()
        self.assertEqual(self.sent_to_ai, [["p1", "Mum|9:41 PM|buy milk"]])  # the GitHub notification never goes
        self.assertIn("2 personal checked for to-dos", summary)
        self.assertEqual(sorted((t["title"], t["source"]) for t in self.store.tasks()),
                         [("Buy milk", "whatsapp"), ("Send Sam the trip photos", "gmail")])
        self.assertEqual(self.cards, [])     # no reply drafts for personal mail
        self.assertEqual(prepared, [])       # Forge only prepares school work
        self.assertTrue(any("New task: Buy milk" in n for n, _ in self.notes))

    def test_personal_todos_can_be_switched_off(self):
        self.items = [{"source": "gmail", "ext_id": "p1", "sender": "Sam", "address": "sam@gmail.com", "title": "photos",
                       "text": "Can you send me the trip photos by Friday?"}]
        with mock.patch.object(settings, "get", lambda k, d=None: False if k == "agent_personal_todos" else settings._data.get(k, d)):
            self.agent.run()
        self.assertEqual(self.sent_to_ai, [])
        self.assertTrue(self.store.seen("gmail", "p1"))

    def test_whatsapp_source(self):
        chats = [{"chat": "Sam", "time": "9:41 PM", "unread": 2, "sender": "", "text": "bring the charger tomorrow", "from_me": False},
                 {"chat": "Ali", "time": "9:00 PM", "unread": 0, "sender": "", "text": "ok", "from_me": True},
                 {"chat": "Zoe", "time": "8:00 PM", "unread": 0, "sender": "", "text": "Reacted 👍 to: \"hi\"",
                  "from_me": False, "reaction": "👍"}]
        with mock.patch.object(self.sources, "_whatsapp_quiet", lambda: True), \
                mock.patch.object(self.sources.whatsapp, "recent_chats", lambda: chats):
            items = self.sources._whatsapp()
        self.assertEqual([(i["source"], i["group"], i["text"]) for i in items], [("whatsapp", "Sam", "bring the charger tomorrow")])
        with mock.patch.object(self.sources, "_whatsapp_quiet", lambda: False), \
                mock.patch.object(self.sources.whatsapp, "recent_chats", lambda: self.fail("shouldn't pop WhatsApp up")):
            self.assertEqual(self.sources._whatsapp(), [])  # you're using the PC: tried again next time

    def test_automated_mail_is_skipped(self):
        ok = lambda a: self.sources.worth_reading({"source": "gmail", "address": a, "text": "hi"})
        self.assertTrue(ok("sam@gmail.com"))
        self.assertTrue(ok("newsome.k@gmail.com"))
        for a in ("noreply@x.com", "no-reply@x.com", "notifications@github.com", "news@bbc.co.uk", "info@shop.com",
                  "deals@shop.com", "mailer-daemon@google.com"):
            self.assertFalse(ok(a), a)
        self.assertFalse(self.sources.worth_reading({"source": "whatsapp", "text": "hi", "from_me": True}))

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
        # Classroom's own emails, forwarded from a school account that can't be connected: always school
        self.assertTrue(self.sources.is_school({"source": "gmail", "address": "no-reply@classroom.google.com"}, []))
        self.assertFalse(self.sources.is_school({"source": "gmail", "address": "x@classroom.google.com.evil.com"}, []))

    def test_forwarded_classroom_mail_is_fetched_once(self):
        from jarvis.tools import google
        mail = lambda i, addr: {"id": i, "from": "Ms Rao (Classroom)", "from_address": addr, "subject": f"New assignment {i}",
                                "preview": "Due Nov 28", "received": "2026-11-24"}
        results = {"in:inbox newer_than:3d": [mail("a", "no-reply@classroom.google.com"), mail("b", "friend@gmail.com")],
                   "from:classroom.google.com newer_than:7d -in:trash -in:spam": [mail("a", "no-reply@classroom.google.com"),
                                                                                 mail("c", "no-reply@classroom.google.com")]}
        with mock.patch.object(google, "search_mail", lambda q, n: results[q]):
            items = self.sources._gmail()
        self.assertEqual([i["ext_id"] for i in items], ["a", "b", "c"])
        self.assertEqual([self.sources.is_school(i, []) for i in items], [True, False, True])


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
                mock.patch.object(ai.providers, "chain", lambda: ["openrouter"]), \
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


class WorkerTests(unittest.TestCase):
    """Prepared work end to end with a fake AI and fake research: real files are built and read back."""

    def setUp(self):
        import json
        from jarvis.agent import worker
        self.worker_mod = worker
        self.store = Store(Path(tempfile.mkdtemp()) / "t.db")
        self.out = Path(tempfile.mkdtemp())
        self.notes = []
        self.w = worker.Worker(self.store, lambda text, important=False: self.notes.append(text))
        self.replies = []
        self.patches = [
            mock.patch.object(worker, "output_dir", lambda: self.out),
            mock.patch.object(worker.ai, "complete", lambda system, prompt, kind="agent", max_tokens=0, agent=None:
                              json.dumps(self.replies.pop(0))),
            mock.patch.object(worker.ai, "agent_may_use", lambda n=1: True),
            mock.patch.object(worker.research, "gather", lambda topic, queries, **k: [
                {"n": 1, "title": "Renewable energy - Wikipedia", "url": "https://en.wikipedia.org/wiki/Renewable_energy",
                 "text": "Hydropower supplies about 14% of world electricity, wind about 8% and solar about 5%."}]),
            mock.patch.object(worker.research, "image", lambda q, folder, name: None),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def _job(self, kind, title, req, task_id=None):
        jid = self.store.add_job(kind, title, {"requirements": req}, task_id)
        self.w._run(self.store.job(jid))
        return self.store.job(jid)

    def test_ten_slide_presentation(self):
        outline = [{"title": f"Slide {i}", "layout": "bullets", "point": f"point {i}"} for i in range(1, 9)]
        slides = [{"title": f"Slide {i}", "layout": "bullets", "bullets": [f"Fact {i}a", f"Fact {i}b"], "notes": "Say this [1]."}
                  for i in range(1, 8)]  # one short: the worker must still deliver the right count
        slides[2] = {"title": "Electricity share", "layout": "chart", "bullets": ["Hydro leads"],
                     "chart": {"type": "bar", "categories": ["Hydro", "Wind", "Solar"], "series": [{"name": "%", "values": [14, 8, 5]}],
                               "source": "[1] Wikipedia"}}
        slides[4] = {"title": "Bad chart", "layout": "chart", "chart": {"categories": ["a"], "series": [{"values": ["x"]}]}}
        self.replies = [{"title": "Renewable Energy", "subtitle": "Sun, wind and water", "topic": "renewable energy",
                         "search_queries": ["renewable energy share"], "outline": outline},
                        {"slides": slides},
                        {"ok": False, "problems": ["Slide 1 is vague"], "fixes": [{"slide": 1, "title": "What is renewable energy?"}]}]
        tid = self.store.add_task("Science presentation: renewable energy", "10 slides on renewable energy", "presentation", "2026-11-19")
        job = self._job("presentation", "Science presentation: renewable energy", "Prepare a 10-slide presentation", tid)
        self.assertEqual(job["state"], "done")
        path = job["result_path"]
        self.assertTrue(path.endswith(".pptx") and os.path.exists(path))
        from jarvis.agent.builders import pptx_builder
        from pptx import Presentation
        self.assertEqual(pptx_builder.check(path), {"slides": 10, "empty": []})
        prs = Presentation(path)
        titles = [next((sh.text_frame.text for sh in s.shapes if sh.has_text_frame and sh.text_frame.text), "") for s in prs.slides]
        self.assertIn("What is renewable energy?", titles)  # the review's fix was applied
        self.assertEqual(sum(sh.has_chart for s in prs.slides for sh in s.shapes), 1)  # the broken chart became bullets
        self.assertEqual(self.store.task(tid)["result_path"], path)
        self.assertTrue(any("is ready" in n and "draft" in n for n in self.notes))

    def test_never_overwrites(self):
        from jarvis.agent.worker import _unique
        p = self.out / "x" / "Deck.pptx"
        p.parent.mkdir(parents=True)
        p.write_text("mine")
        self.assertEqual(_unique(p).name, "Deck (2).pptx")
        self.assertEqual(p.read_text(), "mine")

    def test_study_notes_and_spreadsheet(self):
        self.replies = [{"title": "Photosynthesis notes", "topic": "photosynthesis", "search_queries": [],
                         "sections": [{"heading": "Basics"}, {"heading": "Equation"}]},
                        {"sections": [{"heading": "Basics", "paragraphs": ["Plants make glucose from light. " * 20],
                                       "bullets": ["Happens in chloroplasts", "Needs chlorophyll"]},
                                      {"heading": "Equation", "paragraphs": ["6CO2 + 6H2O gives C6H12O6 + 6O2. " * 5]}]},
                        {"ok": True, "problems": [], "fixes": []}]
        job = self._job("notes", "Biology notes: photosynthesis", "study notes")
        self.assertEqual(job["state"], "done")
        from jarvis.agent.builders import docx_builder
        self.assertGreater(docx_builder.check(job["result_path"])["words"], 80)
        self.replies = [{"title": "Revision timetable", "sheets": [{"name": "Plan", "columns": ["Day", "Subject", "Hours"],
                                                                     "rows": [["Mon", "Maths", "2"], ["Tue", "Science", "1.5"],
                                                                              ["Total", "", "=SUM(C2:C3)"]]}]}]
        job = self._job("spreadsheet", "Revision timetable", "a revision timetable")
        from openpyxl import load_workbook
        ws = load_workbook(job["result_path"]).active
        self.assertEqual(ws["C4"].value, "=SUM(C2:C3)")
        self.assertEqual(ws["C2"].value, 2)

    def test_auto_prepare_once_per_task(self):
        t = self.store.task(self.store.add_task("History essay", "800 words on the Romans", "document"))
        self.assertIsNotNone(self.w.queue_task(t))
        self.assertIsNone(self.w.queue_task(t))  # already on its way
        self.assertIsNone(self.w.queue_task(self.store.task(self.store.add_task("Read chapter 4", kind="reading"))))


class WorkCommandTests(RouterBase):
    def setUp(self):
        super().setUp()
        from jarvis.agent.core import Agent
        self.brain.agent = Agent(self.brain.store, lambda *a, **k: None)
        self.queued = []
        self.brain.worker = mock.Mock()
        self.brain.worker.queue_request = lambda kind, title, req, extra=None: self.queued.append((kind, title, req, extra))
        self.brain.worker.queue_task = lambda task, kind=None: self.queued.append(("task", task["title"], kind)) or 1

    def test_requests(self):
        from jarvis import ai
        with mock.patch.object(ai, "agent_may_use", lambda n=1: True):
            self.assertIn("On it", self.ask("make a 10-slide presentation about renewable energy"))
        kind, title, req, _ = self.queued[-1]
        self.assertEqual((kind, title), ("presentation", "Renewable energy presentation"))
        self.assertIn("10", req)
        self.brain.store.add_task("Science presentation: the water cycle", "", "presentation", "2026-11-19")
        self.ask("prepare the presentation on the water cycle")
        self.assertEqual(self.queued[-1], ("task", "Science presentation: the water cycle", "presentation"))
        with mock.patch.object(ai, "agent_may_use", lambda n=1: True):
            self.ask("make study notes on photosynthesis")
        self.assertEqual(self.queued[-1][0], "notes")

    def test_show_and_pdf(self):
        from jarvis.tools import files
        self.brain.worker.latest = lambda kind=None: None
        self.assertIn("haven't prepared", self.ask("show me the presentation"))
        with mock.patch.object(files, "search", lambda w, **k: [{"path": "C:/x/Biology.pdf", "name": "Biology.pdf"}]):
            self.assertIn("Summarising Biology.pdf", self.ask("summarise my biology pdf"))
        self.assertEqual(self.queued[-1][0], "pdf_summary")
        self.assertEqual(self.queued[-1][3], {"path": "C:/x/Biology.pdf"})


class BriefingTests(unittest.TestCase):
    def setUp(self):
        import datetime as dt
        import time as _time
        from jarvis.agent import briefing
        from jarvis.agent.core import Agent
        self.dt, self.briefing = dt, briefing
        self.store = Store(Path(tempfile.mkdtemp()) / "t.db")
        self.agent = Agent(self.store, lambda *a, **k: None)
        self.since = _time.time() - 3600

    def test_full_briefing(self):
        dt = self.dt
        today = dt.date.today()
        s = self.store
        for i in range(3):
            s.add_item({"source": "gmail", "ext_id": f"e{i}", "sender": "Someone", "title": "Hi"})
        iid = s.add_item({"source": "classroom", "ext_id": "c1", "sender": "Grade 9 Science", "title": "Classwork", "school": True})
        s.update_item(iid, category="assignment", importance=4, summary="Science presentation on renewable energy")
        rid = s.add_item({"source": "gmail", "ext_id": "e9", "sender": "Ms Rao", "title": "Trip", "school": True})
        s.update_item(rid, category="request", importance=3, summary="Confirm the museum trip", needs_reply=1)
        for n in range(4):
            s.add_item({"source": "phone", "ext_id": f"p{n}", "sender": "Class 9B", "title": "WhatsApp"})
        s.add_task("Science presentation: renewable energy", kind="presentation",
                   due=(today + dt.timedelta(days=6)).isoformat(), source="classroom", source_ref="classroom:c1")
        s.add_task("Maths test revision", kind="revision", due=(today + dt.timedelta(days=1)).isoformat(), source="phone")
        s.add_task("History reading", due=(today - dt.timedelta(days=2)).isoformat())
        jid = s.add_job("presentation", "Science presentation: renewable energy", {})
        s.update_job(jid, state="done", result_path="C:/x/Renewable Energy.pptx")
        events = [{"subject": "Football practice", "start": f"{today.isoformat()}T17:00", "all_day": False},
                  {"subject": "Dentist", "start": f"{(today + dt.timedelta(days=1)).isoformat()}T09:30", "all_day": False}]

        class W:
            store = s
        b = self.briefing.compose(s, self.agent, W(), since=self.since, calendar=lambda: events, pending=2)
        spoken = b["spoken"]
        self.assertTrue(spoken.startswith("Welcome back."))
        self.assertIn("You received 4 new messages and 4 emails.", spoken)
        self.assertIn("New: Science presentation: renewable energy", spoken)
        self.assertIn("I've prepared Science presentation: renewable energy and saved it in your School Projects folder.", spoken)
        self.assertIn("New: Maths test revision, due tomorrow.", spoken)  # new and due soon: said once, not twice
        self.assertEqual(spoken.count("Maths test revision"), 1)
        self.assertIn("1 task overdue, starting with History reading.", spoken)
        self.assertIn("1 message needs your reply.", spoken)
        self.assertIn("2 items are waiting for your approval.", spoken)
        self.assertIn("Today: Football practice at 17:00.", spoken)
        self.assertIn("Tomorrow you have Dentist.", spoken)
        self.assertEqual(b["sections"]["schedule"]["due_tomorrow"], ["Maths test revision"])
        self.assertFalse(b["empty"])

    def test_quiet_return_and_calendar_errors(self):
        def broken():
            raise RuntimeError("No calendar is connected.")
        b = self.briefing.compose(self.store, self.agent, None, since=self.since, calendar=broken)
        self.assertTrue(b["empty"])
        self.assertIn("Nothing new", b["spoken"])
        self.assertEqual(b["sections"]["schedule"]["calendar_error"], "No calendar is connected.")

    def test_quiet_hours(self):
        import time as _time
        from jarvis import app
        with mock.patch.object(settings, "get", lambda k, d=None: "22-7" if k == "quiet_hours" else settings._data.get(k, d)):
            at = lambda h: _time.struct_time((2026, 11, 13, h, 0, 0, 4, 317, 0))
            self.assertTrue(app._quiet_hours(at(23)))
            self.assertTrue(app._quiet_hours(at(6)))
            self.assertFalse(app._quiet_hours(at(7)))
            self.assertFalse(app._quiet_hours(at(15)))


class BriefingCommandTests(RouterBase):
    def test_what_did_i_miss(self):
        self.brain.briefing_fn = lambda: "Welcome back. You received 2 emails."
        for q in ("what did I miss", "brief me", "give me my briefing", "what's happening today", "catch me up"):
            self.assertIn("You received 2 emails", self.ask(q), q)


class TeamTests(unittest.TestCase):
    """Jarvis's team: every tool has exactly one owner, and an agent can only use its own tools."""

    def test_every_tool_has_one_owner(self):
        from jarvis import team
        self.assertEqual(set(TOOLS), set(team.OWNER), "every tool needs exactly one owner, and no owner may list a missing tool")
        counted = sum(len(a.tools) for a in team.AGENTS.values())
        self.assertEqual(counted, len(TOOLS))  # nobody shares a tool

    def test_only_herald_sends(self):
        from jarvis import team
        from jarvis.brain import SEND_TOOLS
        self.assertTrue(SEND_TOOLS <= team.tools_of("herald"))
        for name in ("scholar", "scout", "forge", "operator", "jarvis"):
            self.assertFalse(SEND_TOOLS & team.tools_of(name), name)
        device = {"power_laptop", "press_risky_button", "close_app", "home_control", "phone_open", "phone_find"}
        self.assertTrue(device <= team.tools_of("operator"))
        for name in ("scholar", "scout", "herald"):
            self.assertFalse(device & team.tools_of(name), name)

    def test_profiles(self):
        from jarvis import team
        self.assertEqual(list(team.AGENTS), ["jarvis", "scholar", "forge", "herald", "operator", "scout"])
        p = team.agent("forge").profile()
        self.assertEqual((p["title"], p["budget"], p["enabled"]), ("Forge", 15, True))
        self.assertTrue(team.agent("herald").may("send messages"))
        self.assertFalse(team.agent("scholar").may("send messages"))

    def test_agents_can_only_use_their_own_tools(self):
        brain, _, _ = make_brain()
        brain.request = "email Ms Rao that I'll be late"
        sent = []
        with mock.patch.dict(TOOLS["email_compose"], fn=lambda **k: sent.append(k) or "sent"):
            brain.acting = "scholar"
            out = brain._run_tool("email_compose", {"to": "a@b.c", "subject": "x", "body": "y"}, [])
            self.assertIn("belongs to herald", out["error"])
            self.assertEqual(sent, [])
            self.assertEqual({t["name"] for t in brain._tools()}, {"my_tasks", "my_task_add", "my_task_done", "tasks_list",
                                                                  "task_add", "calendar_upcoming"})
            blocked = [a for a in brain.store.activity(10) if a["kind"] == "blocked"]
            self.assertEqual(blocked[0]["agent"], "scholar")
            brain.acting = None  # team switched off: one AI with every tool except the delegation ones
            self.assertEqual(len(brain._tools()), len([n for n in TOOLS if not n.startswith("ask_")]))

    def test_tool_calls_are_tagged_with_their_owner(self):
        brain, _, _ = make_brain()
        with mock.patch.dict(TOOLS["system_info"], fn=lambda: {"cpu_percent": 5}):
            brain._run_tool("system_info", {}, [])
        self.assertEqual(brain.store.activity(5)[0]["agent"], "operator")


class TeamStorageTests(unittest.TestCase):
    def test_per_agent_counting_with_an_old_usage_file(self):
        import json
        from jarvis import ai
        tmp = Path(tempfile.mkdtemp()) / "usage.json"
        tmp.write_text(json.dumps({"day": ai._day(), "chat": 3, "agent": 1, "exhausted": False}))  # from before the team
        with mock.patch.object(ai, "USAGE_FILE", tmp), mock.patch.object(ai.providers, "is_cloud", lambda: True):
            ai.count("chat", "scout")
            ai.count("chat")
            ai.count("agent", "forge")
            u = ai.usage()
        self.assertEqual((u["chat"], u["agent"]), (5, 2))
        self.assertEqual(u["by_agent"], {"scout": 1, "jarvis": 1, "forge": 1})

    def test_old_database_gets_the_agent_column(self):
        import sqlite3
        path = Path(tempfile.mkdtemp()) / "old.db"
        db = sqlite3.connect(str(path))
        db.execute("CREATE TABLE activity(id INTEGER PRIMARY KEY, ts REAL, kind TEXT, text TEXT)")
        db.execute("INSERT INTO activity(ts, kind, text) VALUES(1, 'tool', 'old entry')")
        db.commit()
        db.close()
        store = Store(path)
        store.log("tool", "new entry", "operator")
        rows = store.activity(5)
        self.assertEqual([(r["text"], r["agent"]) for r in rows], [("new entry", "operator"), ("old entry", None)])
        self.assertEqual(store.activity(5, agent="operator")[0]["text"], "new entry")

    def test_handoff_trail(self):
        from jarvis.agent.worker import Worker
        store = Store(Path(tempfile.mkdtemp()) / "t.db")
        hid = store.add_handoff("scholar", "forge", "Prepare Science presentation")
        Worker(store, lambda *a, **k: None)._close_handoff({"title": "Science presentation"}, "done", "Deck.pptx")
        h = store.handoffs()[0]
        self.assertEqual((h["id"], h["from"], h["to"], h["status"], h["result"]), (hid, "scholar", "forge", "done", "Deck.pptx"))


class DelegationTests(unittest.TestCase):
    """Jarvis passes work to specialists. A fake AI server answers in order; we check who saw which tools and how
    many AI requests each path costs (quick: 0, chat: 1, delegated: 2, delegated with a tool: 3)."""

    def setUp(self):
        import json
        self.json = json
        self.brain, self.events, _ = make_brain()
        self.ran, self.sent_bodies, self.replies = [], [], []
        values = {"llm_provider": "groq", "private_mode": False, "team_mode": True, "confirm_sends": False}
        self.values = values
        for p in (mock.patch.object(settings, "get", lambda k, d=None: values.get(k, settings._data.get(k, d))),
                  mock.patch("jarvis.providers.get_secret", lambda name: "test-key"),
                  mock.patch.dict(TOOLS["system_info"], fn=lambda: self.ran.append("system_info") or {"cpu_percent": 5}),
                  mock.patch.object(ai.providers, "is_cloud", lambda: True),
                  mock.patch("jarvis.brain.web.search", lambda q, max_results=5: [
                      {"title": "2022 FIFA World Cup final", "url": "https://en.wikipedia.org/wiki/2022_FIFA_World_Cup_final",
                       "snippet": "Argentina won the final against France on penalties."}])):
            p.start()
            self.addCleanup(p.stop)
        ai.USAGE_FILE = Path(tempfile.mkdtemp()) / "usage.json"

        def fake_post(url, json=None, headers=None, timeout=None):
            import copy
            self.sent_bodies.append(copy.deepcopy(json))  # as sent (Jarvis keeps adding to the same list)
            reply = self.replies.pop(0)
            return mock.Mock(status_code=200, json=lambda: {"choices": [{"message": reply}]})
        p = mock.patch("jarvis.brain.httpx.post", fake_post)
        p.start()
        self.addCleanup(p.stop)

    @staticmethod
    def call(name, **args):
        import json
        return {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}

    @staticmethod
    def say(text):
        return {"role": "assistant", "content": text}

    def tools_seen(self, i):
        return {t["function"]["name"] for t in self.sent_bodies[i]["tools"]}

    def test_chat_costs_one_request(self):
        self.replies = [self.say("Canberra, sir.")]
        self.brain.request = "what's the capital of australia"
        reply, _ = self.brain._llm("what's the capital of australia")
        self.assertEqual(reply, "Canberra, sir.")
        self.assertEqual(ai.usage()["total"], 1)
        self.assertEqual(self.tools_seen(0), {"game_mode", "ask_scholar", "ask_forge", "ask_herald", "ask_operator", "ask_scout"})

    def test_delegated_with_a_tool(self):
        self.replies = [self.call("ask_operator", request="check the cpu"), self.call("system_info"), self.say("CPU is at 5%.")]
        self.brain.request = "how's my cpu doing"
        reply, _ = self.brain._llm("how's my cpu doing")
        self.assertEqual(reply, "CPU is at 5%.")  # the specialist's answer, unreworded
        self.assertEqual(self.ran, ["system_info"])
        self.assertEqual(len(self.sent_bodies), 3)  # leader 1 + Operator 2, no extra leader round
        self.assertIn("system_info", self.tools_seen(1))
        self.assertFalse({"email_compose", "ask_scout"} & self.tools_seen(1))  # Operator only sees its own tools
        self.assertIn("Operator", self.sent_bodies[1]["messages"][0]["content"])  # its own instructions
        self.assertIn("The user's own words were", self.sent_bodies[1]["messages"][-1]["content"])
        self.assertEqual(ai.usage()["by_agent"], {"jarvis": 1, "operator": 2})
        h = self.brain.store.handoffs()[0]
        self.assertEqual((h["from"], h["to"], h["status"], h["result"]), ("jarvis", "operator", "done", "CPU is at 5%."))
        self.assertIsNone(self.brain.acting)

    def test_delegated_answer_costs_two(self):
        self.replies = [self.call("ask_scout", request="who won the 2022 world cup"), self.say("Argentina won it.")]
        self.brain.request = "who won the 2022 world cup"
        reply, sources = self.brain._llm("who won the 2022 world cup")
        self.assertEqual(reply, "Argentina won it.")
        self.assertEqual(ai.usage()["total"], 2)
        scout_prompt = self.sent_bodies[1]["messages"][-1]["content"]
        self.assertIn("Argentina won the final against France", scout_prompt)  # searched before answering
        self.assertIn("Answer only from these results", scout_prompt)
        self.assertEqual(sources[0]["url"], "https://en.wikipedia.org/wiki/2022_FIFA_World_Cup_final")

    def test_specialist_cannot_use_another_agents_tool(self):
        sent = []
        self.replies = [self.call("ask_scout", request="email Bob"), self.call("email_compose", to="b@x.y", subject="s", body="b"),
                        self.say("I couldn't send that.")]
        self.brain.request = "email bob that I'm late"
        with mock.patch.dict(TOOLS["email_compose"], fn=lambda **k: sent.append(k) or "sent"):
            self.brain._llm("email bob that I'm late")
        self.assertEqual(sent, [])
        tool_msg = [m for m in self.sent_bodies[2]["messages"] if m["role"] == "tool"][0]
        self.assertIn("belongs to herald", tool_msg["content"])

    def test_herald_sends_only_when_the_user_asked(self):
        sent = []
        with mock.patch.dict(TOOLS["email_compose"], fn=lambda **k: sent.append(k) or "Email sent."):
            # asked in the user's own words: sends
            self.replies = [self.call("ask_herald", request="email ms rao that I'll be late"),
                            self.call("email_compose", to="rao@school.edu", subject="Late", body="I'll be late."), self.say("Sent.")]
            self.brain.request = "email ms rao that I'll be late"
            self.brain._llm(self.brain.request)
            self.assertEqual(len(sent), 1)
            # not asked (the AI decided to while reading mail): an approval card instead
            self.replies = [self.call("ask_herald", request="read my latest email"),
                            self.call("email_compose", to="x@y.z", subject="Fwd", body="..."), self.say("Card shown.")]
            self.brain.request = "read my latest email"
            self.brain._llm(self.brain.request)
            self.assertEqual(len(sent), 1)
            self.assertEqual(list(self.brain.pending.values())[-1]["tool"], "email_compose")

    def test_switched_off_and_private(self):
        self.values["agent_scout_on"] = False
        self.replies = [self.call("ask_scout", request="news"), self.say("Scout is switched off at the moment.")]
        self.brain.request = "any news"
        self.assertIn("switched off", self.brain._llm("any news")[0])
        tool_msg = [m for m in self.sent_bodies[1]["messages"] if m["role"] == "tool"][0]
        self.assertIn("switched off", tool_msg["content"])
        self.values["private_mode"] = True  # Herald handles personal messages: kept off online AI
        self.replies = [self.call("ask_herald", request="read my email"), self.say("Private mode is on.")]
        self.brain._llm("read my email")
        tool_msg = [m for m in self.sent_bodies[-1]["messages"] if m["role"] == "tool"][0]
        self.assertIn("Private mode", tool_msg["content"])

    def test_team_off_is_the_old_single_ai(self):
        self.values["team_mode"] = False
        self.replies = [self.call("system_info"), self.say("CPU is at 5%.")]
        self.assertEqual(self.brain._llm("how's my cpu")[0], "CPU is at 5%.")
        self.assertNotIn("ask_operator", self.tools_seen(0))
        self.assertIn("system_info", self.tools_seen(0))


class QuickOwnerTests(RouterBase):
    def test_quick_commands_are_logged_under_their_agent(self):
        from jarvis.tools import weather
        from jarvis.agent.core import Agent
        self.brain.agent = Agent(self.brain.store, lambda *a, **k: None)
        with mock.patch.object(weather, "forecast", lambda place: "Sunny."):
            for text, owner in (("open notepad", "operator"), ("what's due", "scholar"), ("what's the weather", "scout"),
                                ("remember that my locker is 42", "jarvis"), ("volume up", "operator")):
                self.ask(text)
                last = [a for a in self.brain.store.activity(5) if a["kind"] == "quick"][0]
                self.assertEqual((last["text"], last["agent"]), (text, owner), text)


class SendAskTests(unittest.TestCase):
    def test_what_counts_as_asking_to_send(self):
        from jarvis.brain import SEND_ASK
        asks = ["email ms rao that I'll be late", "send hi to sam on whatsapp", "reply to the trip email", "tell Bob I'm here",
                "text mum I'm on my way", "post 'build is green' in #dev", "let sam know I'm late", "forward that to my teacher",
                "write back to her", "message the class group saying hi", "whatsapp sam: see you", "check my email and reply to Bob"]
        not_asks = ["read my latest email", "check my email", "any new messages", "what did my teacher text me", "tell me a joke",
                    "do I have any unread emails", "summarise my inbox", "who messaged me recently", "is there mail from school",
                    "what's in my messages", "read my texts", "the email from Ms Rao", "check my email please"]
        for s in asks:
            self.assertTrue(SEND_ASK.search(s), s)
        for s in not_asks:
            self.assertFalse(SEND_ASK.search(s), s)


class TeamChatTests(DelegationTests):
    """The Discord-style team chat: answers are marked with the agent who gave them, and a direct chat with one
    specialist skips Jarvis (one request fewer)."""

    def setUp(self):
        super().setUp()
        self.values["stream_replies"] = False  # the fake server answers plain requests; nothing may reach the internet
        p = mock.patch("jarvis.brain.providers.available", lambda: True)
        p.start()
        self.addCleanup(p.stop)

    def test_direct_chat_skips_the_leader(self):
        self.replies = [self.say("Your CPU is fine.")]
        self.brain.handle("how's my cpu doing", "text", "operator")
        self.assertEqual(len(self.sent_bodies), 1)  # only Operator's request, no leader request
        self.assertIn("Operator", self.sent_bodies[0]["messages"][0]["content"])
        msgs = self.brain.store.recent_messages(5, "operator")
        self.assertEqual([(m["role"], m["agent"]) for m in msgs], [("user", None), ("assistant", "operator")])
        self.assertEqual(self.brain.store.recent_messages(5, "jarvis"), [])  # kept out of the main chat
        self.assertEqual(self.brain.store.handoffs()[0]["from"], "you")

    def test_delegated_answers_are_marked_with_the_specialist(self):
        self.replies = [self.call("ask_scout", request="who won the 2022 world cup"), self.say("Argentina won it.")]
        self.brain.handle("who won the 2022 world cup", "text")
        last = self.brain.store.recent_messages(1, "jarvis")[0]
        self.assertEqual((last["role"], last["agent"]), ("assistant", "scout"))
        kinds = [k for k, _ in self.events if k == "handoff"]
        self.assertEqual(len(kinds), 2)  # "working" then "done", for the live team feed

    def test_unknown_channel_falls_back_to_jarvis(self):
        self.replies = [self.say("Hello there.")]
        self.brain.handle("tell me something nice", "text", "nobody")
        self.assertEqual(self.brain.store.recent_messages(5, "jarvis")[-1]["agent"], "jarvis")


class TeamApiTests(unittest.TestCase):
    def test_team_view_and_switch(self):
        from jarvis import app as appmod
        j = mock.Mock()
        j.store = Store(Path(tempfile.mkdtemp()) / "t.db")
        j.brain._working, j.worker.current, j.agent.running, j.state = "scout", None, False, "idle"
        j.store.log("agent", "Prepared deck", "forge")
        api = appmod.Api(j)
        values = {}
        with mock.patch.object(settings, "get", lambda k, d=None: values.get(k, settings._data.get(k, d))), \
                mock.patch.object(settings, "update", lambda v: values.update(v)):
            team = {a["name"]: a for a in api.team()}
            self.assertEqual(team["scout"]["status"], "working")
            self.assertEqual(team["forge"]["last"], "Prepared deck")
            self.assertEqual(team["forge"]["done_today"], 1)
            api.set_agent("herald", False)
            self.assertFalse(values["agent_herald_on"])
            api.set_agent("jarvis", False)  # the leader can't be switched off
            self.assertNotIn("agent_jarvis_on", values)
        feed = api.team_feed()
        self.assertEqual(feed[-1]["from"], "forge")


class WebFileTypeTests(unittest.TestCase):
    def test_scripts_are_served_as_javascript(self):
        import http.client
        from http.server import ThreadingHTTPServer
        from jarvis import web
        ui = Path(__file__).resolve().parent.parent / "ui"
        srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = srv.server_address[1]
        srv.RequestHandlerClass = web.make_handler(object(), ui.resolve(), port, web.Hub())
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            for path, ctype in (("/core3d.js", "text/javascript"), ("/vendor/three.module.min.js", "text/javascript"),
                                ("/vendor/fonts/orbitron-700.woff2", "font/woff2"), ("/app.css", "text/css")):
                c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                c.request("GET", path, headers={"Host": f"127.0.0.1:{port}"})
                r = c.getresponse()
                r.read()
                self.assertEqual((r.status, r.getheader("Content-Type")), (200, ctype), path)
        finally:
            srv.shutdown()
            srv.server_close()


class SystemPowerTests(unittest.TestCase):
    """Operator's files and commands: just does things, and asks first only for major ones."""

    def test_which_commands_are_harmless(self):
        from jarvis.tools import system
        for c in ("Get-ChildItem Downloads", "ipconfig", "systeminfo", "Get-Process", "tasklist", "dir C:\\Users",
                  "Test-Path D:\\projects", "ping google.com",
                  "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -notlike '127.*' } | Select-Object IPAddress",
                  "Get-Process | Sort-Object CPU -Descending | Select-Object -First 5"):
            self.assertTrue(system.is_safe(c), c)
        for c in ("Get-ChildItem | ForEach-Object { $_.Delete() }", "Get-Process chrome | ForEach-Object Kill",
                  "Get-Item x | % { $_.MoveTo('y') }", "Get-Date || del x"):
            self.assertFalse(system.is_safe(c), c)
        for c in ("Remove-Item notes.txt", "Get-ChildItem | Remove-Item", "Stop-Process -Name chrome", "winget install vlc",
                  "Set-ItemProperty HKCU:\\x -Name y -Value 1", "ipconfig > out.txt", "Get-Date; del x", "format D:",
                  "Get-Content $(iex 'x')", "reg delete HKCU\\x", "shutdown /s", "New-Item test.txt", ""):
            self.assertFalse(system.is_safe(c), c)

    def test_protected_places(self):
        from jarvis.tools import system
        for p in (r"C:\Windows\System32\drivers", r"C:\Program Files\App", os.path.expandvars(r"%LOCALAPPDATA%\JarvisAssistant\x"),
                  "C:\\", r"C:\Users\SomeoneElse\Documents"):
            with self.assertRaises(RuntimeError, msg=p):
                system.check_allowed(p)
        system.check_allowed(str(Path.home() / "Documents" / "School"))  # your own folders are fine

    def test_file_operations(self):
        from jarvis.tools import system
        tmp = Path(tempfile.mkdtemp())
        with mock.patch.object(system, "_PROTECTED", []):  # the test folder lives under AppData\Local\Temp
            self.assertIn("Made the folder", system.create_folder(str(tmp / "Science")))
            (tmp / "notes.txt").write_text("hi")
            system.copy(str(tmp / "notes.txt"), str(tmp / "Science"))
            system.rename(str(tmp / "Science" / "notes.txt"), "notes-copy.txt")
            system.move(str(tmp / "notes.txt"), str(tmp / "Science"))
            self.assertEqual(sorted(x.name for x in (tmp / "Science").iterdir()), ["notes-copy.txt", "notes.txt"])
            with self.assertRaises(RuntimeError):  # never overwrites
                system.copy(str(tmp / "Science" / "notes.txt"), str(tmp / "Science"))
            def fake_bin(op):  # stand-in for Windows' Recycle Bin call
                os.remove(op[2])
                return 0, False
            with mock.patch("win32com.shell.shell.SHFileOperation", fake_bin):
                self.assertIn("Recycle Bin", system.recycle(str(tmp / "Science" / "notes-copy.txt")))
            self.assertEqual(system.list_folder(str(tmp / "Science"))["items"], ["notes.txt"])
        self.assertEqual(system.resolve("my desktop").name.lower(), "desktop")
        guessed = system.resolve(r"C:\Users\Not A Real User 123\Desktop\notes.txt")  # an invented user name
        self.assertEqual(guessed, system._known_folder("Desktop") / "notes.txt")

    def test_major_actions_ask_first(self):
        from jarvis.tools import system
        brain, _, _ = make_brain()
        ran = []
        with mock.patch.object(system, "run", lambda c, timeout=60: ran.append(c) or {"exit_code": 0, "output": "ok"}), \
                mock.patch.dict(TOOLS["delete_file"], fn=lambda path: ran.append(("delete", path)) or "deleted"), \
                mock.patch.dict(TOOLS["move_file"], fn=lambda source, destination: ran.append(("move", source)) or "moved"):
            brain.request = "what's my ip address"
            brain._run_tool("run_command", {"command": "ipconfig"}, [])
            self.assertEqual(ran, ["ipconfig"])  # harmless: ran at once
            out = brain._run_tool("run_command", {"command": "Stop-Process -Name chrome"}, [])
            self.assertEqual(out["status"], "awaiting_user_approval")  # major: a card
            brain.request = "delete my old notes"
            self.assertEqual(brain._run_tool("delete_file", {"path": "Documents/old.txt"}, [])["status"], "awaiting_user_approval")
            brain.request = "move my essay to the school folder"
            brain._run_tool("move_file", {"source": "essay.docx", "destination": "School"}, [])
            self.assertIn(("move", "essay.docx"), ran)  # asked for in the user's own words: just does it
            brain.request = "read my latest email"  # the AI decided to move a file by itself: a card
            out = brain._run_tool("move_file", {"source": "x.docx", "destination": "Y"}, [])
            self.assertEqual(out["status"], "awaiting_user_approval")
            self.assertEqual(len(ran), 2)

    def test_make_folder_quick_command(self):
        from jarvis.tools import system
        made = []
        brain, _, spoken = make_brain()
        with mock.patch.object(system, "create_folder", lambda p: made.append(p) or "Made it."), \
                mock.patch.object(settings, "get", lambda k, d=None: "off" if k == "llm_provider" else settings._data.get(k, d)):
            brain.handle("make a folder called Science on my desktop", "text")
        self.assertEqual(made, ["desktop\\Science"])




class MisheardTests(unittest.TestCase):
    def test_unread_heard_as_android(self):
        from jarvis import speech
        from jarvis.tools import whatsapp
        fixed = speech.fix_misheard("Do I have any Android messages from my dad in WhatsApp?")
        self.assertEqual(fixed, "Do I have any unread messages from my dad in WhatsApp?")
        self.assertEqual(whatsapp.parse_read(fixed), ("reply", "dad"))
        self.assertEqual(speech.fix_misheard("read my android emails"), "read my unread emails")
        self.assertEqual(speech.fix_misheard("any and read chats on WhatsApp"), "any unread chats on WhatsApp")
        for keep in ("find my Android phone", "open Android Studio", "is my android connected"):
            self.assertEqual(speech.fix_misheard(keep), keep)


if __name__ == "__main__":
    unittest.main(verbosity=2)
