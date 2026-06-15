from datetime import UTC, datetime, timedelta

from newsbot.curation import CurationPolicy
from newsbot.types import RawItem


def test_raw_item_curation_blocks_old_items():
    policy = CurationPolicy({"curation": {"max_item_age_days": 7, "required_any_keywords": []}})
    old = datetime.now(UTC) - timedelta(days=10)

    decision = policy.raw_item_decision(
        RawItem(
            source_id="rss",
            external_id="old",
            title="NVIDIA AI update",
            url="https://example.com",
            published_at=old.isoformat(),
        )
    )

    assert decision.keep is False
    assert decision.reason == "too_old"


def test_alert_curation_requires_priority_topic_or_ticker():
    policy = CurationPolicy(
        {
            "curation": {"priority_topics": ["ai"], "priority_tickers": ["NVDA"]},
            "alerts": {
                "min_reliability_score": 0.82,
                "require_priority_topic_or_ticker": True,
            },
        }
    )

    rejected = policy.alert_allowed(
        reliability_allowed=True,
        reliability_score=0.9,
        frontier_score=90,
        topics=["startups"],
        tickers=[],
        social_only=False,
    )
    accepted = policy.alert_allowed(
        reliability_allowed=True,
        reliability_score=0.9,
        frontier_score=90,
        topics=["ai"],
        tickers=[],
        social_only=False,
    )

    assert rejected.keep is False
    assert accepted.keep is True


def test_alert_curation_rejects_low_frontier_score():
    policy = CurationPolicy(
        {
            "curation": {"priority_topics": ["ai"]},
            "alerts": {"min_reliability_score": 0.85, "min_frontier_score": 75},
        }
    )

    decision = policy.alert_allowed(
        reliability_allowed=True,
        reliability_score=0.9,
        frontier_score=40,
        topics=["ai"],
        tickers=[],
        social_only=False,
    )

    assert decision.keep is False
    assert decision.reason == "frontier_score_below_threshold"
