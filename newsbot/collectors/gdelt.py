from __future__ import annotations

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import parse_datetime


class GdeltCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        try:
            params = {
                "query": str(self.source.options.get("query", "AI technology stocks")),
                "mode": "artlist",
                "format": "json",
                "maxrecords": str(int(self.source.options.get("limit", 50))),
                "sort": "hybridrel",
            }
            response = await client.get(self.source.url, params=params)
            response.raise_for_status()
            data = response.json()
            items = []
            for article in data.get("articles", []):
                url = article.get("url")
                if not url:
                    continue
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=url,
                        title=article.get("title") or "Untitled GDELT article",
                        url=url,
                        published_at=parse_datetime(article.get("seendate")),
                        author=article.get("domain"),
                        payload={
                            "connector": "gdelt",
                            "domain": article.get("domain"),
                            "language": article.get("language"),
                            "source_country": article.get("sourcecountry"),
                            "image": article.get("socialimage"),
                        },
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)

