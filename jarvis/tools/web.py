"""Free web research: DuckDuckGo search (no key) plus readable page extraction."""
import ipaddress
import re
import socket
from urllib.parse import unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from ddgs import DDGS

# Wikipedia asks programs to name themselves with a contact link; generic library names get refused.
UA = {"User-Agent": "JarvisAssistant/1.0 (personal study assistant; https://github.com/ishanp2013/Jarvis)",
      "Accept-Language": "en-GB,en;q=0.8"}


def search(query, max_results=5):
    with DDGS() as d:
        rows = list(d.text(query, max_results=max_results, safesearch="moderate"))
    return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in rows]


def news(query, max_results=5):
    with DDGS() as d:
        rows = list(d.news(query, max_results=max_results))
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "date": r.get("date", ""),
             "source": r.get("source", ""), "snippet": r.get("body", "")} for r in rows]


def _public_host(url):
    host = urlparse(url).hostname or ""
    try:
        return not ipaddress.ip_address(socket.gethostbyname(host)).is_private
    except (OSError, ValueError):
        return False


def _wikipedia(url, lang, title, max_chars):
    """Wikipedia asks programs to use its API rather than scrape article pages."""
    try:
        r = httpx.get(f"https://{lang}.wikipedia.org/w/api.php", headers=UA, timeout=12, params={
            "action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "format": "json",
            "titles": unquote(title).replace("_", " ")})
        r.raise_for_status()
        page = next(iter(r.json()["query"]["pages"].values()))
    except (httpx.HTTPError, KeyError, ValueError) as e:
        return {"url": url, "error": f"Could not load the article: {e}"[:200]}
    return {"url": url, "title": page.get("title", title) + " - Wikipedia", "text": page.get("extract", "")[:max_chars]}


def fetch_page(url, max_chars=6000):
    """Main text of a public web page (local-network addresses are refused)."""
    if urlparse(url).scheme not in ("http", "https") or not _public_host(url):
        return {"url": url, "error": "Only public http(s) pages can be fetched."}
    if wiki := re.match(r"https?://(\w+)\.(?:m\.)?wikipedia\.org/wiki/([^#?]+)", url):
        return _wikipedia(url, wiki.group(1), wiki.group(2), max_chars)
    try:
        r = httpx.get(url, headers=UA, timeout=12, follow_redirects=True)
        r.raise_for_status()
    except httpx.HTTPError as e:
        return {"url": url, "error": f"Could not load the page: {e}"[:200]}
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    text = "\n".join(p.get_text(" ", strip=True) for p in root.find_all(["h1", "h2", "h3", "p", "li"]))
    title = soup.title.get_text(strip=True) if soup.title else url
    return {"url": str(r.url), "title": title, "text": text[:max_chars]}
