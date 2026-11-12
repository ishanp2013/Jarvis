"""Speech: wake word (openWakeWord), speech-to-text (faster-whisper) and text-to-speech
(ElevenLabs / Microsoft Edge neural voices / offline Windows voice), with interruptible playback."""
import asyncio
import logging
import os
import queue
import re
import sys
import tempfile
import threading
import time
import types

import httpx
import miniaudio
import numpy as np
import sounddevice as sd

from .config import get_secret, settings

log = logging.getLogger("speech")
RATE = 16000
FRAME = 1280  # 80 ms, the frame size openWakeWord expects


# ---------------------------------------------------------------- wake word
WAKE_MODELS = {"hey_jarvis": "Hey Jarvis", "alexa": "Alexa", "hey_mycroft": "Hey Mycroft", "hey_rhasspy": "Hey Rhasspy"}


def wake_phrase():
    m = settings.get("wake_model") or "hey_jarvis"
    if m in WAKE_MODELS:
        return WAKE_MODELS[m]
    return settings.get("wake_phrase_label") or os.path.splitext(os.path.basename(m))[0].replace("_", " ").title()


class WakeWord:
    """openWakeWord detector. Built-in phrases, or your own model trained with openWakeWord's free
    training notebook (an .onnx file; see SETUP.md)."""

    def __init__(self, model=None):
        # openWakeWord imports scikit-learn only for training custom verifiers. Smart App Control
        # blocks sklearn's DLLs on this PC, so that import is stubbed out: detection doesn't need it.
        stub = types.ModuleType("openwakeword.custom_verifier_model")
        stub.train_custom_verifier = None
        sys.modules.setdefault("openwakeword.custom_verifier_model", stub)
        import openwakeword.utils
        from openwakeword.model import Model

        model = model or settings.get("wake_model") or "hey_jarvis"
        if model in WAKE_MODELS:
            openwakeword.utils.download_models(model_names=[model])
        elif not (os.path.isfile(model) and model.lower().endswith(".onnx")):
            raise RuntimeError(f"Wake word model not found: {model}. Pick an .onnx file trained with openWakeWord.")
        self.name = model
        self.model = Model(wakeword_models=[model], inference_framework="onnx")

    def score(self, frame: np.ndarray) -> float:
        return max(self.model.predict(frame).values())

    def reset(self):
        self.model.reset()


# ---------------------------------------------------------------- speech to text
_HALLUCINATIONS = {"", "you", "thank you.", "thanks for watching!", "thank you for watching.", "bye.", "."}


class STT:
    def __init__(self):
        self._model = None
        self._name = None
        self._lock = threading.Lock()

    def _load(self):
        name = settings["stt_model"]
        if self._model is None or self._name != name:
            from faster_whisper import WhisperModel
            opts = dict(device="cpu", compute_type="int8", cpu_threads=min(4, os.cpu_count() or 4))
            try:  # use the cached model so start-up works offline; download only the first time
                self._model = WhisperModel(name, local_files_only=True, **opts)
            except Exception:
                self._model = WhisperModel(name, **opts)
            self._name = name
        return self._model

    def warm(self):
        with self._lock:
            self._load()

    def transcribe(self, audio_int16: np.ndarray) -> str:
        with self._lock:
            model = self._load()
            audio = audio_int16.astype(np.float32) / 32768.0
            segs, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=False,
                                       condition_on_previous_text=False,
                                       initial_prompt="Hey Jarvis, open Opera GX. Launch Discord. Open YouTube.")
            text = " ".join(s.text for s in segs if s.no_speech_prob < 0.6).strip()
        return "" if text.lower() in _HALLUCINATIONS else text


# ---------------------------------------------------------------- text to speech
def _trim(audio, rate, thresh=300, keep=0.06):
    """Drop the padded silence voices add at both ends; it otherwise adds ~1 s of dead air per reply."""
    loud = np.flatnonzero(np.abs(audio) > thresh)
    if not len(loud):
        return audio
    pad = int(keep * rate)
    return audio[max(0, loud[0] - pad): loud[-1] + pad]


def _decode_mp3(data: bytes):
    d = miniaudio.decode(data, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
    return _trim(np.frombuffer(d.samples, dtype=np.int16), 24000), 24000


def chime(volume=0.25):
    """Short two-tone acknowledgement played the instant the wake word is heard."""
    rate = 24000
    t = np.arange(int(rate * 0.09)) / rate
    tone = np.concatenate([np.sin(2 * np.pi * 880 * t), np.sin(2 * np.pi * 1320 * t)])
    env = np.minimum(1, np.minimum(np.arange(len(tone)), np.arange(len(tone))[::-1]) / 300)
    sd.play((tone * env * volume * 32767 * float(settings["tts_volume"])).astype(np.int16), rate)


def synth_edge(text):
    import edge_tts

    async def run():
        buf = bytearray()
        comm = edge_tts.Communicate(text, settings["edge_voice"], rate=settings["edge_rate"], pitch=settings["edge_pitch"])
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                buf.extend(chunk["data"])
        return bytes(buf)

    data = asyncio.run(run())
    if not data:
        raise RuntimeError("Edge TTS returned no audio")
    return _decode_mp3(data)


def synth_elevenlabs(text):
    key, voice = get_secret("elevenlabs_api_key"), settings["elevenlabs_voice_id"]
    if not key or not voice:
        raise RuntimeError("ElevenLabs key or voice not set")
    r = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_22050_32",
        headers={"xi-api-key": key},
        json={"text": text, "model_id": settings["elevenlabs_model"],
              "voice_settings": {"stability": settings["elevenlabs_stability"],
                                 "similarity_boost": settings["elevenlabs_similarity"],
                                 "style": settings["elevenlabs_style"]}},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"ElevenLabs {r.status_code}: {r.text[:150]}")
    return _decode_mp3(r.content)


def synth_windows(text):
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        path = os.path.join(tempfile.gettempdir(), "jarvis_sapi.wav")
        voice = win32com.client.Dispatch("SAPI.SpVoice")
        for v in voice.GetVoices():
            if "en-gb" in v.GetAttribute("Language").lower() or "George" in v.GetDescription():
                voice.Voice = v
                break
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(path, 3)
        voice.AudioOutputStream = stream
        voice.Speak(text)
        stream.Close()
    finally:
        pythoncom.CoUninitialize()
    d = miniaudio.decode_file(path, output_format=miniaudio.SampleFormat.SIGNED16, nchannels=1, sample_rate=24000)
    return _trim(np.frombuffer(d.samples, dtype=np.int16), 24000), 24000


PROVIDERS = {"elevenlabs": synth_elevenlabs, "edge": synth_edge, "windows": synth_windows}


def elevenlabs_voices():
    key = get_secret("elevenlabs_api_key")
    r = httpx.get("https://api.elevenlabs.io/v1/voices", headers={"xi-api-key": key}, timeout=15)
    r.raise_for_status()
    return [{"id": v["voice_id"], "name": v["name"], "labels": v.get("labels", {})} for v in r.json()["voices"]]


def elevenlabs_usage():
    key = get_secret("elevenlabs_api_key")
    r = httpx.get("https://api.elevenlabs.io/v1/user/subscription", headers={"xi-api-key": key}, timeout=15)
    r.raise_for_status()
    j = r.json()
    return {"tier": j.get("tier"), "used": j.get("character_count"), "limit": j.get("character_limit")}


def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out, cur = [], ""
    for p in parts:  # merge very short fragments so speech doesn't sound choppy
        cur = f"{cur} {p}".strip()
        if len(cur) > 40:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


class SentenceStream:
    """Collects an AI reply as it arrives and hands out whole sentences to the Speaker.

    The last sentence is held back until finish(), so a closing touch (", sir.") can be added to it."""

    def __init__(self):
        self._q = queue.Queue()
        self._buf = ""
        self._ready = []
        self.text = ""
        self.started = False

    def feed(self, delta):
        if not delta:
            return
        self.text += delta
        self._buf += delta
        parts = re.split(r"(?<=[.!?])\s+", self._buf)
        self._buf = parts.pop()  # unfinished
        for p in parts:
            self._ready.append(p)
        # keep one finished sentence back; release the rest once they're long enough to sound natural
        while len(self._ready) > 1:
            first = self._ready.pop(0)
            if len(first) < 40 and self._ready:
                self._ready[0] = f"{first} {self._ready[0]}"
                continue
            self.started = True
            self._q.put(first)

    def finish(self, final_touch=None):
        """final_touch(last_sentence) may rewrite the last sentence before it's spoken."""
        rest = " ".join(x for x in self._ready + [self._buf.strip()] if x).strip()
        self._ready, self._buf = [], ""
        if rest:
            self._q.put(final_touch(rest) if final_touch else rest)
        self._q.put(None)

    def __iter__(self):
        while (s := self._q.get()) is not None:
            yield s


class Speaker:
    """Synthesises sentence by sentence and plays while the next one renders; stop() is instant."""

    def __init__(self, on_state, on_error, on_level=None):
        self.on_state, self.on_error = on_state, on_error
        self.on_level = on_level or (lambda v: None)  # 0..1 loudness of what's being said, ~20 times a second
        self._gen = 0
        self._speaking = threading.Event()
        self._lock = threading.Lock()

    @property
    def speaking(self):
        return self._speaking.is_set()

    def stop(self):
        with self._lock:
            self._gen += 1
        sd.stop()
        self._speaking.clear()

    def say(self, text, block=False):
        """Speak text. text may also be an iterable of sentences that is still being written (a
        SentenceStream): speaking starts with the first sentence."""
        self.stop()
        gen = self._gen
        t = threading.Thread(target=self._run, args=(text, gen), daemon=True)
        t.start()
        if block:
            t.join()

    def _synth(self, sentence):
        order = [settings["tts_provider"]] + [p for p in ("edge", "windows") if p != settings["tts_provider"]]
        for name in order:
            try:
                return PROVIDERS[name](sentence)
            except Exception as e:
                log.warning("TTS %s failed: %s", name, e)
                self.on_error(f"Voice '{name}' failed, falling back: {str(e)[:120]}")
        return None

    def _run(self, text, gen):
        q = queue.Queue(maxsize=2)

        def produce():
            for s in (_sentences(text) if isinstance(text, str) else text):
                if gen != self._gen:
                    break
                q.put(self._synth(s))
            q.put(StopIteration)

        threading.Thread(target=produce, daemon=True).start()
        self._speaking.set()
        self.on_state(True)
        try:
            while gen == self._gen:
                item = q.get()
                if item is StopIteration:
                    break
                if item is None or gen != self._gen:
                    continue
                audio, rate = item
                sd.play((audio * float(settings["tts_volume"])).astype(np.int16), rate)
                started = time.time()
                # wait in small steps so stop() takes effect within ~50 ms, reporting loudness for the orb
                stream = sd.get_stream()
                while stream.active and gen == self._gen:
                    i = int((time.time() - started) * rate)
                    chunk = audio[i:i + rate // 20].astype(np.float32)
                    self.on_level(min(1.0, float(np.sqrt(np.mean(chunk ** 2))) / 6000) if len(chunk) else 0.0)
                    sd.sleep(50)
                self.on_level(0.0)
        except Exception as e:
            self.on_error(f"Audio playback failed: {e}")
        finally:
            if gen == self._gen:
                self._speaking.clear()
                self.on_state(False)
