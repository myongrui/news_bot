from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.types import RawItem
from newsbot.utils import parse_datetime


class GitHubTrendingCollector(BaseCollector):
    """Trending repos via the public GitHub search API (no auth, rate-limited).

    Approximates "trending" as recently-active repos matching a query, sorted by stars. Star
    count flows into the engagement (buzz) score.
    """

    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        try:
            options = self.source.options
            limit = int(options.get("limit", 25))
            window_days = int(options.get("window_days", 14))
            query = str(options.get("query", "topic:ai"))
            since = (datetime.now(UTC) - timedelta(days=window_days)).date().isoformat()
            base_url = str(self.source.url).rstrip("/")
            params = {
                "q": f"{query} pushed:>={since}",
                "sort": "stars",
                "order": "desc",
                "per_page": str(min(limit, 100)),
            }
            response = await client.get(
                f"{base_url}/search/repositories",
                params=params,
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            repos = response.json().get("items", [])
            items: list[RawItem] = []
            for repo in repos[:limit]:
                url = repo.get("html_url")
                if not url:
                    continue
                items.append(
                    RawItem(
                        source_id=self.source.id,
                        external_id=str(repo.get("id") or url),
                        title=repo.get("full_name") or "Untitled repo",
                        url=url,
                        published_at=parse_datetime(repo.get("pushed_at") or repo.get("created_at")),
                        author=(repo.get("owner") or {}).get("login"),
                        content=repo.get("description"),
                        payload={
                            "connector": "github_trending",
                            "stars": repo.get("stargazers_count"),
                        },
                    )
                )
            return CollectorResult(items=items)
        except Exception as exc:  # noqa: BLE001
            return self.failed(exc)
