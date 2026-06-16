from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from newsbot.types import SourceConfig
from newsbot.utils import clean_text, parse_datetime


# Rebalanced for a discussion-first feed: official/blog sources no longer dominate on role
# alone (they rank via the buzz band when actually discussed), and the discussion/fast-signal
# role carries real weight instead of being a near-zero lead.
SOURCE_ROLE_POINTS = {
    "primary_truth": 18,
    "deep_analysis": 16,
    "fast_signal": 14,
    "context": 12,
    "unknown": 4,
}

# Max points contributed by social engagement ("buzz") — a first-class signal.
BUZZ_MAX = 25

TECHNICAL_KEYWORDS = {
    "agent",
    "agents",
    "benchmark",
    "benchmarks",
    "changelog",
    "claude code",
    "codex",
    "coding agent",
    "copilot",
    "cursor",
    "eval",
    "evals",
    "evaluation",
    "frontier model",
    "github actions",
    "gpu",
    "gpus",
    "hbm",
    "inference",
    "langchain",
    "langgraph",
    "langsmith",
    "mcp",
    "model release",
    "open weights",
    "reasoning",
    "research",
    "training",
}

MARKET_KEYWORDS = {
    "8-k",
    "10-k",
    "10-q",
    "capex",
    "capital expenditure",
    "datacenter",
    "data center",
    "earnings",
    "ai safety",
    "antitrust",
    "bis",
    "doj",
    "enforcement",
    "export controls",
    "filing",
    "ftc",
    "free cash flow",
    "guidance",
    "initiated coverage",
    "market perform",
    "nist",
    "overweight",
    "partnership",
    "policy",
    "price target",
    "rating",
    "regulator",
    "revenue",
    "regulation",
    "rulemaking",
    "sec",
    "target price",
    "underweight",
    "upgrade",
    "valuation",
}


@dataclass(frozen=True)
class FrontierResult:
    score: int
    category: str
    reasons: list[str] = field(default_factory=list)


class FrontierScorer:
    def score(
        self,
        *,
        text: str,
        published_at: str | None,
        source_roles: list[str],
        topics: list[str],
        tickers: list[str],
        social_only: bool,
        source_count: int,
        engagement: float = 0.0,
    ) -> FrontierResult:
        normalized = clean_text(text).lower()
        score = 0
        reasons: list[str] = []

        recency_points = self._recency_points(published_at)
        score += recency_points
        if recency_points >= 15:
            reasons.append("fresh")
        elif recency_points == 0:
            reasons.append("old")

        source_points = max((SOURCE_ROLE_POINTS.get(role, 4) for role in source_roles), default=4)
        score += source_points
        strongest_role = max(source_roles, key=lambda role: SOURCE_ROLE_POINTS.get(role, 4), default="unknown")
        reasons.append(strongest_role)

        technical_hits = _keyword_hits(normalized, TECHNICAL_KEYWORDS)
        technical_points = min(20, len(technical_hits) * 5)
        score += technical_points
        if technical_hits:
            reasons.append(f"technical:{', '.join(technical_hits[:3])}")

        market_hits = _keyword_hits(normalized, MARKET_KEYWORDS)
        market_points = min(20, len(market_hits) * 5)
        if tickers:
            market_points = min(20, market_points + 8)
        score += market_points
        if market_hits or tickers:
            reason = ", ".join((market_hits + tickers)[:4])
            reasons.append(f"market:{reason}")

        priority_points = 0
        if topics:
            priority_points += min(10, len(topics) * 5)
        if tickers:
            priority_points += min(10, len(tickers) * 8)
        score += priority_points
        if priority_points:
            reasons.append("watchlist_match")

        independent_roles = set(source_roles)
        corroboration_points = 0
        if source_count >= 2:
            corroboration_points += 5
        if len(independent_roles) >= 2:
            corroboration_points += 5
        score += corroboration_points
        if corroboration_points:
            reasons.append("corroborated")

        buzz_points = round(min(BUZZ_MAX, max(0.0, engagement) * BUZZ_MAX))
        score += buzz_points
        if engagement >= 0.66:
            reasons.append("buzz:high")
        elif engagement >= 0.33:
            reasons.append("buzz:medium")

        # Social signal is now wanted, not penalized. Only nudge down social-only items that
        # have no measurable discussion behind them.
        if social_only and engagement <= 0:
            score = max(0, score - 8)
            reasons.append("social_no_buzz")

        category = self._category(
            technical_points=technical_points,
            market_points=market_points,
            topics=topics,
            tickers=tickers,
            social_only=social_only,
        )
        return FrontierResult(score=min(100, score), category=category, reasons=reasons)

    def _recency_points(self, published_at: str | None) -> int:
        parsed = parse_datetime(published_at)
        if not parsed:
            return 20
        published = datetime.fromisoformat(parsed.replace("Z", "+00:00")).astimezone(UTC)
        age = datetime.now(UTC) - published
        if age <= timedelta(hours=24):
            return 20
        if age <= timedelta(hours=72):
            return 16
        if age <= timedelta(days=7):
            return 10
        if age <= timedelta(days=14):
            return 5
        return 0

    def _category(
        self,
        *,
        technical_points: int,
        market_points: int,
        topics: list[str],
        tickers: list[str],
        social_only: bool,
    ) -> str:
        if social_only:
            return "early_signal"
        if "policy" in topics:
            return "policy_and_regulation"
        if market_points >= technical_points and (tickers or "markets" in topics or "filings" in topics):
            return "market_impact"
        if technical_points >= 10 or "research" in topics:
            return "technical_frontier"
        if "cybersecurity" in topics:
            return "risk_and_security"
        return "strategic_context"


def source_role(source: SourceConfig | None) -> str:
    if source is None:
        return "unknown"
    configured = source.options.get("source_role")
    if configured:
        return str(configured)
    if source.connector.value in {"hn", "reddit", "x"}:
        return "fast_signal"
    if source.connector.value in {"arxiv", "uploads"}:
        return "deep_analysis"
    if source.connector.value == "sec":
        return "primary_truth"
    if source.trust_tier.value == "primary_official":
        return "primary_truth"
    if source.trust_tier.value == "trusted_media":
        return "context"
    return "unknown"


def _keyword_hits(text: str, keywords: set[str]) -> list[str]:
    hits = []
    for keyword in keywords:
        pattern = r"(?<![a-z0-9])" + re.escape(keyword) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            hits.append(keyword)
    return sorted(hits)
