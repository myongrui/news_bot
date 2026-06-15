import asyncio

import httpx

from newsbot.collectors.rss import RssCollector
from newsbot.config import AppConfig, Settings
from newsbot.db import Database
from newsbot.types import Connector, SourceConfig, SourceTier


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
