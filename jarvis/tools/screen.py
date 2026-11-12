"""Screenshots (for "what's on my screen?") and the clipboard. Pure pywin32 + numpy: no extra installs.

A screenshot is taken only when you ask about your screen, is never saved to disk, and goes only to
the AI model you chose in Settings."""
import ctypes
import struct
import zlib

import numpy as np
import win32api
import win32clipboard
import win32con
import win32gui
import win32ui


def capture(max_width=1600, region=None):
    """PNG bytes of the monitor with the active window (or region=(left, top, right, bottom) in real
    pixels), scaled down to at most max_width pixels wide."""
    # Work in real pixels: with display scaling (e.g. 125%), a DPI-unaware thread only sees part of the screen.
    user32 = ctypes.windll.user32
    old = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor aware v2
    try:
        return _capture(max_width, region)
    finally:
        if old:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(old))


def _capture(max_width, region):
    hwnd = win32gui.GetForegroundWindow()
    mon = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTOPRIMARY)
    left, top, right, bottom = region or win32api.GetMonitorInfo(mon)["Monitor"]
    w, h = right - left, bottom - top
    desk = win32gui.GetDesktopWindow()
    src = win32gui.GetWindowDC(desk)
    sdc = win32ui.CreateDCFromHandle(src)
    mdc = sdc.CreateCompatibleDC()
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(sdc, w, h)
    mdc.SelectObject(bmp)
    try:
        mdc.BitBlt((0, 0), (w, h), sdc, (left, top), win32con.SRCCOPY)
        raw = np.frombuffer(bmp.GetBitmapBits(True), dtype=np.uint8).reshape(h, w, 4)
    finally:
        win32gui.DeleteObject(bmp.GetHandle())
        mdc.DeleteDC()
        sdc.DeleteDC()
        win32gui.ReleaseDC(desk, src)
    rgb = raw[:, :, 2::-1]  # BGRA -> RGB
    step = max(1, -(-w // max_width))
    if step > 1:  # box-average down so text stays readable
        hh, ww = (h // step) * step, (w // step) * step
        rgb = rgb[:hh, :ww].reshape(hh // step, step, ww // step, step, 3).mean(axis=(1, 3)).astype(np.uint8)
    return png(np.ascontiguousarray(rgb))


def png(rgb):
    h, w, _ = rgb.shape
    rows = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


# ------------------------------------------------------------------ clipboard
def _open():
    for _ in range(10):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception:
            win32api.Sleep(50)
    raise RuntimeError("The clipboard is busy. Try again in a moment.")


def get_clipboard():
    _open()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        return ""
    finally:
        win32clipboard.CloseClipboard()


def set_clipboard(text):
    _open()
    try:
        win32clipboard.EmptyClipboard()
        if text:
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, str(text))
    finally:
        win32clipboard.CloseClipboard()
    return "Copied to your clipboard."
