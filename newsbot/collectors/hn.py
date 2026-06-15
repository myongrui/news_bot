from __future__ import annotations

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import parse_datetime


class HackerNewsCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        try:
            limit = int(self.source.options.get("limit", 50))
            base_url = self.source.url.rstrip("/")
            ids_response = await client.get(f"{base_url}/topstories.json")
            ids_response.raise_for_status()
            story_ids = ids_response.json()[:limit]
            items: list[RawItem] = []
            for story_id in story_ids:
                response = await client.get(f"{base_url}/item/{story_id}.json")
                if response.status_code >= 400:
                    continue
                story = response.json() or {}
                if story.get("type") != "story":
                    continue
                title = story.get("title") or "Untitled HN story"
                url = story.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=str(story_id),
                        title=title,
                        url=url,
                        published_at=parse_datetime(_unix_to_iso(story.get("time"))),
                        author=story.get("by"),
                        content=story.get("text"),
                        payload={
                            "connector": "hn",
                            "score": story.get("score"),
                            "comments_url": f"https://news.ycombinator.com/item?id={story_id}",
                        },
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)


def _unix_to_iso(value: int | None) -> str | None:
    if not value:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(int(value), UTC).isoformat()

