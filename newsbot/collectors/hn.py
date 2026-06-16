from __future__ import annotations

from datetime import UTC, datetime

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import parse_datetime


class HackerNewsCollector(BaseCollector):
    """Collect Hacker News stories via the Algolia search API.

    Uses the front-page / points-threshold query rather than the ``topstories`` firehose so we
    ingest what is actually being discussed. Algolia returns ``points`` and ``num_comments``
    directly, which feed the engagement (buzz) score.
    """

    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        try:
            options = self.source.options
            limit = int(options.get("limit", 50))
            min_points = int(options.get("min_points", 0))
            # Default to the Algolia endpoint; legacy Firebase URLs are normalized below.
            base_url = str(self.source.url).rstrip("/")
            if "algolia" not in base_url:
                base_url = "https://hn.algolia.com/api/v1"
            tags = options.get("tags", "front_page")
            params: dict[str, str] = {
                "tags": str(tags),
                "hitsPerPage": str(limit),
            }
            if min_points > 0:
                params["numericFilters"] = f"points>={min_points}"
            response = await client.get(f"{base_url}/search", params=params)
            response.raise_for_status()
            hits = response.json().get("hits", [])
            items: list[RawItem] = []
            for hit in hits:
                story_id = hit.get("objectID")
                if not story_id:
                    continue
                comments_url = f"https://news.ycombinator.com/item?id={story_id}"
                title = hit.get("title") or hit.get("story_title") or "Untitled HN story"
                url = hit.get("url") or hit.get("story_url") or comments_url
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=str(story_id),
                        title=title,
                        url=url,
                        published_at=parse_datetime(_created_at(hit)),
                        author=hit.get("author"),
                        content=hit.get("story_text") or hit.get("comment_text"),
                        payload={
                            "connector": "hn",
                            "score": hit.get("points"),
                            "comments": hit.get("num_comments"),
                            "comments_url": comments_url,
                        },
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)


def _created_at(hit: dict) -> str | None:
    value = hit.get("created_at")
    if value:
        return str(value)
    timestamp = hit.get("created_at_i")
    if timestamp:
        return datetime.fromtimestamp(int(timestamp), UTC).isoformat()
    return None
