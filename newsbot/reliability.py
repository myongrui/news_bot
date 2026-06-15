from __future__ import annotations

from dataclasses import dataclass

from newsbot.types import Confidence, SourceTier


TIER_BASE_SCORE = {
    SourceTier.PRIMARY_OFFICIAL.value: 0.94,
    SourceTier.TRUSTED_MEDIA.value: 0.84,
    SourceTier.RESEARCH.value: 0.78,
    SourceTier.COMMUNITY_SOCIAL.value: 0.42,
    SourceTier.UNKNOWN.value: 0.30,
}


@dataclass(frozen=True)
class ReliabilityResult:
    score: float
    confidence: Confidence
    alert_allowed: bool
    social_only: bool
    reason: str


def score_cluster(source_tiers: list[str], *, has_conflict: bool = False) -> ReliabilityResult:
    if not source_tiers:
        return ReliabilityResult(0.0, Confidence.LOW, False, False, "No sources")
    scores = [TIER_BASE_SCORE.get(tier, TIER_BASE_SCORE[SourceTier.UNKNOWN.value]) for tier in source_tiers]
    score = max(scores)
    independent_count = len(set(source_tiers))
    social_only = all(tier == SourceTier.COMMUNITY_SOCIAL.value for tier in source_tiers)
    if len(source_tiers) >= 2:
        score = min(0.99, score + 0.08)
    if independent_count >= 2:
        score = min(0.99, score + 0.04)
    if has_conflict:
        score = min(score, 0.55)
        return ReliabilityResult(score, Confidence.CAUTION, False, social_only, "Conflicting claims")
    trusted_single = any(
        tier in {SourceTier.PRIMARY_OFFICIAL.value, SourceTier.TRUSTED_MEDIA.value}
        for tier in source_tiers
    )
    corroborated_social = social_only and len(source_tiers) >= 2
    alert_allowed = (trusted_single and score >= 0.80) or corroborated_social
    confidence = Confidence.HIGH if score >= 0.80 else Confidence.MEDIUM if score >= 0.60 else Confidence.LOW
    reason = "Trusted single source" if trusted_single else "Corroborated social signal" if corroborated_social else "Digest only"
    return ReliabilityResult(score, confidence, alert_allowed, social_only, reason)

