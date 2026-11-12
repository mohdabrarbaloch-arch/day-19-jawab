"""Web search, with no API key required.

Two backends, tried in order:

  1. DuckDuckGo's HTML endpoint — real web results, no key, no quota.
  2. Wikipedia's search API — a narrower but very reliable fallback for
     when DDG rate-limits us or the network blocks it.

Both return the same `SearchResult` shape, so the rest of the app never
knows which one answered. If both fail we return an empty list and the
caller says so honestly rather than inventing results.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.config import settings

_DDG_HTML = "https://html.duckduckgo.com/html/"
_DDG_LITE = "https://lite.duckduckgo.com/lite/"

# DDG's HTML endpoint answers a plain bot UA with a 202 challenge page. A
# normal browser UA over GET gets real results, so that is what we send.
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_WIKI_API = "https://en.wikipedia.org/w/api.php"

_RESULT_BLOCK = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'.*?(?:<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>'
    r'|<div[^>]+class="result__snippet"[^>]*>(?P<snippet2>.*?)</div>)?',
    re.DOTALL,
)
_LITE_BLOCK = re.compile(
    r'<a[^>]+class="result-link"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'.*?(?:<td[^>]+class="result-snippet"[^>]*>(?P<snippet>.*?)</td>)?',
    re.S,
)
_TAG = re.compile(r"<[^>]+>")


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    domain: str = ""

    def __post_init__(self) -> None:
        if not self.domain:
            self.domain = domain_of(self.url)


def domain_of(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    host = host.removeprefix("www.")
    return host


def _strip_tags(raw: str) -> str:
    text = _TAG.sub(" ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _unwrap_ddg(href: str) -> str:
    """DDG wraps outbound links in /l/?uddg=<encoded>. Unwrap them."""
    if href.startswith("//"):
        href = "https:" + href
    if "duckduckgo.com/l/" in href:
        qs = parse_qs(urlparse(href).query)
        target = qs.get("uddg", [""])[0]
        if target:
            return unquote(target)
    return href


def _is_usable(url: str) -> bool:
    if not url.startswith(("http://", "https://")):
        return False
    host = domain_of(url)
    if not host:
        return False
    # DDG's own pages and ad redirects are not sources.
    blocked = ("duckduckgo.com", "bing.com", "google.com/url")
    return not any(b in host + url for b in blocked)


async def _search_duckduckgo(query: str, limit: int) -> list[SearchResult]:
    """DuckDuckGo's HTML endpoint over GET with a browser UA.

    POST with a bot UA gets a 202 challenge; GET with a browser UA gets
    results. If the HTML endpoint still refuses, the lite endpoint is tried.
    """
    headers = {
        "User-Agent": _BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://duckduckgo.com/",
    }

    bodies: list[str] = []
    async with httpx.AsyncClient(
        timeout=settings.fetch_timeout_seconds, follow_redirects=True, headers=headers
    ) as client:
        try:
            resp = await client.get(_DDG_HTML, params={"q": query, "kl": "us-en"})
            if resp.status_code == 200:
                bodies.append(resp.text)
        except httpx.HTTPError:
            pass

        if not bodies or "result__a" not in bodies[0]:
            try:
                resp = await client.get(_DDG_LITE, params={"q": query})
                if resp.status_code == 200:
                    bodies.append(resp.text)
            except httpx.HTTPError:
                pass

    for body in bodies:
        results = _parse_ddg(body, limit)
        if results:
            return results
    return []


def _parse_ddg(body: str, limit: int) -> list[SearchResult]:
    """Pull results out of either DDG HTML layout."""
    results: list[SearchResult] = []
    seen: set[str] = set()

    for match in _RESULT_BLOCK.finditer(body):
        url = _unwrap_ddg(html.unescape(match.group("href") or ""))
        if not _is_usable(url) or url in seen:
            continue
        title = _strip_tags(match.group("title") or "")
        snippet = _strip_tags(match.group("snippet") or match.group("snippet2") or "")
        if not title:
            continue
        seen.add(url)
        results.append(SearchResult(title=title, url=url, snippet=snippet))
        if len(results) >= limit:
            break

    if results:
        return results

    # Lite layout: plain <a class="result-link"> plus a snippet cell.
    for match in _LITE_BLOCK.finditer(body):
        url = _unwrap_ddg(html.unescape(match.group("href") or ""))
        if not _is_usable(url) or url in seen:
            continue
        title = _strip_tags(match.group("title") or "")
        if not title:
            continue
        seen.add(url)
        results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=_strip_tags(match.group("snippet") or ""),
            )
        )
        if len(results) >= limit:
            break

    return results


async def _search_wikipedia(query: str, limit: int) -> list[SearchResult]:
    params = {
        "action": "query",
        "list": "search",
        "srsearch": query,
        "format": "json",
        "srlimit": str(limit),
        "srprop": "snippet",
    }
    async with httpx.AsyncClient(
        timeout=settings.fetch_timeout_seconds, follow_redirects=True
    ) as client:
        resp = await client.get(
            _WIKI_API, params=params, headers={"User-Agent": settings.user_agent}
        )
        if resp.status_code != 200:
            return []
        data = resp.json()

    out: list[SearchResult] = []
    for item in data.get("query", {}).get("search", []):
        title = item.get("title", "")
        if not title:
            continue
        out.append(
            SearchResult(
                title=title,
                url=f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
                snippet=_strip_tags(item.get("snippet", "")),
            )
        )
    return out


async def search(query: str, limit: int | None = None) -> list[SearchResult]:
    """Search the web. Returns [] if every backend failed — never fake data."""
    limit = limit or settings.search_results
    query = query.strip()
    if not query:
        return []

    for backend in (_search_duckduckgo, _search_wikipedia):
        try:
            results = await backend(query, limit)
        except (httpx.HTTPError, ValueError, KeyError):
            continue
        if results:
            return results

    return []
