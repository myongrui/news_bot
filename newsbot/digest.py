from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from newsbot.ai import AiValidationError, LocalStructuredClient, make_ai_client
from newsbot.config import AppConfig, load_app_config
from newsbot.curation import CurationPolicy
from newsbot.db import Database
from newsbot.telegram import format_digest_message
from newsbot.utils import digest_id as make_digest_id
from newsbot.utils import normalize_title, period_bounds


# TLDR-style section taxonomy, in display order.
SECTION_ORDER = ["ai", "markets", "novelty"]
SECTION_TITLES = {
    "ai": "🚀 AI & Launches",
    "markets": "📈 Markets & Stocks",
    "novelty": "🔬 Frontier & Novelty",
}
_MARKET_TOPICS = {"markets", "blue_chips", "analyst_ratings", "filings"}
_NOVELTY_TOPICS = {"research", "developer_tools", "devops"}


def section_for(topics: list[str], tickers: list[str], frontier_category: str | None) -> str:
    topic_set = set(topics or [])
    if tickers or (topic_set & _MARKET_TOPICS) or frontier_category == "market_impact":
        return "markets"
    if "ai" in topic_set:
        return "ai"
    if (topic_set & _NOVELTY_TOPICS) or frontier_category == "technical_frontier":
        return "novelty"
    return "novelty"


def read_time_minutes(text: str | None) -> int:
    words = len((text or "").split())
    return max(1, round(words / 200)) if words else 1


class DigestBuilder:
    def __init__(self, config: AppConfig | None = None, db: Database | None = None) -> None:
        self.config = config or load_app_config()
        self.db = db or Database(self.config.settings.sqlite_path)
        self.db.init()
        self.db.upsert_sources(self.config.sources)
        self.curation = CurationPolicy(self.config.curation)

    async def build(self, period: str) -> str:
        start, end = period_bounds(period)
        clusters = self.db.list_clusters(
            since=start.isoformat(),
            until=end.isoformat(),
            limit=120,
        )
        sorted_rows = sorted(clusters, key=self.curation.sort_key, reverse=True)
        sections, quick_links = self._organize(sorted_rows)
        cluster_payloads = [
            payload for section in SECTION_ORDER for payload in sections[section]
        ] + quick_links
        ai_client = make_ai_client(self.config.settings)
        try:
            digest = await ai_client.summarize_digest(period, cluster_payloads)
        except (AiValidationError, ValueError):
            digest = await LocalStructuredClient().summarize_digest(period, cluster_payloads)
        title = digest.title
        markdown = self._render_markdown(period, digest.model_dump(), sections, quick_links)
        id_ = make_digest_id(period, start, end)
        self.db.save_digest(
            digest_id=id_,
            period=period,
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            title=title,
            summary_md=markdown,
            payload={
                "digest": digest.model_dump(),
                "clusters": cluster_payloads,
                "sections": sections,
                "quick_links": quick_links,
            },
        )
        page_path = "/" if period == "daily" else f"/week/{_iso_week(start)}"
        highlights = [
            f"{SECTION_TITLES[section].split(' ', 1)[-1]}: {sections[section][0]['headline']}"
            for section in SECTION_ORDER
            if sections[section]
        ]
        self.db.enqueue_telegram_message(
            digest_id=id_,
            text=format_digest_message(
                title,
                f"{self.config.settings.base_url.rstrip('/')}{page_path}",
                digest.overview,
                highlights,
            ),
        )
        return id_

    def _cluster_payload(self, row: Any) -> dict[str, Any]:
        summary = json.loads(row["summary_json"] or "{}")
        docs = self.db.cluster_documents(row["id"])
        topics = json.loads(row["topic_slugs_json"] or "[]")
        tickers = json.loads(row["ticker_symbols_json"] or "[]")
        longest_text = max((doc["text"] or "" for doc in docs), key=len, default="")
        return {
            "id": row["id"],
            "title": summary.get("title") or row["title"],
            "headline": summary.get("headline") or summary.get("title") or row["title"],
            "summary": summary.get("summary") or summary.get("why_it_matters", ""),
            "confidence": summary.get("confidence") or row["confidence"],
            "why_it_matters": summary.get("why_it_matters", ""),
            "bullets": summary.get("bullets", []),
            "topics": topics,
            "tickers": tickers,
            "is_social_signal": bool(row["is_social_signal"]),
            "reliability_score": row["reliability_score"],
            "frontier_score": row["frontier_score"],
            "frontier_category": row["frontier_category"],
            "frontier_reasons": json.loads(row["frontier_reasons_json"] or "[]"),
            "buzz_score": self.curation.buzz_of(row),
            "section": section_for(topics, tickers, row["frontier_category"]),
            "read_time_min": read_time_minutes(longest_text),
            "url": docs[0]["url"] if docs else "",
            "sources": [
                {"title": doc["source_name"] or doc["title"], "url": doc["url"]}
                for doc in docs[:3]
            ],
        }

    def _organize(
        self, sorted_rows: list[Any]
    ) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        """Group pre-sorted clusters into TLDR sections, demoting overflow / context-only
        / duplicate items into Quick Links."""
        sections: dict[str, list[dict[str, Any]]] = {key: [] for key in SECTION_ORDER}
        quick_links: list[dict[str, Any]] = []
        seen_titles: set[str] = set()
        for row in sorted_rows:
            payload = self._cluster_payload(row)
            title_key = normalize_title(payload["title"])
            if title_key and title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            section = payload["section"]
            full = sections[section]
            if self.curation.is_context_only(row) or len(full) >= self.curation.section_limit(section):
                quick_links.append(payload)
            else:
                full.append(payload)
        return sections, quick_links[: self.curation.section_limit("quick_links")]

    def _render_markdown(
        self,
        period: str,
        digest: dict[str, Any],
        sections: dict[str, list[dict[str, Any]]],
        quick_links: list[dict[str, Any]],
    ) -> str:
        lines = [f"# {digest['title']}", "", digest["overview"], ""]
        if digest.get("key_points"):
            lines.append("## In Brief")
            for point in digest["key_points"]:
                lines.append(f"- {point}")
            lines.append("")
        for section in SECTION_ORDER:
            items = sections.get(section, [])
            if not items:
                continue
            lines.append(f"## {SECTION_TITLES[section]}")
            lines.append("")
            for item in items:
                lines.extend(self._item_lines(item))
        if quick_links:
            lines.append("## 🔗 Quick Links")
            for item in quick_links:
                url = item.get("url") or (item["sources"][0]["url"] if item["sources"] else "")
                lines.append(f"- [{item['headline']}]({url})")
            lines.append("")
        if digest.get("watch_next"):
            lines.append("## Watch Next")
            for point in digest["watch_next"]:
                lines.append(f"- {point}")
        if period in {"daily", "weekly"}:
            lines.append("")
            lines.append("_Stock-related summaries are informational and not financial advice._")
        return "\n".join(lines).strip()

    def _item_lines(self, item: dict[str, Any]) -> list[str]:
        """One TLDR item: linked headline + read-time tag + 2-3 sentence summary."""
        url = item.get("url") or (item["sources"][0]["url"] if item["sources"] else "")
        headline = item["headline"]
        linked = f"[{headline}]({url})" if url else headline
        meta = f"_{item['read_time_min']} min read_"
        if item["tickers"]:
            meta += f" · {', '.join(item['tickers'])}"
        lines = [f"### {linked}", meta, ""]
        if item.get("summary"):
            lines.append(item["summary"])
        elif item.get("why_it_matters"):
            lines.append(item["why_it_matters"])
        lines.append("")
        return lines


def _iso_week(start: datetime) -> str:
    iso = start.astimezone(UTC).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
