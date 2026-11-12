"""Research for prepared work: reliable sources first, and free-licence images with their credits.

Sources: Wikipedia (through its API), then web results ranked so encyclopaedias, government, university,
science and well-known education sites come first. Images: Wikimedia Commons, only files under free
licences (Creative Commons or public domain), each with the author and licence to credit on the slide."""
import html
import logging
import re
from urllib.parse import urlparse

import httpx

from ..tools import web

log = logging.getLogger("research")
UA = {"User-Agent": "JarvisAssistant/1.0 (personal study assistant; https://github.com/ishanp2013/Jarvis)"}
TRUSTED = re.compile(r"(wikipedia\.org|britannica\.com|\.gov(\.\w+)?$|\.edu(\.\w+)?$|\.ac\.\w+$|nasa\.gov|noaa\.gov|who\.int|un\.org|"
                     r"iea\.org|irena\.org|worldbank\.org|ourworldindata\.org|nationalgeographic\.com|bbc\.co\.uk|bbc\.com|"
                     r"khanacademy\.org|nature\.com|sciencedirect\.com|smithsonianmag\.com|europa\.eu|unesco\.org|"
                     r"energy\.gov|eia\.gov|metoffice\.gov\.uk|rsc\.org|newscientist\.com|scientificamerican\.com)$")
AVOID = re.compile(r"(pinterest|facebook|instagram|tiktok|reddit|quora|youtube|amazon|ebay|coursehero|chegg|studocu|brainly|"
                   r"scribd|slideshare|answers\.com|grokipedia|everybodywiki|fandom|medium\.com|blogspot|wordpress\.com)")
NOT_PHOTOS = re.compile(r"\b(diagrams?|drawings?|schematics?|maps?|plans?|sections?|cutaway|cross[- ]?section|logos?|charts?|"
                        r"graphs?|schemes?|infographics?|blueprints?|icons?|flags?|svg|plots?|tables?|layouts?|elevations?)\b", re.I)


def _domain(url):
    return (urlparse(url).hostname or "").removeprefix("www.")


def _wiki_search(topic):
    try:
        r = httpx.get("https://en.wikipedia.org/w/api.php", headers=UA, timeout=12, params={
            "action": "query", "list": "search", "srsearch": topic, "srlimit": 2, "format": "json"})
        return [f"https://en.wikipedia.org/wiki/{h['title'].replace(' ', '_')}" for h in r.json()["query"]["search"]]
    except (httpx.HTTPError, KeyError, ValueError):
        return []


def gather(topic, queries, max_sources=5, chars=2500):
    """[{'n', 'title', 'url', 'text'}] from the most reliable pages found."""
    candidates = [(3, u) for u in _wiki_search(topic)]
    for q in [topic] + list(queries)[:3]:
        try:
            for r in web.search(q, max_results=6):
                d = _domain(r["url"])
                if not r["url"] or AVOID.search(d):
                    continue
                candidates.append((2 if TRUSTED.search(d) else 1, r["url"]))
        except Exception as e:  # search engines rate-limit sometimes; Wikipedia alone still works
            log.warning("search failed for %r: %s", q, e)
    seen_urls, seen_domains, sources = set(), {}, []
    for score, url in sorted(candidates, key=lambda c: -c[0]):
        d = _domain(url)
        if url in seen_urls or seen_domains.get(d, 0) >= 2:
            continue
        if score == 1 and len(sources) >= 3:  # with three reliable sources already, skip lesser-known sites
            continue
        seen_urls.add(url)
        page = web.fetch_page(url, max_chars=chars)
        if page.get("error") or len(page.get("text", "")) < 300:
            continue
        seen_domains[d] = seen_domains.get(d, 0) + 1
        sources.append({"n": len(sources) + 1, "title": page.get("title", d)[:120], "url": page["url"], "text": page["text"]})
        if len(sources) >= max_sources:
            break
    return sources


def _plain(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def image(query, folder, name):
    """Downloads one free-licence picture for `query` into folder. Returns {'path', 'credit'} or None."""
    try:
        r = httpx.get("https://commons.wikimedia.org/w/api.php", headers=UA, timeout=15, params={
            "action": "query", "generator": "search", "gsrsearch": f"filetype:bitmap {query}", "gsrnamespace": 6,
            "gsrlimit": 15, "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size", "iiurlwidth": 1280, "format": "json"})
        pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    except (httpx.HTTPError, ValueError):
        return None
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        lic = _plain(meta.get("LicenseShortName", {}).get("value", ""))
        if info.get("mime") not in ("image/jpeg", "image/png") or not re.search(r"CC|Public domain|PD", lic, re.I):
            continue
        if NOT_PHOTOS.search(p.get("title", "")):  # photos look better on slides than technical drawings
            continue
        if info.get("width", 0) < 500 or info.get("height", 0) < 300:
            continue
        url = info.get("thumburl") or info.get("url")
        try:
            img = httpx.get(url, headers=UA, timeout=30, follow_redirects=True)
            img.raise_for_status()
        except httpx.HTTPError:
            continue
        ext = ".png" if info["mime"] == "image/png" else ".jpg"
        path = folder / f"{name}{ext}"
        path.write_bytes(img.content)
        artist = _plain(meta.get("Artist", {}).get("value", "")) or "Unknown author"
        return {"path": str(path), "credit": f"Image: {artist[:60]}, {lic}, via Wikimedia Commons",
                "page": info.get("descriptionurl", "")}
    return None
