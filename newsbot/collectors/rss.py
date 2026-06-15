from __future__ import annotations

import time

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import clean_text, parse_datetime, strip_html


class RssCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        try:
            response = await client.get(self.source.url)
            response.raise_for_status()
            import feedparser

            parsed = feedparser.parse(response.content)
            items: list[RawItem] = []
            limit = int(self.source.options.get("limit", len(parsed.entries)))
            for entry in parsed.entries[:limit]:
                published = _entry_time(entry)
                link = entry.get("link") or entry.get("id") or self.source.url
                title = clean_text(entry.get("title", "Untitled"))
                content = _entry_content(entry)
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=str(entry.get("id") or link),
                        title=title,
                        url=link,
                        published_at=published,
                        author=entry.get("author"),
                        content=content,
                        payload={"connector": "rss"},
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)


def _entry_time(entry: object) -> str | None:
    published = getattr(entry, "published", None) or getattr(entry, "updated", None)
    parsed = parse_datetime(published)
    if parsed:
        return parsed
    for attr in ("published_parsed", "updated_parsed"):
        value = getattr(entry, attr, None)
        if value:
            return parse_datetime(time.strftime("%Y-%m-%dT%H:%M:%SZ", value))
    return None


def _entry_content(entry: object) -> str | None:
    if getattr(entry, "content", None):
        content = entry.content[0]
        if isinstance(content, dict):
            return strip_html(content.get("value", ""))
        return strip_html(getattr(content, "value", ""))
    summary = getattr(entry, "summary", None)
    return strip_html(summary) if summary else None
