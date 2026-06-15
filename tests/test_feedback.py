from newsbot.db import Database
from newsbot.types import Connector, Document, RawItem, SourceConfig, SourceTier


def test_not_interesting_feedback_hides_cluster_from_default_lists(tmp_path):
    db = Database(tmp_path / "newsbot.db")
    db.init()
    db.upsert_sources(
        [
            SourceConfig(
                id="source",
                name="Source",
                connector=Connector.RSS,
                url="https://example.com/feed",
                trust_tier=SourceTier.TRUSTED_MEDIA,
            )
        ]
    )
    raw_id = db.upsert_raw_item(
        RawItem(
            source_id="source",
            external_id="story",
            title="Borderline but plausible market signal",
            url="https://example.com/story",
            content="Analyst raises Microsoft price target after cloud margin update.",
        )
    )
    db.upsert_document(
        Document(
            id="doc-1",
            raw_item_id=raw_id,
            source_id="source",
            title="Borderline but plausible market signal",
            url="https://example.com/story",
            text="Analyst raises Microsoft price target after cloud margin update.",
            snippet="Analyst raises Microsoft price target after cloud margin update.",
        )
    )
    db.upsert_cluster(
        cluster_id="cluster-1",
        document_id="doc-1",
        title="Borderline but plausible market signal",
        canonical_url="https://example.com/story",
        topic_slugs=["markets"],
        ticker_symbols=["MSFT"],
        reliability_score=0.86,
        confidence="high",
        is_social_signal=False,
        frontier_score=69,
        frontier_category="market_impact",
        frontier_reasons=["context", "market:MSFT"],
    )

    assert len(db.list_clusters()) == 1

    db.set_cluster_feedback("cluster-1", "not_interesting")

    assert db.get_cluster_feedback("cluster-1") == "not_interesting"
    assert db.list_clusters() == []
    assert len(db.list_clusters(include_not_interesting=True)) == 1

    db.clear_cluster_feedback("cluster-1")

    assert db.get_cluster_feedback("cluster-1") is None
    assert len(db.list_clusters()) == 1
