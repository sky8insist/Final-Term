import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx

from app.config.settings import settings
from app.services.mock_external_service import mock_public_search


class ExternalSearchError(RuntimeError):
    pass


INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE) for pattern in (
        r"ignore (all|the) previous instructions", r"system prompt", r"developer message",
        r"you are now", r"do not follow", r"tool call",
        r"忽略(以上|之前|所有).{0,12}(指令|要求)", r"(泄露|显示|输出).{0,8}(系统提示词|开发者消息)",
        r"你现在是", r"调用.{0,8}(工具|函数)",
    )
]


def _trust_level(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith((".gov", ".gov.cn", ".edu", ".edu.cn")):
        return "high"
    if any(domain in host for domain in ("who.int", "nature.com", "science.org", "arxiv.org", "wikipedia.org")):
        return "medium"
    return "unrated"


def _sanitize(text: str, limit: int = 4000) -> str:
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text).strip()
    lines = [line for line in cleaned.splitlines() if not any(pattern.search(line) for pattern in INJECTION_PATTERNS)]
    return "\n".join(lines)[:limit]


async def search_web_async(query: str, max_results: int | None = None) -> list[dict]:
    if not settings.web_search_url or not settings.web_search_api_key:
        raise ExternalSearchError("Web search is not configured")
    limit = min(max(max_results or settings.web_search_max_results, 1), 10)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                settings.web_search_url,
                headers={"Authorization": f"Bearer {settings.web_search_api_key}", "Content-Type": "application/json"},
                json={"query": query, "max_results": limit, "search_depth": "advanced"},
            )
            response.raise_for_status()
            rows = response.json().get("results", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise ExternalSearchError("Web search failed") from exc
    accessed_at = datetime.now(UTC).isoformat()
    results = []
    for row in rows[:limit]:
        url = str(row.get("url", "")).strip()
        content = _sanitize(str(row.get("content") or row.get("snippet") or ""))
        if not url or not content:
            continue
        results.append({
            "title": _sanitize(str(row.get("title") or url), 300), "url": url,
            "content": content, "publishedAt": row.get("published_date"),
            "accessedAt": accessed_at, "trustLevel": _trust_level(url),
            "score": row.get("score"),
        })
    return results


async def search_wikipedia_async(query: str, max_results: int | None = None) -> list[dict]:
    """Key-free public fallback through the official MediaWiki API."""
    limit = min(max(max_results or 3, 1), 5)
    endpoint = f"https://{settings.wikipedia_language}.wikipedia.org/w/api.php"
    try:
        async with httpx.AsyncClient(
            timeout=20, headers={"User-Agent": "ExamAI/1.0 educational-assistant"},
        ) as client:
            response = await client.get(endpoint, params={
                "action": "query", "generator": "search", "gsrsearch": query,
                "gsrlimit": limit, "prop": "extracts|info", "exintro": 1,
                "explaintext": 1, "inprop": "url", "format": "json", "formatversion": 2,
            })
            response.raise_for_status()
            pages = response.json().get("query", {}).get("pages", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        raise ExternalSearchError("Wikipedia search failed") from exc
    accessed_at = datetime.now(UTC).isoformat()
    return [{
        "title": _sanitize(str(page.get("title") or ""), 300),
        "url": str(page.get("fullurl") or ""),
        "content": _sanitize(str(page.get("extract") or "")),
        "publishedAt": None, "accessedAt": accessed_at,
        "trustLevel": "medium", "score": None, "provider": "wikipedia",
    } for page in pages if page.get("fullurl") and page.get("extract")]


async def search_public_knowledge_async(query: str, max_results: int | None = None) -> list[dict]:
    """Prefer configured web search, then use Wikipedia without an API key."""
    if settings.mock_external_apis:
        return mock_public_search(query)[:max_results]
    if settings.web_search_url and settings.web_search_api_key:
        try:
            rows = await search_web_async(query, max_results=max_results)
            if rows:
                return rows
        except ExternalSearchError:
            pass
    if settings.enable_wikipedia_fallback:
        return await search_wikipedia_async(query, max_results=max_results)
    raise ExternalSearchError("No public knowledge provider is available")
