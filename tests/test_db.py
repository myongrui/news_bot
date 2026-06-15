from newsbot.db import Database


def test_save_claims_dedupes_repeated_claim_text(tmp_path):
    db = Database(tmp_path / "newsbot.db")
    db.init()

    db.save_claims(
        "cluster-1",
        [
            {
                "text": "NVIDIA announced a new inference platform.",
                "confidence": "high",
                "source_document_ids": ["doc-1"],
            },
            {
                "text": "NVIDIA announced a new inference platform.",
                "confidence": "high",
                "source_document_ids": ["doc-1"],
            },
        ],
    )

    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]

    assert count == 1
