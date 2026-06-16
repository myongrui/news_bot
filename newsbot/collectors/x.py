from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import parse_datetime

# Unauthenticated syndication endpoint used by embedded profile widgets. This is an unofficial,
# best-effort path (the paid v2 API is not available) — it can change or rate-limit without
# notice, so the collector tolerates per-handle failures and degrades gracefully. Public posts
# only; no login, no paywall bypass.
#
# X aggressively rate-limits (HTTP 429) this endpoint from datacenter IPs. The base host is
# configurable via source.url so it can be routed through a residential egress / proxy / mirror;
# requests are paced with jitter and retried with backoff to avoid self-inflicting limits.
_PATH = "/srv/timeline-profile/screen-name/{handle}"
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://platform.twitter.com/",
}
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.DOTALL
)


class XCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        accounts = [str(handle).lstrip("@") for handle in self.source.options.get("accounts", [])]
        if not accounts:
            return self.disabled("No X accounts configured (options.accounts)")
        options = self.source.options
        per_account = int(options.get("limit", 15))
        pace_seconds = float(options.get("pace_seconds", 3.0))
        max_retries = int(options.get("max_retries", 2))
        base = str(self.source.url).rstrip("/")
        items: list[RawItem] = []
        errors: list[str] = []
        rate_limited = False
        for index, handle in enumerate(accounts):
            if index:
                await asyncio.sleep(pace_seconds + random.uniform(0, pace_seconds))
            try:
                response = await self._fetch(client, base, handle, max_retries)
                tweets = _parse_timeline(response.text)
                for tweet in tweets[:per_account]:
                    item = _tweet_to_item(self.source.id, handle, tweet)
                    if item is not None:
                        items.append(item)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    rate_limited = True
                errors.append(f"{handle}: {exc}")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{handle}: {exc}")
        if not items and rate_limited:
            # Distinct status so /health surfaces "throttled by X", not a generic error.
            return CollectorResult(items=[], status="rate_limited", error="; ".join(errors[:5]))
        if not items and errors:
            return self.failed("; ".join(errors[:5]))
        status = "ok" if not errors else "partial"
        return CollectorResult(items=items, status=status, error="; ".join(errors[:5]) or None)

    async def _fetch(
        self, client: httpx.AsyncClient, base: str, handle: str, max_retries: int
    ) -> httpx.Response:
        url = base + _PATH.format(handle=handle)
        last: httpx.Response | None = None
        for attempt in range(max_retries + 1):
            response = await client.get(url, headers=_BROWSER_HEADERS)
            if response.status_code != 429:
                response.raise_for_status()
                return response
            last = response
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt + random.uniform(0, 1))
        assert last is not None
        last.raise_for_status()
        return last


def _parse_timeline(html: str) -> list[dict[str, Any]]:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    entries = (
        data.get("props", {})
        .get("pageProps", {})
        .get("timeline", {})
        .get("entries", [])
    )
    tweets: list[dict[str, Any]] = []
    for entry in entries:
        tweet = entry.get("content", {}).get("tweet") if isinstance(entry, dict) else None
        if isinstance(tweet, dict):
            tweets.append(tweet)
    return tweets


def _tweet_to_item(source_id: str, handle: str, tweet: dict[str, Any]) -> RawItem | None:
    tweet_id = tweet.get("id_str") or tweet.get("id")
    if not tweet_id:
        return None
    text = tweet.get("full_text") or tweet.get("text") or ""
    user = tweet.get("user") or {}
    username = user.get("screen_name") or handle
    url = f"https://x.com/{username}/status/{tweet_id}"
    metrics = {
        "like_count": tweet.get("favorite_count"),
        "retweet_count": tweet.get("retweet_count"),
        "reply_count": tweet.get("reply_count"),
        "quote_count": tweet.get("quote_count"),
    }
    return RawItem(
        source_id=source_id,
        external_id=str(tweet_id),
        title=(text or "Untitled X post")[:120],
        url=url,
        published_at=parse_datetime(tweet.get("created_at")),
        author=username,
        content=text,
        payload={
            "connector": "x",
            "metrics": metrics,
            "author_verified": user.get("verified"),
        },
    )
