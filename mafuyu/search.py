"""Search providers behind the web_search tool (see research.py).

Providers are tried in order and the first that answers wins:
SearXNG, a self-hosted metasearch over Google/Bing/DDG (SEARXNG_URL) ->
Serper, i.e. Google results (SERPER_API_KEY) -> DuckDuckGo.
DuckDuckGo needs no key, so search keeps working when a key is missing, a free quota
runs out, or the SearXNG instance is down.
"""

import asyncio
import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from ddgs import DDGS

log = logging.getLogger(__name__)

SERPER_URL = "https://google.serper.dev/search"
SERPER_NEWS_URL = "https://google.serper.dev/news"
TIMEOUT_SEC = 15
MAX_RESULTS = 8
TRACKING_PARAMS = {"msockid", "fbclid", "gclid"}


def clean_url(url: str) -> str:
    """Drop tracking parameters (Bing adds msockid) so the same page is not listed twice."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in TRACKING_PARAMS and not k.startswith("utm_")]
    return urlunsplit(parts._replace(query=urlencode(query)))


class WebSearch:
    def __init__(self, searxng_url: str | None, serper_api_key: str | None):
        self._searxng_url = searxng_url.rstrip("/") if searxng_url else None
        self._serper_key = serper_api_key

    async def _searxng(self, query: str, topic: str, time_range: str | None) -> list[dict]:
        params = {"q": query, "format": "json", "language": "ja", "categories": topic}
        if time_range:
            params["time_range"] = time_range
        async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
            resp = await client.get(f"{self._searxng_url}/search", params=params)
            resp.raise_for_status()
            data = resp.json()
        results = data.get("results", [])
        if not results and data.get("unresponsive_engines"):
            # Every engine was blocked or timed out; let the next provider try.
            raise RuntimeError(f"no engine answered: {data['unresponsive_engines']}")
        rows, seen = [], set()
        for r in results:
            url = clean_url(r.get("url", ""))
            if url in seen:
                continue
            seen.add(url)
            date = r["publishedDate"][:10] if r.get("publishedDate") else ""
            rows.append({"title": r.get("title", ""), "url": url, "date": date,
                         "text": r.get("content") or ""})
            if len(rows) == MAX_RESULTS:
                break
        return rows

    async def _serper(self, query: str, topic: str, time_range: str | None) -> list[dict]:
        """Google results via Serper (serper.dev)."""
        body = {"q": query, "gl": "jp", "hl": "ja", "num": MAX_RESULTS}
        if time_range:
            body["tbs"] = f"qdr:{time_range[0]}"  # d / w / m / y
        url = SERPER_NEWS_URL if topic == "news" else SERPER_URL
        async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
            resp = await client.post(url, json=body, headers={"X-API-KEY": self._serper_key})
            resp.raise_for_status()
            return self.parse_serper(resp.json(), topic)

    @staticmethod
    def parse_serper(data: dict, topic: str) -> list[dict]:
        rows = []
        box = data.get("answerBox")
        if box and (box.get("answer") or box.get("snippet")):
            rows.append({"title": box.get("title") or "Googleの回答", "url": box.get("link", ""),
                         "text": box.get("answer") or box.get("snippet", "")})
        graph = data.get("knowledgeGraph")
        if graph and graph.get("description"):
            rows.append({"title": graph.get("title", ""), "url": graph.get("descriptionLink", ""),
                         "text": graph["description"]})
        for r in data.get("news" if topic == "news" else "organic", [])[:MAX_RESULTS]:
            date = f"{r['date']} " if r.get("date") else ""
            rows.append({"title": r.get("title", ""), "url": r.get("link", ""),
                         "text": date + r.get("snippet", "")})
        return rows

    async def _ddg(self, query: str, topic: str, time_range: str | None) -> list[dict]:
        return await asyncio.to_thread(self._ddg_sync, query, topic, time_range)

    @staticmethod
    def _ddg_sync(query: str, topic: str, time_range: str | None) -> list[dict]:
        timelimit = {"day": "d", "week": "w", "month": "m", "year": "y"}.get(time_range or "")
        ddgs = DDGS()
        if topic == "news":
            rows = ddgs.news(query, region="jp-jp", timelimit=timelimit, max_results=MAX_RESULTS)
            return [{"title": r.get("title", ""), "url": r.get("url", ""),
                     "text": f"{r.get('date', '')} {r.get('body', '')}"} for r in rows]
        rows = ddgs.text(query, region="jp-jp", timelimit=timelimit, max_results=MAX_RESULTS)
        return [{"title": r.get("title", ""), "url": r.get("href", ""), "text": r.get("body", "")}
                for r in rows]

    async def results(self, query: str, topic: str = "general",
                      time_range: str | None = None) -> list[dict] | None:
        """Raw result rows from the first provider that answers, or None if all failed."""
        topic = topic if topic in ("general", "news") else "general"
        if time_range not in (None, "day", "week", "month", "year"):
            time_range = None

        # Try providers in order of result quality; DuckDuckGo needs no key and is the last resort.
        providers = []
        if self._searxng_url:
            providers.append(("SearXNG", self._searxng))
        if self._serper_key:
            providers.append(("Serper", self._serper))
        providers.append(("DuckDuckGo", self._ddg))

        results, source = None, ""
        for source, provider in providers:
            try:
                results = await asyncio.wait_for(provider(query, topic, time_range), TIMEOUT_SEC)
                break
            except Exception as e:
                log.warning("%s search failed for %r: %s", source, query, e)
        if results is not None:
            log.info("search via %s: %r (%d results)", source, query, len(results))
        return results

