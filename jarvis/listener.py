"""Microphone loop: wake word -> capture until silence -> hand utterance to the brain.

One 16 kHz input stream feeds everything. The wake word stays armed while Jarvis is thinking or
speaking, so "Hey Jarvis" always interrupts. Muting closes the stream: the mic is then not open at all.
"""
import logging
import queue
import threading
import time

import numpy as np
import sounddevice as sd

from .config import settings
from .speech import FRAME, RATE

log = logging.getLogger("listener")


class Listener:
    def __init__(self, wake, on_utterance, on_wake, emit):
        self.wake, self.on_utterance, self.on_wake, self.emit = wake, on_utterance, on_wake, emit
        self.frames = queue.Queue(maxsize=200)
        self.stream = None
        self.mode = "idle"            # idle | listening
        self.listen_deadline = 0.0
        self.noise = 200.0             # running estimate of background RMS
        self.buf, self.speech_started, self.last_voice = [], False, 0.0
        self.clock = 0.0               # audio time in seconds (robust to processing lag, unlike wall-clock)
        self.level = 0.0
        threading.Thread(target=self._loop, daemon=True, name="listener").start()

    # -------- mic control
    def start(self):
        if self.stream:
            return
        try:
            self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME, callback=self._cb)
            self.stream.start()
            self.emit("mic", {"on": True, "device": sd.query_devices(kind="input")["name"]})
        except Exception as e:
            self.stream = None
            self.emit("mic", {"on": False, "error": str(e)})

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.mode = "idle"
        self.emit("mic", {"on": False})

    def _cb(self, indata, frames, t, status):
        try:
            self.frames.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass  # if we fall behind, drop audio rather than lag further

    # -------- listening
    def listen_now(self, window=6.0):
        """Start capturing a command without the wake word (button press or follow-up turn)."""
        if not self.stream:
            return
        self.buf, self.speech_started = [], False
        self.listen_deadline = self.clock + window
        self.mode = "listening"
        self.emit("state", {"state": "listening"})

    def cancel_listen(self):
        self.mode = "idle"

    def _loop(self):
        last_level_emit = 0.0
        while True:
            frame = self.frames.get()
            self.clock += len(frame) / RATE
            rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
            self.level = rms
            now = time.time()
            if now - last_level_emit > 0.1:
                self.emit("level", {"rms": min(1.0, rms / 4000)})
                last_level_emit = now

            if self.mode == "idle":
                self.noise = 0.98 * self.noise + 0.02 * rms
                if settings["wake_word_enabled"]:
                    score = self.wake.score(frame)
                    if score >= float(settings["wake_threshold"]):
                        self.wake.reset()
                        log.info("wake word %.2f", score)
                        self.on_wake()
                        self.listen_now(window=5.0)
                continue

            # listening: simple energy endpointing relative to the room's noise floor
            threshold = max(self.noise * 2.5, 350)
            self.buf.append(frame)
            if rms > threshold:
                self.speech_started, self.last_voice = True, self.clock
            elif not self.speech_started and self.clock > self.listen_deadline:
                self.mode = "idle"
                self.emit("state", {"state": "idle"})
                continue
            duration = len(self.buf) * FRAME / RATE
            silence_ms = (self.clock - self.last_voice) * 1000 if self.speech_started else 0
            if (self.speech_started and silence_ms > settings["silence_end_ms"]) or duration > 15:
                audio = np.concatenate(self.buf)
                self.buf, self.mode = [], "idle"
                self.wake.reset()
                threading.Thread(target=self.on_utterance, args=(audio,), daemon=True).start()
