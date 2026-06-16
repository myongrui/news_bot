import asyncio

import pytest
from pydantic import ValidationError

from newsbot.ai import LocalStructuredClient, StorySummary


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


def test_story_summary_accepts_tldr_fields():
    summary = StorySummary.model_validate(
        {
            "title": "NVIDIA announces a new AI system",
            "headline": "NVIDIA ships a new inference system",
            "summary": "NVIDIA released a system. It targets data center inference.",
            "confidence": "high",
            "why_it_matters": "It affects the AI infrastructure basket.",
            "bullets": ["NVIDIA announced a new system."],
        }
    )

    assert summary.headline.startswith("NVIDIA ships")
    assert "data center inference" in summary.summary


def test_local_fallback_populates_tldr_fields():
    client = LocalStructuredClient()
    documents = [
        {"title": "New model release", "url": "https://example.com", "snippet": "A new model shipped."}
    ]
    summary = asyncio.run(client.summarize_story(documents, "medium"))

    assert summary.headline
    assert summary.summary


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

