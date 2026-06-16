from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import httpx

from newsbot.ai import AiValidationError, make_ai_client
from newsbot.classify import classify_tickers, classify_topics
from newsbot.collectors import COLLECTOR_TYPES
from newsbot.config import AppConfig, load_app_config
from newsbot.curation import CurationPolicy
from newsbot.db import Database
from newsbot.engagement import cluster_engagement
from newsbot.fetch import DocumentExtractor
from newsbot.frontier import FrontierScorer, source_role
from newsbot.reliability import score_cluster
from newsbot.telegram import TelegramClient, format_cluster_alert
from newsbot.types import Document
from newsbot.utils import canonicalize_url, normalize_title, stable_id


@dataclass(frozen=True)
class IngestReport:
    collected: int = 0
    extracted: int = 0
    clustered: int = 0
    alerts_queued: int = 0


class NewsPipeline:
    def __init__(self, config: AppConfig | None = None, db: Database | None = None) -> None:
        self.config = config or load_app_config()
        self.db = db or Database(self.config.settings.sqlite_path)
        self.db.init()
        self.db.upsert_sources(self.config.sources)
        self.extractor = DocumentExtractor(self.config)
        self.curation = CurationPolicy(self.config.curation)
        self.frontier = FrontierScorer()

    async def ingest(self, source: str = "all") -> IngestReport:
        collected = await self.collect(source)
        extracted, clustered, alerts_queued = await self.extract_and_cluster()
        return IngestReport(
            collected=collected,
            extracted=extracted,
            clustered=clustered,
            alerts_queued=alerts_queued,
        )

    async def collect(self, source: str = "all") -> int:
        selected = self.config.enabled_sources(None if source == "all" else source)
        headers = {"User-Agent": self.config.settings.http_user_agent}
        total = 0
        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            for source_config in selected:
                collector_type = COLLECTOR_TYPES.get(source_config.connector)
                if collector_type is None:
                    self.db.update_source_health(
                        source_config.id,
                        status="error",
                        error=f"No collector for {source_config.connector}",
                    )
                    continue
                result = await collector_type(source_config, self.config).collect(client)
                for item in result.items:
                    if not self.curation.raw_item_decision(item).keep:
                        continue
                    self.db.upsert_raw_item(item)
                total += sum(1 for item in result.items if self.curation.raw_item_decision(item).keep)
                self.db.update_source_health(
                    source_config.id,
                    status=result.status,
                    items_seen=len(result.items),
                    error=result.error,
                )
        return total

    async def extract_and_cluster(self) -> tuple[int, int, int]:
        ai_client = make_ai_client(self.config.settings)
        extracted = 0
        clustered = 0
        alerts_queued = 0
        headers = {"User-Agent": self.config.settings.http_user_agent}
        async with httpx.AsyncClient(timeout=30, headers=headers, follow_redirects=True) as client:
            rows = self.db.raw_items_without_documents(limit=250)
            for row in rows:
                document = await self.extractor.extract_row(client, row)
                if document is None:
                    continue
                if not self.curation.document_decision(document.title, document.text).keep:
                    continue
                self.db.upsert_document(document)
                extracted += 1
                cluster_id, alert_was_queued = await self._cluster_document(
                    document,
                    ai_client,
                    queue_alert=alerts_queued < self.curation.alert_max_per_run,
                )
                if cluster_id:
                    clustered += 1
                    if alert_was_queued:
                        alerts_queued += 1
        return extracted, clustered, alerts_queued

    async def _cluster_document(
        self,
        document: Document,
        ai_client: object,
        *,
        queue_alert: bool = True,
    ) -> tuple[str | None, bool]:
        source = self.config.source_by_id(document.source_id)
        if source is None:
            return None, False
        source_text = f"{document.title}\n{document.snippet}\n{document.text[:2000]}"
        topics = classify_topics(source_text, self.config.topics, source.topics)
        tickers = classify_tickers(source_text, self.config.tickers)
        cluster_key = canonicalize_url(document.url)
        if document.metadata.get("connector") in {"reddit", "x", "hn"} and not tickers:
            cluster_key = normalize_title(document.title)
        cluster_id = stable_id("cluster", cluster_key or normalize_title(document.title))
        existing_docs = self.db.cluster_documents(cluster_id)
        source_tiers = [row["source_trust_tier"] for row in existing_docs]
        source_tiers.append(source.trust_tier.value)
        reliability = score_cluster(source_tiers)
        source_roles = [
            source_role(self.config.source_by_id(row["source_id"]))
            for row in existing_docs
        ]
        source_roles.append(source_role(source))
        cluster_metadata = [_row_metadata(row) for row in existing_docs]
        cluster_metadata.append(document.metadata)
        engagement = cluster_engagement(cluster_metadata)
        frontier = self.frontier.score(
            text=source_text,
            published_at=document.published_at,
            source_roles=source_roles,
            topics=topics,
            tickers=tickers,
            social_only=reliability.social_only,
            source_count=len(existing_docs) + 1,
            engagement=engagement,
        )
        self.db.upsert_cluster(
            cluster_id=cluster_id,
            document_id=document.id,
            title=document.title,
            canonical_url=canonicalize_url(document.url),
            topic_slugs=topics,
            ticker_symbols=tickers,
            reliability_score=reliability.score,
            confidence=reliability.confidence.value,
            is_social_signal=reliability.social_only,
            frontier_score=frontier.score,
            frontier_category=frontier.category,
            frontier_reasons=frontier.reasons,
            buzz_score=engagement,
        )
        documents = self.db.cluster_documents(cluster_id)
        summary_documents = [
            {
                "id": row["id"],
                "title": row["title"],
                "url": row["url"],
                "source": row["source_name"],
                "trust_tier": row["source_trust_tier"],
                "snippet": row["snippet"],
            }
            for row in documents[:5]
        ]
        try:
            summary = await ai_client.summarize_story(summary_documents, reliability.confidence.value)
        except (AiValidationError, httpx.HTTPError, ValueError):
            return cluster_id, False
        summary_payload = summary.model_dump()
        self.db.upsert_cluster(
            cluster_id=cluster_id,
            document_id=document.id,
            title=summary.title,
            canonical_url=canonicalize_url(document.url),
            topic_slugs=topics,
            ticker_symbols=tickers,
            reliability_score=reliability.score,
            confidence=summary.confidence,
            is_social_signal=reliability.social_only,
            frontier_score=frontier.score,
            frontier_category=frontier.category,
            frontier_reasons=frontier.reasons,
            buzz_score=engagement,
            summary=summary_payload,
        )
        self.db.save_claims(
            cluster_id,
            [claim.model_dump() for claim in summary.claims],
        )
        alert_decision = self.curation.alert_allowed(
            reliability_allowed=reliability.alert_allowed,
            reliability_score=reliability.score,
            frontier_score=frontier.score,
            topics=topics,
            tickers=tickers,
            social_only=reliability.social_only,
            published_at=document.published_at,
            engagement=engagement,
        )
        alert_was_queued = False
        if queue_alert and alert_decision.keep:
            cluster = self.db.get_cluster(cluster_id)
            if cluster and not cluster["alert_queued_at"]:
                text = format_cluster_alert(cluster, documents)
                self.db.enqueue_telegram_message(text=text, cluster_id=cluster_id)
                self.db.mark_cluster_alert_queued(cluster_id)
                alert_was_queued = True
        return cluster_id, alert_was_queued

    async def run_alerts(self) -> tuple[int, int]:
        telegram = TelegramClient(
            self.config.settings.telegram_bot_token,
            self.config.settings.telegram_chat_id,
        )
        sent = 0
        failed = 0
        for message in self.db.pending_telegram_messages(limit=25):
            try:
                await telegram.send_message(message["text"])
            except Exception as exc:  # noqa: BLE001
                self.db.mark_telegram_failed(message["id"], str(exc))
                failed += 1
            else:
                self.db.mark_telegram_sent(message["id"])
                sent += 1
        return sent, failed


def _row_metadata(row: object) -> dict:
    try:
        return json.loads(row["metadata_json"] or "{}")
    except (KeyError, TypeError, ValueError):
        return {}


def run_ingest(source: str = "all") -> IngestReport:
    return asyncio.run(NewsPipeline().ingest(source=source))
