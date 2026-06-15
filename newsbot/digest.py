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
from newsbot.utils import period_bounds


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
            limit=80,
        )
        clusters = self._curate_digest_clusters(period, clusters)
        cluster_payloads = [self._cluster_payload(row) for row in clusters]
        ai_client = make_ai_client(self.config.settings)
        try:
            digest = await ai_client.summarize_digest(period, cluster_payloads)
        except (AiValidationError, ValueError):
            digest = await LocalStructuredClient().summarize_digest(period, cluster_payloads)
        title = digest.title
        markdown = self._render_markdown(period, digest.model_dump(), cluster_payloads)
        id_ = make_digest_id(period, start, end)
        self.db.save_digest(
            digest_id=id_,
            period=period,
            period_start=start.isoformat(),
            period_end=end.isoformat(),
            title=title,
            summary_md=markdown,
            payload={"digest": digest.model_dump(), "clusters": cluster_payloads},
        )
        page_path = "/" if period == "daily" else f"/week/{_iso_week(start)}"
        self.db.enqueue_telegram_message(
            digest_id=id_,
            text=format_digest_message(
                title,
                f"{self.config.settings.base_url.rstrip('/')}{page_path}",
                digest.overview,
            ),
        )
        return id_

    def _cluster_payload(self, row: Any) -> dict[str, Any]:
        summary = json.loads(row["summary_json"] or "{}")
        docs = self.db.cluster_documents(row["id"])
        return {
            "id": row["id"],
            "title": summary.get("title") or row["title"],
            "confidence": summary.get("confidence") or row["confidence"],
            "why_it_matters": summary.get("why_it_matters", ""),
            "bullets": summary.get("bullets", []),
            "topics": json.loads(row["topic_slugs_json"] or "[]"),
            "tickers": json.loads(row["ticker_symbols_json"] or "[]"),
            "is_social_signal": bool(row["is_social_signal"]),
            "reliability_score": row["reliability_score"],
            "frontier_score": row["frontier_score"],
            "frontier_category": row["frontier_category"],
            "frontier_reasons": json.loads(row["frontier_reasons_json"] or "[]"),
            "sources": [
                {"title": doc["source_name"] or doc["title"], "url": doc["url"]}
                for doc in docs[:3]
            ],
        }

    def _render_markdown(
        self,
        period: str,
        digest: dict[str, Any],
        clusters: list[dict[str, Any]],
    ) -> str:
        lines = [
            f"# {digest['title']}",
            "",
            digest["overview"],
            "",
        ]
        if digest.get("key_points"):
            lines.append("## Key Points")
            for point in digest["key_points"]:
                lines.append(f"- {point}")
            lines.append("")
        primary = [cluster for cluster in clusters if not cluster["is_social_signal"]]
        social = [cluster for cluster in clusters if cluster["is_social_signal"]]
        if primary:
            if period == "weekly":
                lines.append("## Weekly Themes")
                for topic, topic_clusters in self._theme_groups(primary).items():
                    lines.append(f"### {topic.title()}")
                    for cluster in topic_clusters:
                        lines.extend(self._cluster_lines(cluster, heading_level=4))
                    lines.append("")
            else:
                lines.append("## Top Frontier Stories")
                for cluster in primary:
                    lines.extend(self._cluster_lines(cluster))
            lines.append("")
        if social:
            lines.append("## Social Signals")
            for cluster in social[: self.curation.social_signal_limit()]:
                lines.extend(self._cluster_lines(cluster))
            lines.append("")
        if digest.get("watch_next"):
            lines.append("## Watch Next")
            for point in digest["watch_next"]:
                lines.append(f"- {point}")
        if period in {"daily", "weekly"}:
            lines.append("")
            lines.append("_Stock-related summaries are informational and not financial advice._")
        return "\n".join(lines).strip()

    def _curate_digest_clusters(self, period: str, clusters: list[Any]) -> list[Any]:
        limit = self.curation.daily_digest_limit() if period == "daily" else self.curation.weekly_digest_limit()
        sorted_clusters = sorted(clusters, key=self.curation.sort_key, reverse=True)
        primary = [cluster for cluster in sorted_clusters if not cluster["is_social_signal"]]
        social = [cluster for cluster in sorted_clusters if cluster["is_social_signal"]]
        return primary[:limit] + social[: self.curation.social_signal_limit()]

    def _theme_groups(self, clusters: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for cluster in clusters:
            topic = cluster["topics"][0] if cluster["topics"] else cluster["frontier_category"]
            groups.setdefault(topic, []).append(cluster)
        return groups

    def _cluster_lines(self, cluster: dict[str, Any], *, heading_level: int = 3) -> list[str]:
        labels = []
        if cluster["tickers"]:
            labels.append(", ".join(cluster["tickers"]))
        if cluster["topics"]:
            labels.append(", ".join(cluster["topics"]))
        suffix = f" ({'; '.join(labels)})" if labels else ""
        heading = "#" * heading_level
        reasons = ", ".join(cluster.get("frontier_reasons", [])[:4]) or "frontier match"
        lines = [
            f"{heading} {cluster['title']}{suffix}",
            f"Frontier: {int(cluster.get('frontier_score') or 0)} | Category: {cluster.get('frontier_category') or 'unscored'}",
            f"Why ranked: {reasons}",
            f"Confidence: {cluster['confidence']}",
        ]
        why = cluster.get("why_it_matters")
        if why:
            lines.append(why)
        for bullet in cluster.get("bullets", [])[:3]:
            lines.append(f"- {bullet}")
        sources = cluster.get("sources", [])
        if sources:
            source_links = ", ".join(f"[{source['title']}]({source['url']})" for source in sources)
            lines.append(f"Sources: {source_links}")
        lines.append("")
        return lines


def _iso_week(start: datetime) -> str:
    iso = start.astimezone(UTC).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"
