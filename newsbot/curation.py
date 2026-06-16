from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from newsbot.types import RawItem
from newsbot.utils import clean_text, parse_datetime


@dataclass(frozen=True)
class CurationDecision:
    keep: bool
    reason: str


class CurationPolicy:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config
        self.item_rules = config.get("curation", {})
        self.alert_rules = config.get("alerts", {})
        self.digest_rules = config.get("digests", {})

    @property
    def max_item_age_days(self) -> int:
        return int(self.item_rules.get("max_item_age_days", 14))

    @property
    def min_text_chars(self) -> int:
        return int(self.item_rules.get("min_text_chars", 120))

    @property
    def alert_max_per_run(self) -> int:
        return int(self.alert_rules.get("max_per_run", 5))

    @property
    def alert_min_score(self) -> float:
        return float(self.alert_rules.get("min_reliability_score", 0.82))

    @property
    def alert_min_frontier_score(self) -> float:
        return float(self.alert_rules.get("min_frontier_score", 75))

    @property
    def alert_max_age_hours(self) -> int:
        return int(self.alert_rules.get("max_age_hours", 72))

    @property
    def suppress_social_only_alerts(self) -> bool:
        return bool(self.alert_rules.get("suppress_social_only", True))

    @property
    def min_engagement_for_social_alert(self) -> float:
        return float(self.alert_rules.get("min_engagement_for_social_alert", 0.55))

    @property
    def require_priority_for_alert(self) -> bool:
        return bool(self.alert_rules.get("require_priority_topic_or_ticker", True))

    @property
    def min_buzz_for_blog_only(self) -> float:
        return float(self.digest_rules.get("min_buzz_for_blog_only", 0.15))

    def section_limit(self, section: str) -> int:
        limits = self.digest_rules.get("section_limits", {}) or {}
        return int(limits.get(section, 8))

    def daily_digest_limit(self) -> int:
        return int(self.digest_rules.get("daily_max_clusters", 25))

    def weekly_digest_limit(self) -> int:
        return int(self.digest_rules.get("weekly_max_clusters", 60))

    def social_signal_limit(self) -> int:
        return int(self.digest_rules.get("social_signal_limit", 6))

    def raw_item_decision(self, item: RawItem) -> CurationDecision:
        if self._too_old(item.published_at):
            return CurationDecision(False, "too_old")
        text = clean_text(f"{item.title} {item.content or ''}")
        lower = text.lower()
        for blocked in self.item_rules.get("blocked_keywords", []):
            if blocked.lower() in lower:
                return CurationDecision(False, f"blocked_keyword:{blocked}")
        required = [keyword.lower() for keyword in self.item_rules.get("required_any_keywords", [])]
        if required and not any(keyword in lower for keyword in required):
            return CurationDecision(False, "no_required_keyword")
        return CurationDecision(True, "kept")

    def document_decision(self, title: str, text: str) -> CurationDecision:
        combined = clean_text(f"{title} {text}")
        if len(combined) < self.min_text_chars:
            return CurationDecision(False, "too_short")
        lower = combined.lower()
        for blocked in self.item_rules.get("blocked_keywords", []):
            if blocked.lower() in lower:
                return CurationDecision(False, f"blocked_keyword:{blocked}")
        return CurationDecision(True, "kept")

    def alert_allowed(
        self,
        *,
        reliability_allowed: bool,
        reliability_score: float,
        frontier_score: float = 0,
        topics: list[str],
        tickers: list[str],
        social_only: bool,
        published_at: str | None = None,
        engagement: float = 0.0,
    ) -> CurationDecision:
        # Gates that apply regardless of source type.
        if frontier_score < self.alert_min_frontier_score:
            return CurationDecision(False, "frontier_score_below_threshold")
        if self._older_than_hours(published_at, self.alert_max_age_hours):
            return CurationDecision(False, "too_old_for_alert")

        # Social-only path: gate on real discussion (buzz), not trusted corroboration. A single
        # genuinely viral post can alert and bypasses the watchlist requirement.
        if social_only:
            if self.suppress_social_only_alerts:
                return CurationDecision(False, "social_only")
            if engagement < self.min_engagement_for_social_alert:
                return CurationDecision(False, "social_buzz_below_threshold")
            return CurationDecision(True, "kept")

        # Non-social path: trusted-source reliability gate + watchlist relevance.
        if not reliability_allowed:
            return CurationDecision(False, "reliability_gate")
        if reliability_score < self.alert_min_score:
            return CurationDecision(False, "score_below_threshold")
        if self.require_priority_for_alert:
            priority_topics = set(self.item_rules.get("priority_topics", []))
            priority_tickers = set(self.item_rules.get("priority_tickers", []))
            if not (priority_topics.intersection(topics) or priority_tickers.intersection(tickers)):
                return CurationDecision(False, "no_priority_topic_or_ticker")
        return CurationDecision(True, "kept")

    def sort_key(self, cluster: Any) -> tuple[float, float, float, int]:
        topics = set(json.loads(cluster["topic_slugs_json"] or "[]"))
        tickers = set(json.loads(cluster["ticker_symbols_json"] or "[]"))
        priority_topics = set(self.item_rules.get("priority_topics", []))
        priority_tickers = set(self.item_rules.get("priority_tickers", []))
        priority_hits = len(topics.intersection(priority_topics)) + len(tickers.intersection(priority_tickers))
        frontier_score = float(cluster["frontier_score"] or 0)
        buzz = self.buzz_of(cluster)
        # Discussed stories rise: frontier first, then raw buzz, then reliability and watchlist.
        return (frontier_score, buzz, float(cluster["reliability_score"]), priority_hits)

    @staticmethod
    def buzz_of(cluster: Any) -> float:
        try:
            return float(cluster["buzz_score"] or 0)
        except (IndexError, KeyError, TypeError):
            return 0.0

    def is_context_only(self, cluster: Any) -> bool:
        """A blog/context story that nobody is discussing and that isn't on the watchlist.

        Such clusters are held back from the main feed (demoted to Quick Links), so blogs only
        surface as "the article behind the buzz".
        """
        if self.buzz_of(cluster) >= self.min_buzz_for_blog_only:
            return False
        if cluster["is_social_signal"]:
            return False
        topics = set(json.loads(cluster["topic_slugs_json"] or "[]"))
        tickers = set(json.loads(cluster["ticker_symbols_json"] or "[]"))
        priority_topics = set(self.item_rules.get("priority_topics", []))
        priority_tickers = set(self.item_rules.get("priority_tickers", []))
        if priority_topics.intersection(topics) or priority_tickers.intersection(tickers):
            return False
        return True

    def _too_old(self, published_at: str | None) -> bool:
        parsed = parse_datetime(published_at)
        if not parsed:
            return False
        dt = datetime.fromisoformat(parsed.replace("Z", "+00:00")).astimezone(UTC)
        return dt < datetime.now(UTC) - timedelta(days=self.max_item_age_days)

    def _older_than_hours(self, published_at: str | None, hours: int) -> bool:
        parsed = parse_datetime(published_at)
        if not parsed:
            return False
        dt = datetime.fromisoformat(parsed.replace("Z", "+00:00")).astimezone(UTC)
        return dt < datetime.now(UTC) - timedelta(hours=hours)
