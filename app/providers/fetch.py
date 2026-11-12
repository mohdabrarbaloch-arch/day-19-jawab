"""Downloading and cleaning the pages we cite.

Two rules here, both about not lying to the reader:

  * We only cite a page we actually downloaded. If the fetch fails, the
    source is still listed (the search engine found it) but it is marked
    `fetched=False` and the answer never quotes it.
  * We cap the bytes we read. A 40 MB page is not a source, it's a problem.
"""

from __future__ import annotations

import asyncio
import re

import httpx

from app.config import settings
from app.engine.answer import SourceDoc
from app.providers.search import SearchResult, domain_of

_SCRIPT = re.compile(
    r"<(script|style|noscript|svg|iframe)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE
)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_TAG = re.compile(
    r"</?(p|div|br|li|tr|h[1-6]|section|article|header|footer|blockquote)[^>]*>",
    re.IGNORECASE,
)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")

# Pages that are almost never the answer, even when they rank.
_SKIP_HOSTS = (
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "twitter.com",
    "x.com",
    "pinterest.com",
    "linkedin.com",
    "reddit.com",
)


def html_to_text(raw: str) -> str:
    """Strip a page down to readable prose.

    Deliberately crude: kill scripts and styles, turn block tags into
    newlines so paragraphs stay separate, drop the rest of the markup,
    unescape entities, collapse whitespace.
    """
    import html as html_mod

    text = _COMMENT.sub(" ", raw)
    text = _SCRIPT.sub(" ", text)
    text = _BLOCK_TAG.sub("\n", text)
    text = _TAG.sub(" ", text)
    text = html_mod.unescape(text)
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _NL.sub("\n\n", text)
    return text.strip()


def _should_skip(url: str) -> bool:
    host = domain_of(url)
    return any(s in host for s in _SKIP_HOSTS)


async def fetch_one(client: httpx.AsyncClient, result: SearchResult) -> SourceDoc:
    """Fetch and clean a single result. Never raises."""
    base = SourceDoc(
        title=result.title,
        url=result.url,
        domain=result.domain or domain_of(result.url),
        text="",
        snippet=result.snippet,
        fetched=False,
    )

    if _should_skip(result.url):
        return base

    try:
        resp = await client.get(result.url)
    except (httpx.HTTPError, ValueError):
        return base

    if resp.status_code != 200:
        return base

    ctype = resp.headers.get("content-type", "").lower()
    if "html" not in ctype and "text" not in ctype:
        return base

    raw = resp.text[: settings.max_page_bytes]
    text = html_to_text(raw)

    # A page with almost no prose is a paywall, a JS shell, or a 404 page.
    if len(text) < 400:
        return base

    base.text = text
    base.fetched = True
    return base


async def fetch_many(
    results: list[SearchResult], limit: int | None = None
) -> list[SourceDoc]:
    """Fetch several pages concurrently, preserving the search order."""
    limit = limit or settings.fetch_pages
    targets = results[:limit]
    if not targets:
        return []

    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    limits = httpx.Limits(max_connections=6, max_keepalive_connections=3)

    async with httpx.AsyncClient(
        timeout=settings.fetch_timeout_seconds,
        follow_redirects=True,
        headers=headers,
        limits=limits,
    ) as client:
        docs = await asyncio.gather(
            *(fetch_one(client, r) for r in targets), return_exceptions=True
        )

    out: list[SourceDoc] = []
    for i, doc in enumerate(docs):
        if isinstance(doc, BaseException):
            r = targets[i]
            out.append(
                SourceDoc(
                    title=r.title,
                    url=r.url,
                    domain=r.domain or domain_of(r.url),
                    text="",
                    snippet=r.snippet,
                    fetched=False,
                )
            )
        else:
            out.append(doc)
    return out
