from __future__ import annotations

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import parse_datetime


class LobstersCollector(BaseCollector):
    """Lobste.rs hottest stories via the public JSON endpoint (carries upvote score)."""

    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        try:
            limit = int(self.source.options.get("limit", 25))
            base_url = str(self.source.url).rstrip("/")
            response = await client.get(f"{base_url}/hottest.json")
            response.raise_for_status()
            stories = response.json()
            items: list[RawItem] = []
            for story in stories[:limit]:
                short_id = story.get("short_id")
                comments_url = story.get("comments_url")
                url = story.get("url") or comments_url
                if not url:
                    continue
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=str(short_id or url),
                        title=story.get("title") or "Untitled Lobsters story",
                        url=url,
                        published_at=parse_datetime(story.get("created_at")),
                        author=(story.get("submitter_user") or {}).get("username")
                        if isinstance(story.get("submitter_user"), dict)
                        else story.get("submitter_user"),
                        content=story.get("description_plain") or story.get("description"),
                        payload={
                            "connector": "lobsters",
                            "score": story.get("score"),
                            "comments": story.get("comment_count"),
                            "comments_url": comments_url,
                        },
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)
