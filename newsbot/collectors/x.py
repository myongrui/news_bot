from __future__ import annotations

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import parse_datetime


class XCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        token = self.config.settings.x_bearer_token
        if not token:
            return self.disabled("Missing X_BEARER_TOKEN")
        try:
            params = {
                "query": str(self.source.options.get("query", "AI lang:en -is:retweet")),
                "max_results": str(min(max(int(self.source.options.get("limit", 25)), 10), 100)),
                "tweet.fields": "created_at,author_id,public_metrics,entities",
                "expansions": "author_id",
                "user.fields": "username,name,verified",
            }
            response = await client.get(
                self.source.url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            response.raise_for_status()
            data = response.json()
            users = {
                user.get("id"): user
                for user in data.get("includes", {}).get("users", [])
                if user.get("id")
            }
            items: list[RawItem] = []
            for post in data.get("data", []):
                author = users.get(post.get("author_id"), {})
                username = author.get("username") or post.get("author_id")
                post_id = post.get("id")
                post_url = f"https://x.com/{username}/status/{post_id}"
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=str(post_id),
                        title=post.get("text", "Untitled X post")[:120],
                        url=post_url,
                        published_at=parse_datetime(post.get("created_at")),
                        author=username,
                        content=post.get("text"),
                        payload={
                            "connector": "x",
                            "metrics": post.get("public_metrics", {}),
                            "author_verified": author.get("verified"),
                        },
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)

