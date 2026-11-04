"""Lightweight web research for production references (DuckDuckGo HTML)."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)


async def web_search(query: str, *, limit: int = 5) -> list[dict[str, str]]:
    """Best-effort public web search. Returns [{title,url,snippet}]."""
    q = " ".join(str(query).split())
    if not q:
        return []
    results: list[dict[str, str]] = []
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            html = r.text
        # Parse result blocks without heavy deps
        blocks = re.findall(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'class="result__snippet"[^>]*>(.*?)</(?:a|td|div)',
            html,
            flags=re.I | re.S,
        )
        for href, title, snippet in blocks:
            clean_title = _strip_tags(title)
            clean_snip = _strip_tags(snippet)
            link = _unwrap_ddg(href)
            if not clean_title or not link:
                continue
            results.append({"title": clean_title, "url": link, "snippet": clean_snip})
            if len(results) >= limit:
                break
    except Exception as exc:
        logger.warning("web_search failed for %r: %s", q, exc)
    return results


async def gather_references(topic: str, *, limit: int = 5) -> dict[str, Any]:
    queries = [
        f"{topic} cinematic short film reference",
        f"{topic} photoreal lifestyle video shot list",
        f"{topic} youtube shorts tiktok caption ideas",
    ]
    refs: list[dict[str, str]] = []
    seen: set[str] = set()
    for q in queries:
        for item in await web_search(q, limit=3):
            u = item.get("url") or ""
            if u in seen:
                continue
            seen.add(u)
            refs.append(item)
            if len(refs) >= limit:
                break
        if len(refs) >= limit:
            break
    return {"query": topic, "references": refs}


def _strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _unwrap_ddg(href: str) -> str:
    # DuckDuckGo wraps as //duckduckgo.com/l/?uddg=<encoded>
    m = re.search(r"[?&]uddg=([^&]+)", href)
    if m:
        from urllib.parse import unquote

        return unquote(m.group(1))
    if href.startswith("//"):
        return "https:" + href
    return href
