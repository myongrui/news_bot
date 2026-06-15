from newsbot.curation import CurationPolicy
from newsbot.digest import DigestBuilder


def test_daily_digest_markdown_includes_frontier_reasons_and_social_signals():
    builder = DigestBuilder.__new__(DigestBuilder)
    builder.curation = CurationPolicy({"digests": {"social_signal_limit": 5}})

    markdown = builder._render_markdown(
        "daily",
        {
            "title": "Daily Frontier Brief",
            "overview": "Two stories mattered today.",
            "key_points": [],
            "watch_next": [],
        },
        [
            {
                "title": "NVIDIA inference benchmark",
                "confidence": "high",
                "frontier_score": 88,
                "frontier_category": "technical_frontier",
                "frontier_reasons": ["fresh", "primary_truth", "technical:gpu"],
                "why_it_matters": "It affects AI infrastructure.",
                "bullets": ["A new benchmark was published."],
                "sources": [{"title": "NVIDIA", "url": "https://example.com/nvidia"}],
                "topics": ["ai"],
                "tickers": ["NVDA"],
                "is_social_signal": False,
            },
            {
                "title": "HN discussion on agents",
                "confidence": "low",
                "frontier_score": 55,
                "frontier_category": "early_signal",
                "frontier_reasons": ["fast_signal", "social_only_penalty"],
                "why_it_matters": "Builders are discussing it.",
                "bullets": ["A thread is gaining traction."],
                "sources": [{"title": "HN", "url": "https://example.com/hn"}],
                "topics": ["ai"],
                "tickers": [],
                "is_social_signal": True,
            },
        ],
    )

    assert "Frontier: 88" in markdown
    assert "Why ranked: fresh, primary_truth, technical:gpu" in markdown
    assert "## Social Signals" in markdown

