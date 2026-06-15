from newsbot.reliability import score_cluster
from newsbot.types import Confidence, SourceTier


def test_trusted_single_source_can_alert():
    result = score_cluster([SourceTier.TRUSTED_MEDIA.value])

    assert result.alert_allowed is True
    assert result.confidence == Confidence.HIGH


def test_single_social_source_is_digest_only():
    result = score_cluster([SourceTier.COMMUNITY_SOCIAL.value])

    assert result.alert_allowed is False
    assert result.social_only is True
    assert result.confidence == Confidence.LOW


def test_conflict_suppresses_alert():
    result = score_cluster([SourceTier.PRIMARY_OFFICIAL.value], has_conflict=True)

    assert result.alert_allowed is False
    assert result.confidence == Confidence.CAUTION

