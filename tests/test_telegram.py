from newsbot.telegram import FINANCIAL_FOOTER, format_cluster_alert


def test_format_cluster_alert_hides_confidence_and_uses_full_source_urls():
    cluster = {
        "summary_json": (
            '{"title":"NVIDIA updates AI roadmap","confidence":"high",'
            '"why_it_matters":"It affects AI infrastructure.","bullets":["Roadmap updated."]}'
        ),
        "title": "Fallback title",
        "confidence": "medium",
        "ticker_symbols_json": '["NVDA"]',
        "topic_slugs_json": '["ai"]',
    }
    documents = [
        {
            "source_name": "NVIDIA Blog",
            "title": "Doc",
            "url": "https://example.com/nvda",
        }
    ]

    message = format_cluster_alert(cluster, documents)

    assert "Confidence:" not in message
    assert "NVIDIA Blog" not in message
    assert "1. https://example.com/nvda" in message
    assert message.index("<b>NVIDIA updates AI roadmap</b>") < message.index("1. https://example.com/nvda")
    assert message.index("1. https://example.com/nvda") < message.index("<b>Why it matters:</b>")
    assert FINANCIAL_FOOTER.strip() in message
