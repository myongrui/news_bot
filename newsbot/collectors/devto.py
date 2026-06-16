from __future__ import annotations

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import parse_datetime


class DevToCollector(BaseCollector):
    """Dev.to top articles via the public API (carries reactions + comment counts)."""

    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        try:
            options = self.source.options
            limit = int(options.get("limit", 25))
            base_url = str(self.source.url).rstrip("/")
            params: dict[str, str] = {"per_page": str(limit)}
            if options.get("tag"):
                params["tag"] = str(options["tag"])
            # ``top`` = most reacted articles in the last N days.
            params["top"] = str(options.get("top_days", 1))
            response = await client.get(f"{base_url}/articles", params=params)
            response.raise_for_status()
            articles = response.json()
            items: list[RawItem] = []
            for article in articles:
                url = article.get("url")
                if not url:
                    continue
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=str(article.get("id") or url),
                        title=article.get("title") or "Untitled Dev.to article",
                        url=url,
                        published_at=parse_datetime(
                            article.get("published_at") or article.get("published_timestamp")
                        ),
                        author=(article.get("user") or {}).get("username"),
                        content=article.get("description"),
                        payload={
                            "connector": "devto",
                            "positive_reactions_count": article.get("positive_reactions_count"),
                            "comments_count": article.get("comments_count"),
                        },
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)
