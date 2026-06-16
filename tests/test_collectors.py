import asyncio
import json

import httpx

from newsbot.collectors.hn import HackerNewsCollector
from newsbot.collectors.rss import RssCollector
from newsbot.collectors.x import XCollector
from newsbot.config import AppConfig, Settings
from newsbot.db import Database
from newsbot.types import Connector, SourceConfig, SourceTier


def _config(source: SourceConfig, tmp_path) -> AppConfig:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'newsbot.db'}",
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "uploads",
    )
    return AppConfig(settings=settings, sources=[source], topics=[], tickers=[], curation={})


def test_rss_collector_parses_feed_entries(tmp_path):
    feed = b"""<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
      <channel>
        <title>Example</title>
        <item>
          <guid>story-1</guid>
          <title>AI chip update</title>
          <link>https://example.com/story?utm_source=x</link>
          <description>NVIDIA announced an AI chip update.</description>
          <pubDate>Sun, 24 May 2026 01:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=feed))
        source = SourceConfig(
            id="rss",
            name="RSS",
            connector=Connector.RSS,
            url="https://example.com/feed.xml",
            trust_tier=SourceTier.TRUSTED_MEDIA,
        )
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'newsbot.db'}",
            data_dir=tmp_path / "data",
            upload_dir=tmp_path / "uploads",
        )
        config = AppConfig(settings=settings, sources=[source], topics=[], tickers=[], curation={})
        async with httpx.AsyncClient(transport=transport) as client:
            return await RssCollector(source, config).collect(client)

    result = asyncio.run(run())

    assert result.status == "ok"
    assert result.items[0].title == "AI chip update"
    assert result.items[0].content == "NVIDIA announced an AI chip update."


def test_rss_collector_strips_html_from_feed_content(tmp_path):
    feed = b"""<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
      <channel>
        <title>Example</title>
        <item>
          <guid>story-2</guid>
          <title>AWS update</title>
          <link>https://example.com/aws</link>
          <description><![CDATA[<p><a href="https://aws.amazon.com/">Amazon SageMaker</a>
          now supports governance capabilities.</p>]]></description>
        </item>
      </channel>
    </rss>
    """

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, content=feed))
        source = SourceConfig(
            id="rss",
            name="RSS",
            connector=Connector.RSS,
            url="https://example.com/feed.xml",
            trust_tier=SourceTier.TRUSTED_MEDIA,
        )
        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'newsbot.db'}",
            data_dir=tmp_path / "data",
            upload_dir=tmp_path / "uploads",
        )
        config = AppConfig(settings=settings, sources=[source], topics=[], tickers=[], curation={})
        async with httpx.AsyncClient(transport=transport) as client:
            return await RssCollector(source, config).collect(client)

    result = asyncio.run(run())

    assert result.items[0].content == "Amazon SageMaker now supports governance capabilities."
    assert "<p>" not in result.items[0].content
    assert "href" not in result.items[0].content


def test_hn_collector_uses_algolia_and_captures_comments(tmp_path):
    payload = {
        "hits": [
            {
                "objectID": "111",
                "title": "Show HN: a new agent framework",
                "url": "https://example.com/agent",
                "points": 320,
                "num_comments": 145,
                "author": "pg",
                "created_at": "2026-06-15T10:00:00Z",
            }
        ]
    }

    async def run():
        def handler(request):
            assert "hn.algolia.com" in str(request.url)
            assert "front_page" in str(request.url)
            return httpx.Response(200, json=payload)

        transport = httpx.MockTransport(handler)
        source = SourceConfig(
            id="hn",
            name="Hacker News",
            connector=Connector.HN,
            url="https://hn.algolia.com/api/v1",
            trust_tier=SourceTier.COMMUNITY_SOCIAL,
            options={"tags": "front_page", "min_points": 100},
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await HackerNewsCollector(source, _config(source, tmp_path)).collect(client)

    result = asyncio.run(run())

    assert result.status == "ok"
    item = result.items[0]
    assert item.title == "Show HN: a new agent framework"
    assert item.payload["score"] == 320
    assert item.payload["comments"] == 145


def test_x_collector_parses_syndication_payload(tmp_path):
    next_data = {
        "props": {
            "pageProps": {
                "timeline": {
                    "entries": [
                        {
                            "content": {
                                "tweet": {
                                    "id_str": "999",
                                    "full_text": "Frontier model released today.",
                                    "created_at": "2026-06-15T12:00:00.000Z",
                                    "favorite_count": 1200,
                                    "retweet_count": 300,
                                    "reply_count": 80,
                                    "quote_count": 20,
                                    "user": {"screen_name": "karpathy", "verified": True},
                                }
                            }
                        }
                    ]
                }
            }
        }
    }
    html = (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(next_data)
        + "</script></body></html>"
    )

    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text=html))
        source = SourceConfig(
            id="x",
            name="X",
            connector=Connector.X,
            url="https://syndication.twitter.com",
            trust_tier=SourceTier.COMMUNITY_SOCIAL,
            options={"accounts": ["karpathy"]},
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await XCollector(source, _config(source, tmp_path)).collect(client)

    result = asyncio.run(run())

    item = result.items[0]
    assert item.author == "karpathy"
    assert item.url == "https://x.com/karpathy/status/999"
    assert item.payload["metrics"]["like_count"] == 1200
    assert item.payload["metrics"]["retweet_count"] == 300


def test_x_collector_disabled_without_accounts(tmp_path):
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(200, text=""))
        source = SourceConfig(
            id="x",
            name="X",
            connector=Connector.X,
            url="https://syndication.twitter.com",
            trust_tier=SourceTier.COMMUNITY_SOCIAL,
            options={},
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await XCollector(source, _config(source, tmp_path)).collect(client)

    result = asyncio.run(run())
    assert result.status == "disabled"


def test_database_dedupes_raw_items(tmp_path):
    db = Database(tmp_path / "newsbot.db")
    source = SourceConfig(
        id="rss",
        name="RSS",
        connector=Connector.RSS,
        url="https://example.com/feed.xml",
        trust_tier=SourceTier.TRUSTED_MEDIA,
    )
    db.init()
    db.upsert_sources([source])

    from newsbot.types import RawItem

    first = db.upsert_raw_item(
        RawItem(
            source_id="rss",
            external_id="story-1",
            title="AI chip update",
            url="https://example.com/story?utm_source=x",
        )
    )
    second = db.upsert_raw_item(
        RawItem(
            source_id="rss",
            external_id="story-1",
            title="AI chip update revised",
            url="https://example.com/story?utm_campaign=y",
        )
    )

    assert first == second
    assert db.counts()["raw_items"] == 1
