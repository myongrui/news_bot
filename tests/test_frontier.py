from datetime import UTC, datetime, timedelta

from newsbot.frontier import FrontierScorer


def test_fresh_official_nvidia_ai_item_scores_high():
    result = FrontierScorer().score(
        text=(
            "NVIDIA announced a new GPU inference platform with training benchmarks "
            "for frontier model deployment in data centers."
        ),
        published_at=datetime.now(UTC).isoformat(),
        source_roles=["primary_truth"],
        topics=["ai", "semiconductors"],
        tickers=["NVDA"],
        social_only=False,
        source_count=1,
    )

    assert result.score >= 75
    assert result.category in {"technical_frontier", "market_impact"}
    assert "primary_truth" in result.reasons


def test_old_official_item_stays_digest_level():
    result = FrontierScorer().score(
        text="NVIDIA announced a GPU inference model release with benchmarks.",
        published_at=(datetime.now(UTC) - timedelta(days=30)).isoformat(),
        source_roles=["primary_truth"],
        topics=["ai"],
        tickers=[],
        social_only=False,
        source_count=1,
    )

    assert result.score < 75
    assert "old" in result.reasons


def test_social_only_item_without_buzz_is_nudged_down():
    result = FrontierScorer().score(
        text="HN is discussing a new AI agent benchmark and GPU inference result.",
        published_at=datetime.now(UTC).isoformat(),
        source_roles=["fast_signal"],
        topics=["ai"],
        tickers=[],
        social_only=True,
        source_count=1,
        engagement=0.0,
    )

    assert result.category == "early_signal"
    assert "social_no_buzz" in result.reasons


def test_high_buzz_social_outranks_quiet_blog():
    scorer = FrontierScorer()
    buzzy_social = scorer.score(
        text="HN is discussing a new AI agent benchmark and GPU inference result.",
        published_at=datetime.now(UTC).isoformat(),
        source_roles=["fast_signal"],
        topics=["ai"],
        tickers=[],
        social_only=True,
        source_count=1,
        engagement=0.9,
    )
    quiet_blog = scorer.score(
        text="A company published a general AI literacy blog post.",
        published_at=datetime.now(UTC).isoformat(),
        source_roles=["primary_truth"],
        topics=["ai"],
        tickers=[],
        social_only=False,
        source_count=1,
        engagement=0.0,
    )

    assert buzzy_social.score > quiet_blog.score
    assert "buzz:high" in buzzy_social.reasons


def test_corroborated_discussion_can_be_frontier_worthy_with_buzz():
    result = FrontierScorer().score(
        text="A trusted report confirms an AI agent model release with evals and inference benchmarks.",
        published_at=datetime.now(UTC).isoformat(),
        source_roles=["fast_signal", "context"],
        topics=["ai"],
        tickers=[],
        social_only=False,
        source_count=2,
        engagement=0.5,
    )

    assert result.score >= 75
    assert "corroborated" in result.reasons


def test_market_filing_outranks_generic_ai_blog():
    scorer = FrontierScorer()
    filing = scorer.score(
        text="Microsoft filed an 8-K with AI datacenter capex guidance and revenue impact.",
        published_at=datetime.now(UTC).isoformat(),
        source_roles=["primary_truth"],
        topics=["markets", "filings"],
        tickers=["MSFT"],
        social_only=False,
        source_count=1,
    )
    generic = scorer.score(
        text="A company published a general AI literacy blog post.",
        published_at=datetime.now(UTC).isoformat(),
        source_roles=["primary_truth"],
        topics=["ai"],
        tickers=[],
        social_only=False,
        source_count=1,
    )

    assert filing.score > generic.score
    assert filing.category == "market_impact"


def test_keyword_matching_does_not_treat_security_as_sec_filing():
    result = FrontierScorer().score(
        text="A security research post discusses model safety evaluation.",
        published_at=datetime.now(UTC).isoformat(),
        source_roles=["primary_truth"],
        topics=["cybersecurity", "research"],
        tickers=[],
        social_only=False,
        source_count=1,
    )

    assert all("market:sec" not in reason for reason in result.reasons)


def test_blue_chip_analyst_note_scores_as_market_impact():
    result = FrontierScorer().score(
        text="An analyst upgrade raised JPMorgan's price target and cited valuation and buyback upside.",
        published_at=datetime.now(UTC).isoformat(),
        source_roles=["context"],
        topics=["markets", "blue_chips", "analyst_ratings"],
        tickers=["JPM"],
        social_only=False,
        source_count=1,
    )

    assert result.category == "market_impact"
    assert result.score >= 65


def test_policy_regulatory_item_gets_policy_category():
    result = FrontierScorer().score(
        text="NIST published AI safety guidance while regulators weigh new export controls.",
        published_at=datetime.now(UTC).isoformat(),
        source_roles=["primary_truth"],
        topics=["policy", "ai"],
        tickers=[],
        social_only=False,
        source_count=1,
    )

    assert result.category == "policy_and_regulation"
    assert result.score >= 65
