from __future__ import annotations

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import clean_text, parse_datetime


class StockTwitsCollector(BaseCollector):
    """Trending StockTwits messages (retail FinTwit sentiment), carrying like counts.

    Best-effort: StockTwits rate-limits unauthenticated access, so failures degrade gracefully.
    """

    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        try:
            limit = int(self.source.options.get("limit", 25))
            base_url = str(self.source.url).rstrip("/")
            response = await client.get(f"{base_url}/streams/trending.json")
            response.raise_for_status()
            messages = response.json().get("messages", [])
            items: list[RawItem] = []
            for message in messages[:limit]:
                message_id = message.get("id")
                if not message_id:
                    continue
                user = message.get("user") or {}
                username = user.get("username")
                body = message.get("body") or ""
                symbols = [s.get("symbol") for s in message.get("symbols", []) if s.get("symbol")]
                likes = (message.get("likes") or {}).get("total")
                url = f"https://stocktwits.com/{username}/message/{message_id}"
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=str(message_id),
                        title=clean_text(body, max_chars=120) or "StockTwits message",
                        url=url,
                        published_at=parse_datetime(message.get("created_at")),
                        author=username,
                        content=body,
                        payload={
                            "connector": "stocktwits",
                            "watchlist_count": likes,
                            "message_count": message.get("reshares", {}).get("reshared_count")
                            if isinstance(message.get("reshares"), dict)
                            else None,
                            "symbols": symbols,
                        },
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)
