from __future__ import annotations

from urllib.parse import urlencode

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import clean_text, parse_datetime


class ArxivCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        try:
            import feedparser

            query = str(self.source.options.get("query", "cat:cs.AI"))
            limit = int(self.source.options.get("limit", 30))
            params = urlencode(
                {
                    "search_query": query,
                    "start": "0",
                    "max_results": str(limit),
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                }
            )
            response = await client.get(f"{self.source.url}?{params}")
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            items: list[RawItem] = []
            for entry in parsed.entries:
                entry_id = str(entry.get("id") or entry.get("link"))
                pdf_url = _pdf_url(entry)
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=entry_id,
                        title=clean_text(entry.get("title", "Untitled arXiv paper")),
                        url=pdf_url or entry_id,
                        published_at=parse_datetime(entry.get("published")),
                        author=", ".join(author.get("name", "") for author in entry.get("authors", [])),
                        content=clean_text(entry.get("summary", "")),
                        payload={
                            "connector": "arxiv",
                            "entry_url": entry_id,
                            "pdf_url": pdf_url,
                            "categories": [tag.get("term") for tag in entry.get("tags", [])],
                        },
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)


def _pdf_url(entry: object) -> str | None:
    for link in entry.get("links", []):
        if link.get("type") == "application/pdf":
            return str(link.get("href"))
    return None

