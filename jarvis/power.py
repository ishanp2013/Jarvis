"""Keeps the laptop from going to sleep on its own while it's plugged in, so Jarvis's background work
and phone access keep running. On battery, normal sleep applies.

This only asks Windows not to *idle*-sleep while Jarvis runs (the same request a video player makes);
it changes no power settings. Closing the lid or pressing the power button still sleeps the laptop."""
import ctypes
import logging
import threading
import time

import psutil

from .config import settings

log = logging.getLogger("power")
ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def plugged_in():
    b = psutil.sensors_battery()
    return True if b is None else bool(b.power_plugged)  # desktops have no battery


def battery():
    b = psutil.sensors_battery()
    return None if b is None else {"percent": round(b.percent), "plugged": bool(b.power_plugged)}


class KeepAwake:
    """The request belongs to the thread that made it, so one long-lived thread owns it."""

    def __init__(self, on_change=None):
        self.active = False
        self.on_change = on_change or (lambda active: None)
        threading.Thread(target=self._loop, daemon=True, name="keep-awake").start()

    def _loop(self):
        while True:
            want = bool(settings.get("keep_awake_on_ac", True)) and plugged_in()
            if want != self.active:
                flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if want else 0)
                ctypes.windll.kernel32.SetThreadExecutionState(flags)
                self.active = want
                log.info("keep awake %s", "on (plugged in)" if want else "off")
                self.on_change(want)
            time.sleep(30)
