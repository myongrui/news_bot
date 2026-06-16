from newsbot.curation import CurationPolicy
from newsbot.digest import DigestBuilder, read_time_minutes, section_for


def _item(**overrides):
    item = {
        "id": "c1",
        "title": "NVIDIA inference benchmark",
        "headline": "NVIDIA ships a new inference benchmark",
        "summary": "NVIDIA published a benchmark for frontier inference. It targets data center GPUs.",
        "confidence": "high",
        "frontier_score": 88,
        "frontier_category": "technical_frontier",
        "frontier_reasons": ["fresh", "buzz:high"],
        "why_it_matters": "It affects AI infrastructure.",
        "bullets": ["A new benchmark was published."],
        "sources": [{"title": "NVIDIA", "url": "https://example.com/nvidia"}],
        "url": "https://example.com/nvidia",
        "topics": ["ai"],
        "tickers": ["NVDA"],
        "read_time_min": 4,
        "is_social_signal": False,
    }
    item.update(overrides)
    return item


def test_tldr_markdown_has_sections_readtime_and_quick_links():
    builder = DigestBuilder.__new__(DigestBuilder)
    builder.curation = CurationPolicy({"digests": {}})

    sections = {
        "ai": [_item()],
        "markets": [],
        "novelty": [],
    }
    quick_links = [
        _item(id="c2", headline="A quieter blog post", url="https://example.com/blog"),
    ]
    markdown = builder._render_markdown(
        "daily",
        {
            "title": "Daily Frontier Brief",
            "overview": "Two stories mattered today.",
            "key_points": [],
            "watch_next": [],
        },
        sections,
        quick_links,
    )

    assert "## 🚀 AI & Launches" in markdown
    assert "[NVIDIA ships a new inference benchmark](https://example.com/nvidia)" in markdown
    assert "4 min read" in markdown
    assert "NVIDIA published a benchmark for frontier inference." in markdown
    assert "## 🔗 Quick Links" in markdown
    assert "[A quieter blog post](https://example.com/blog)" in markdown
    # No reader-facing scoring chrome.
    assert "Frontier:" not in markdown
    assert "Why ranked:" not in markdown


def test_section_for_routes_by_topic_and_ticker():
    assert section_for(["markets"], [], None) == "markets"
    assert section_for(["ai"], [], None) == "ai"
    assert section_for([], ["NVDA"], None) == "markets"
    assert section_for(["research"], [], None) == "novelty"
    assert section_for(["ai"], ["NVDA"], None) == "markets"  # ticker wins → markets


def test_read_time_minutes():
    assert read_time_minutes("") == 1
    assert read_time_minutes("word " * 400) == 2
