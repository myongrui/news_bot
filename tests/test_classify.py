from newsbot.classify import classify_tickers, classify_topics
from newsbot.types import TickerConfig, TopicConfig


def test_classify_topics_by_keyword_and_source_topic():
    topics = [
        TopicConfig(slug="ai", name="AI", keywords=("artificial intelligence", "llm")),
        TopicConfig(slug="markets", name="Markets", keywords=("earnings", "stock")),
    ]

    assert classify_topics("New LLM earnings impact", topics, ("research",)) == [
        "ai",
        "markets",
        "research",
    ]


def test_classify_tickers_by_symbol_and_alias():
    tickers = [
        TickerConfig(symbol="NVDA", name="NVIDIA", aliases=("CUDA",)),
        TickerConfig(symbol="MSFT", name="Microsoft", aliases=("Azure",)),
    ]

    assert classify_tickers("Nvidia and Azure expand AI infrastructure", tickers) == [
        "MSFT",
        "NVDA",
    ]


def test_ticker_symbols_do_not_match_common_words():
    tickers = [
        TickerConfig(symbol="COST", name="Costco Wholesale", aliases=("Costco",)),
        TickerConfig(symbol="NOW", name="ServiceNow", aliases=("ServiceNow",)),
        TickerConfig(symbol="V", name="Visa", aliases=("Visa",)),
    ]

    assert classify_tickers("The platform now lowers cost for developers using version V.", tickers) == []
    assert classify_tickers("ServiceNow and $V were mentioned by analysts.", tickers) == ["NOW", "V"]


def test_classify_blue_chip_analyst_language():
    topics = [
        TopicConfig(
            slug="analyst_ratings",
            name="Analyst Ratings",
            keywords=("price target", "upgrade", "downgrade"),
        ),
        TopicConfig(slug="blue_chips", name="Blue Chips", keywords=("blue chip", "mega cap")),
    ]
    tickers = [
        TickerConfig(symbol="JPM", name="JPMorgan Chase", aliases=("JPMorgan",)),
        TickerConfig(symbol="LLY", name="Eli Lilly", aliases=("Lilly",)),
    ]
    text = "Analyst raises JPMorgan price target while calling Lilly a blue chip compounder."

    assert classify_topics(text, topics) == ["analyst_ratings", "blue_chips"]
    assert classify_tickers(text, tickers) == ["JPM", "LLY"]


def test_mouse_cursor_does_not_match_cursor_ide():
    topics = [
        TopicConfig(slug="developer_tools", name="Developer Tools", keywords=("cursor ide", "copilot")),
    ]
    # A general-interest essay that happens to mention a mouse cursor must not be tagged.
    essay = "The first time I emailed a stranger my cursor hovered over Send for five minutes."

    assert classify_topics(essay, topics) == []
    assert classify_topics("I switched my editor to Cursor IDE for agentic coding.", topics) == [
        "developer_tools"
    ]


def test_no_seed_topics_means_content_only():
    # Aggregator sources pass no seed topics, so an off-topic item gets no tags.
    topics = [TopicConfig(slug="ai", name="AI", keywords=("llm", "model"))]
    assert classify_topics("A personal essay about writing to strangers.", topics, ()) == []
    assert classify_topics("A new LLM was released.", topics, ()) == ["ai"]


def test_classify_policy_regulation_language():
    topics = [
        TopicConfig(
            slug="policy",
            name="Policy and Regulation",
            keywords=("ai safety", "export controls", "nist", "rulemaking"),
        ),
        TopicConfig(slug="ai", name="AI", keywords=("ai", "model")),
    ]

    text = "NIST releases AI safety guidance as export controls and rulemaking evolve."

    assert classify_topics(text, topics) == ["ai", "policy"]
