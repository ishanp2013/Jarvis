"""Instant, offline answers to greetings and small talk ("hi", "who are you", "thank you"), so these
feel snappy and work with no AI model. Only whole short phrases match; anything longer goes on to
the commands and the AI as usual."""
import datetime as dt
import random
import re

from ..config import settings

JOKES = [
    "I would tell you a UDP joke, but you might not get it.",
    "There are ten kinds of people: those who understand binary, and those who don't.",
    "I asked the Wi-Fi for a joke. The punchline is still buffering.",
    "Why did the computer go to the doctor? It had a virus. Nothing a restart couldn't fix.",
    "I'm reading a book about anti-gravity. It's impossible to put down.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
]


def _greeting():
    h = dt.datetime.now().hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 17 else "Good evening"


def _name():
    return settings.get("assistant_name") or "Jarvis"


def _capabilities():
    return ("I can open, close and arrange your apps, play music on Spotify, search the web with sources, "
            "find your files, check the weather, read and send email, manage your calendar and tasks, "
            "post to Discord, send WhatsApp messages, check GitHub, run your routines, and tell you how your PC is doing. "
            "Connect accounts and an AI model in Settings for full conversations.")


_RULES = [
    (r"(?:hi|hello|hey|hiya|howdy|yo|greetings|hey there|hi there|hello there)", lambda: f"{_greeting()}. How can I help?"),
    (r"good (?:morning|afternoon|evening)", lambda: f"{_greeting()}. What can I do for you?"),
    (r"(?:how are you|how are you doing|how's it going|how are things|you good|how do you do)",
     lambda: random.choice(["All systems running smoothly. How can I help?", "Fully operational and at your service.",
                            "Never better. What do you need?"])),
    (r"(?:what's up|whats up|sup|wassup)", lambda: "Just keeping an eye on things. What do you need?"),
    (r"(?:who are you|what are you|what's your name|whats your name|what is your name|introduce yourself|tell me about yourself)",
     lambda: f"I'm {_name()}, your personal desktop assistant. Say 'what can you do' to hear what I can help with."),
    (r"(?:what can you do|what do you do|help|help me|what are your (?:features|abilities|skills)|how can you help(?: me)?)", _capabilities),
    (r"(?:who (?:made|built|created) you|who is your (?:creator|maker))",
     lambda: "I was built for you, here on this laptop. Everything I do runs on your own PC unless you connect an online service."),
    (r"(?:are you (?:there|awake|listening|online)|you there|jarvis\??)", lambda: "Always. What do you need?"),
    (r"(?:thanks|thank you|thank you so much|thanks a lot|cheers|nice|great|perfect|awesome|good job|well done)",
     lambda: random.choice(["You're welcome.", "Any time.", "Happy to help.", "My pleasure."])),
    (r"good ?night", lambda: "Good night. Rest well."),
    (r"(?:bye|goodbye|see you|see you later|later|i'm off|that's it for now)",
     lambda: random.choice(["Goodbye. I'll be here if you need me.", "See you soon."])),
    (r"(?:tell me a joke|say something funny|make me laugh|joke)", lambda: random.choice(JOKES)),
    (r"(?:are you (?:real|human|an ai|a robot))", lambda: "I'm an AI assistant running on your PC. Real enough to get things done."),
    (r"(?:i love you|love you)", lambda: "That's very kind. I'm rather fond of working for you too."),
    (r"(?:are you (?:smart|clever)|you're (?:smart|clever))", lambda: "Clever enough to know what I don't know, and to look it up."),
]
_COMPILED = [(re.compile(rf"^(?:(?:hey|hi|ok|okay) )?{pat}(?: jarvis)?$"), fn) for pat, fn in _RULES]


def reply(text):
    """An instant answer for small talk, or None. `text` is lowercase without the wake phrase."""
    t = re.sub(r"[^\w' ]", "", text).strip()
    t = re.sub(r"\s+", " ", t)
    for pat, fn in _COMPILED:
        if pat.match(t):
            return fn()
    return None
