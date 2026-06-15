from newsbot.utils import canonicalize_url, normalize_title


def test_canonicalize_url_removes_tracking_and_www():
    url = "https://www.Example.com/path/?utm_source=x&gclid=1&a=2"

    assert canonicalize_url(url) == "https://example.com/path?a=2"


def test_normalize_title_for_cluster_keys():
    assert normalize_title(" NVIDIA's New AI-Chip! ") == "nvidia s new ai chip"

