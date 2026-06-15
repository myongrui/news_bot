import pytest
from pydantic import ValidationError

from newsbot.ai import StorySummary


def test_story_summary_schema_accepts_valid_payload():
    summary = StorySummary.model_validate(
        {
            "title": "NVIDIA announces a new AI system",
            "confidence": "high",
            "why_it_matters": "It affects the AI infrastructure basket.",
            "bullets": ["NVIDIA announced a new system."],
            "claims": [
                {
                    "text": "NVIDIA announced a new system.",
                    "confidence": "high",
                    "source_document_ids": ["doc1"],
                }
            ],
            "citations": ["https://example.com"],
        }
    )

    assert summary.confidence == "high"


def test_story_summary_schema_rejects_unknown_confidence():
    with pytest.raises(ValidationError):
        StorySummary.model_validate(
            {
                "title": "Bad",
                "confidence": "certain",
                "why_it_matters": "Nope",
                "bullets": ["Nope"],
            }
        )

