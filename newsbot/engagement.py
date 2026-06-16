"""Normalized social-engagement ("buzz") scoring.

Collectors already stash raw engagement counts in each ``RawItem.payload`` (which survives
into ``Document.metadata``). This module turns those heterogeneous counts — HN points, Reddit
upvotes, X likes/retweets, etc. — into a single comparable 0.0–1.0 buzz value so the frontier
scorer can rank "what's being talked about".
"""

from __future__ import annotations

import math
from typing import Any, Iterable

# Raw weight at which a source is considered "very buzzy" (maps to ~1.0 after log scaling).
# Calibrated per connector because their count scales differ by orders of magnitude.
_REFERENCE: dict[str, float] = {
    "hn": 500.0,            # points + comments
    "reddit": 1000.0,       # score + num_comments
    "x": 5000.0,            # likes + 2*retweets + replies + quotes
    "lobsters": 80.0,       # upvote score
    "devto": 300.0,         # reactions + comments
    "stocktwits": 20000.0,  # watchlist_count + message volume
    "github_trending": 2000.0,  # stars
    "producthunt": 800.0,   # votes_count
}


def _num(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _raw_weight(connector: str, metadata: dict[str, Any]) -> float:
    if connector == "hn":
        return _num(metadata.get("score")) + _num(metadata.get("comments"))
    if connector == "reddit":
        return _num(metadata.get("score")) + _num(metadata.get("num_comments"))
    if connector == "x":
        metrics = metadata.get("metrics") or {}
        return (
            _num(metrics.get("like_count"))
            + 2 * _num(metrics.get("retweet_count"))
            + _num(metrics.get("reply_count"))
            + _num(metrics.get("quote_count"))
        )
    if connector == "lobsters":
        return _num(metadata.get("score"))
    if connector == "devto":
        return _num(metadata.get("positive_reactions_count")) + _num(metadata.get("comments_count"))
    if connector == "stocktwits":
        return _num(metadata.get("watchlist_count")) + _num(metadata.get("message_count"))
    if connector == "github_trending":
        return _num(metadata.get("stars"))
    if connector == "producthunt":
        return _num(metadata.get("votes_count"))
    return 0.0


def engagement_score(metadata: dict[str, Any] | None) -> float:
    """Return a 0.0–1.0 buzz score for a single document's metadata.

    Non-social connectors (blogs, newsletters, sec, arxiv, macro feeds) have no reference and
    return 0.0 — they are context, ranked by source role, not buzz.
    """
    if not metadata:
        return 0.0
    connector = str(metadata.get("connector") or "")
    reference = _REFERENCE.get(connector)
    if not reference:
        return 0.0
    weight = _raw_weight(connector, metadata)
    if weight <= 0:
        return 0.0
    return min(1.0, math.log1p(weight) / math.log1p(reference))


def cluster_engagement(metadata_list: Iterable[dict[str, Any] | None]) -> float:
    """Max buzz across the documents in a cluster."""
    return max((engagement_score(metadata) for metadata in metadata_list), default=0.0)
