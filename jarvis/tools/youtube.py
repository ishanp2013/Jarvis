"""YouTube and YouTube Music in your browser: "play X on YouTube" opens the top video itself instead
of a results page. Uses YouTube's public search page (no account, no key)."""
import json
import re
import urllib.parse

import httpx

from . import windows as win

_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/130.0 Safari/537.36", "Accept-Language": "en-GB,en;q=0.9"}


def top_video(query):
    """(video id, title) of the first real video result, or None."""
    try:
        r = httpx.get("https://www.youtube.com/results", params={"search_query": query}, headers=_UA, timeout=10,
                      cookies={"CONSENT": "YES+1"}, follow_redirects=True)
    except httpx.HTTPError:
        return None
    m = re.search(r'"videoRenderer":\{"videoId":"([\w-]{11})".{0,2000}?"title":\{"runs":\[\{"text":"((?:[^"\\]|\\.)*)"', r.text)
    if not m:
        m = re.search(r'"videoId":"([\w-]{11})"', r.text)
        return (m.group(1), query) if m else None
    try:
        title = json.loads(f'"{m.group(2)}"')
    except ValueError:
        title = query
    return m.group(1), title


def play(query, music=False):
    hit = top_video(query + (" song" if music else ""))
    host = "https://music.youtube.com" if music else "https://www.youtube.com"
    where = "YouTube Music" if music else "YouTube"
    if not hit:
        win.open_url(f"{host}/search?q=" + urllib.parse.quote_plus(query) if music else
                     "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query))
        return f"Searching {where} for {query}."
    win.open_url(f"{host}/watch?v={hit[0]}")
    return f"Playing {hit[1]} on {where}."
