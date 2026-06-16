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


def _social_alert_policy():
    return CurationPolicy(
        {
            "curation": {"priority_topics": ["ai"], "priority_tickers": ["NVDA"]},
            "alerts": {
                "min_frontier_score": 60,
                "suppress_social_only": False,
                "min_engagement_for_social_alert": 0.55,
            },
        }
    )


def test_high_buzz_on_topic_social_alert_is_allowed():
    decision = _social_alert_policy().alert_allowed(
        reliability_allowed=False,  # single social source: reliability gate would normally block
        reliability_score=0.42,
        frontier_score=80,
        topics=["ai"],  # matches a priority topic via content
        tickers=[],
        social_only=True,
        engagement=0.8,
    )

    assert decision.keep is True


def test_off_topic_high_buzz_social_alert_is_rejected():
    # A viral but off-watchlist social post (e.g. a general-interest HN essay) must not alert,
    # even with high buzz.
    decision = _social_alert_policy().alert_allowed(
        reliability_allowed=False,
        reliability_score=0.42,
        frontier_score=80,
        topics=["startups"],  # no priority topic/ticker
        tickers=[],
        social_only=True,
        engagement=0.9,
    )

    assert decision.keep is False
    assert decision.reason == "no_priority_topic_or_ticker"


def test_low_buzz_social_alert_is_suppressed():
    decision = _social_alert_policy().alert_allowed(
        reliability_allowed=False,
        reliability_score=0.42,
        frontier_score=80,
        topics=["ai"],
        tickers=[],
        social_only=True,
        engagement=0.2,
    )

    assert decision.keep is False
    assert decision.reason == "social_buzz_below_threshold"


def test_context_only_blog_is_held_back():
    policy = CurationPolicy(
        {
            "curation": {"priority_topics": ["ai"], "priority_tickers": ["NVDA"]},
            "digests": {"min_buzz_for_blog_only": 0.15},
        }
    )

    quiet_blog = {
        "buzz_score": 0.0,
        "is_social_signal": False,
        "topic_slugs_json": '["startups"]',
        "ticker_symbols_json": "[]",
    }
    discussed_blog = {**quiet_blog, "buzz_score": 0.4}
    watchlist_blog = {**quiet_blog, "topic_slugs_json": '["ai"]'}

    assert policy.is_context_only(quiet_blog) is True
    assert policy.is_context_only(discussed_blog) is False
    assert policy.is_context_only(watchlist_blog) is False
