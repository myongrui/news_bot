from __future__ import annotations

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import parse_datetime


class RedditCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        settings = self.config.settings
        if not settings.reddit_client_id or not settings.reddit_client_secret:
            return self.disabled("Missing REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET")
        try:
            token_response = await client.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(settings.reddit_client_id, settings.reddit_client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": settings.reddit_user_agent},
            )
            token_response.raise_for_status()
            token = token_response.json()["access_token"]
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": settings.reddit_user_agent,
            }
            limit = int(self.source.options.get("limit", 25))
            subreddits = self.source.options.get("subreddits", [])
            items: list[RawItem] = []
            for subreddit in subreddits:
                response = await client.get(
                    f"https://oauth.reddit.com/r/{subreddit}/hot",
                    params={"limit": str(limit), "raw_json": "1"},
                    headers=headers,
                )
                if response.status_code >= 400:
                    continue
                data = response.json()
                for child in data.get("data", {}).get("children", []):
                    post = child.get("data", {})
                    permalink = post.get("permalink")
                    post_url = f"https://www.reddit.com{permalink}" if permalink else post.get("url")
                    title = post.get("title") or "Untitled Reddit post"
                    content = post.get("selftext") or ""
                    items.append(
                        RawItem(
                            source_id=self.source.id,
                            external_id=post.get("name") or post_url,
                            title=title,
                            url=post.get("url") or post_url,
                            published_at=parse_datetime(_unix_to_iso(post.get("created_utc"))),
                            author=post.get("author"),
                            content=content,
                            payload={
                                "connector": "reddit",
                                "subreddit": subreddit,
                                "score": post.get("score"),
                                "comments_url": post_url,
                                "num_comments": post.get("num_comments"),
                            },
                        )
                    )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)


def _unix_to_iso(value: int | float | None) -> str | None:
    if not value:
        return None
    from datetime import UTC, datetime

    return datetime.fromtimestamp(float(value), UTC).isoformat()

