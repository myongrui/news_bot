from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Protocol

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from newsbot.utils import clean_text

if TYPE_CHECKING:
    from newsbot.config import Settings


class AiValidationError(RuntimeError):
    pass


class ClaimSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1)
    confidence: str = Field(pattern="^(high|medium|low|caution)$")
    source_document_ids: list[str] = Field(default_factory=list)


class StorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    confidence: str = Field(pattern="^(high|medium|low|caution)$")
    why_it_matters: str = Field(min_length=1)
    frontier_category: str = Field(default="strategic_context", min_length=1)
    frontier_reason: str = Field(default="", min_length=0)
    market_or_technical_impact: str = Field(default="", min_length=0)
    watch_next: str = Field(default="", min_length=0)
    bullets: list[str] = Field(min_length=1, max_length=3)
    claims: list[ClaimSummary] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)


class DigestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1)
    overview: str = Field(min_length=1)
    key_points: list[str] = Field(default_factory=list, max_length=8)
    watch_next: list[str] = Field(default_factory=list, max_length=5)


class AiClient(Protocol):
    async def summarize_story(self, documents: list[dict[str, Any]], confidence: str) -> StorySummary:
        ...

    async def summarize_digest(
        self,
        period: str,
        clusters: list[dict[str, Any]],
    ) -> DigestSummary:
        ...


class OpenAIResponsesClient:
    def __init__(self, settings: Settings, *, model: str = "gpt-5-mini") -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAIResponsesClient")
        self.api_key = settings.openai_api_key
        self.model = model

    async def summarize_story(self, documents: list[dict[str, Any]], confidence: str) -> StorySummary:
        prompt = {
            "task": "Summarize one news/research story for a personal AI/tech/stocks digest.",
            "rules": [
                "Use only the supplied documents.",
                "Do not include buy/sell/hold recommendations.",
                "Every factual bullet must be traceable to at least one supplied URL.",
                "Explain why a hybrid AI builder/investor should care.",
                "Do not imply trading advice or action.",
                "If the documents conflict, set confidence to caution.",
                "Return exactly three bullets unless fewer facts are available.",
            ],
            "input_confidence": confidence,
            "documents": documents,
        }
        data = await self._structured_response(
            name="story_summary",
            schema=StorySummary.model_json_schema(),
            prompt=json.dumps(prompt, ensure_ascii=False),
        )
        try:
            return StorySummary.model_validate_json(data)
        except ValidationError as exc:
            raise AiValidationError(str(exc)) from exc

    async def summarize_digest(
        self,
        period: str,
        clusters: list[dict[str, Any]],
    ) -> DigestSummary:
        prompt = {
            "task": f"Create a concise {period} digest overview for tech, AI, and stock-adjacent news.",
            "rules": [
                "Use only the supplied story clusters.",
                "Keep it factual and cited by story URLs.",
                "Do not include buy/sell/hold recommendations.",
                "Mention uncertainty where confidence is low or caution.",
            ],
            "clusters": clusters,
        }
        data = await self._structured_response(
            name="digest_summary",
            schema=DigestSummary.model_json_schema(),
            prompt=json.dumps(prompt, ensure_ascii=False),
        )
        try:
            return DigestSummary.model_validate_json(data)
        except ValidationError as exc:
            raise AiValidationError(str(exc)) from exc

    async def _structured_response(self, *, name: str, schema: dict[str, Any], prompt: str) -> str:
        payload = {
            "model": self.model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "You are a cautious news analyst. You produce structured JSON only, "
                        "cite source URLs, label uncertainty, and avoid financial advice."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        data = response.json()
        text = _extract_output_text(data)
        if not text:
            raise AiValidationError("OpenAI response did not contain output text")
        return text


class LocalStructuredClient:
    """Deterministic fallback for local development and tests when API keys are absent."""

    async def summarize_story(self, documents: list[dict[str, Any]], confidence: str) -> StorySummary:
        first = documents[0] if documents else {}
        title = clean_text(str(first.get("title") or "Untitled story"), max_chars=140)
        citations = [str(doc.get("url")) for doc in documents if doc.get("url")]
        snippets = [clean_text(str(doc.get("snippet") or ""), max_chars=220) for doc in documents]
        bullets = [snippet for snippet in snippets if snippet][:3] or ["No extractable summary was available."]
        claims = [
            ClaimSummary(
                text=bullet,
                confidence=confidence if confidence in {"high", "medium", "low", "caution"} else "medium",
                source_document_ids=[str(first.get("id"))] if first.get("id") else [],
            )
            for bullet in bullets[:3]
        ]
        return StorySummary(
            title=title,
            confidence=confidence if confidence in {"high", "medium", "low", "caution"} else "medium",
            why_it_matters="This item is relevant to the configured AI, tech, research, or market watchlist.",
            frontier_category="strategic_context",
            frontier_reason="Matched the configured frontier intelligence watchlist.",
            market_or_technical_impact="Potentially relevant to AI, technology, or market context.",
            watch_next="Watch for primary-source updates, filings, benchmarks, or follow-up reporting.",
            bullets=bullets[:3],
            claims=claims,
            citations=citations[:5],
        )

    async def summarize_digest(
        self,
        period: str,
        clusters: list[dict[str, Any]],
    ) -> DigestSummary:
        key_points = [
            clean_text(f"{cluster.get('title')}: {cluster.get('why_it_matters', '')}", max_chars=180)
            for cluster in clusters[:8]
        ]
        return DigestSummary(
            title=f"{period.title()} Newsbot Brief",
            overview=f"{len(clusters)} relevant story clusters were captured for this {period} period.",
            key_points=key_points,
            watch_next=[
                "Watch for primary-source updates and filings related to high-confidence clusters.",
                "Treat community-only signals as leads until corroborated.",
            ],
        )


def make_ai_client(settings: Settings) -> AiClient:
    if settings.openai_api_key:
        return OpenAIResponsesClient(settings)
    if settings.offline_summaries:
        return LocalStructuredClient()
    raise ValueError("OPENAI_API_KEY is required when NEWSBOT_OFFLINE_SUMMARIES=false")


def _extract_output_text(data: dict[str, Any]) -> str | None:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts: list[str] = []
    for output in data.get("output", []):
        for content in output.get("content", []):
            if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "\n".join(parts).strip() or None
