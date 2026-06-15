import asyncio

from newsbot.config import AppConfig, Settings
from newsbot.db import Database
from newsbot.pipeline import NewsPipeline
from newsbot.types import Connector, RawItem, SourceConfig, SourceTier, TickerConfig, TopicConfig


def test_pipeline_extracts_clusters_and_queues_trusted_alert(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'newsbot.db'}",
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "uploads",
        offline_summaries=True,
    )
    config = AppConfig(
        settings=settings,
        sources=[
            SourceConfig(
                id="trusted",
                name="Trusted Tech",
                connector=Connector.RSS,
                url="https://example.com/feed",
                trust_tier=SourceTier.TRUSTED_MEDIA,
                topics=("ai",),
                options={"source_role": "primary_truth"},
            )
        ],
        topics=[
            TopicConfig(slug="ai", name="AI", keywords=("ai", "artificial intelligence")),
            TopicConfig(slug="markets", name="Markets", keywords=("earnings", "stock")),
        ],
        tickers=[TickerConfig(symbol="NVDA", name="NVIDIA", aliases=("Nvidia",))],
        curation={
                "curation": {
                    "required_any_keywords": ["ai", "nvidia"],
                    "priority_topics": ["ai"],
                    "priority_tickers": ["NVDA"],
                    "min_text_chars": 40,
                },
                "alerts": {
                    "max_per_run": 5,
                    "min_reliability_score": 0.82,
                    "min_frontier_score": 75,
                    "require_priority_topic_or_ticker": True,
                    "suppress_social_only": True,
                },
            "digests": {},
        },
    )
    db = Database(tmp_path / "newsbot.db")
    pipeline = NewsPipeline(config=config, db=db)
    db.upsert_raw_item(
        RawItem(
            source_id="trusted",
            external_id="1",
            title="Nvidia expands AI inference and GPU benchmark roadmap",
            url="https://example.com/nvidia-ai",
            content=(
                "Nvidia expanded its AI inference infrastructure roadmap for data centers, "
                "with new GPU training benchmarks and enterprise deployment guidance."
            ),
        )
    )

    extracted, clustered, alerts = asyncio.run(pipeline.extract_and_cluster())

    assert extracted == 1
    assert clustered == 1
    assert alerts == 1
    assert db.counts()["telegram_messages"] == 1


def test_pipeline_alert_queue_respects_max_per_run(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'newsbot.db'}",
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "uploads",
        offline_summaries=True,
    )
    config = AppConfig(
        settings=settings,
        sources=[
            SourceConfig(
                id="official",
                name="Official AI",
                connector=Connector.RSS,
                url="https://example.com/feed",
                trust_tier=SourceTier.PRIMARY_OFFICIAL,
                topics=("ai",),
                options={"source_role": "primary_truth"},
            )
        ],
        topics=[TopicConfig(slug="ai", name="AI", keywords=("ai", "inference", "training"))],
        tickers=[TickerConfig(symbol="NVDA", name="NVIDIA", aliases=("Nvidia",))],
        curation={
            "curation": {
                "required_any_keywords": ["ai", "nvidia"],
                "priority_topics": ["ai"],
                "priority_tickers": ["NVDA"],
                "min_text_chars": 40,
            },
            "alerts": {
                "max_per_run": 3,
                "min_reliability_score": 0.85,
                "min_frontier_score": 75,
                "require_priority_topic_or_ticker": True,
                "suppress_social_only": True,
            },
            "digests": {},
        },
    )
    db = Database(tmp_path / "newsbot.db")
    pipeline = NewsPipeline(config=config, db=db)
    for index in range(5):
        db.upsert_raw_item(
            RawItem(
                source_id="official",
                external_id=str(index),
                title=f"Nvidia AI inference benchmark update {index}",
                url=f"https://example.com/nvidia-ai-{index}",
                content=(
                    "Nvidia released an AI inference GPU training benchmark for data center "
                    "deployment with new guidance for frontier model infrastructure."
                ),
            )
        )

    extracted, clustered, alerts = asyncio.run(pipeline.extract_and_cluster())

    assert extracted == 5
    assert clustered == 5
    assert alerts == 3
    assert db.counts()["telegram_messages"] == 3
