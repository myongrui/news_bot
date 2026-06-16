from newsbot.engagement import cluster_engagement, engagement_score


def test_non_social_sources_have_zero_buzz():
    assert engagement_score({"connector": "rss"}) == 0.0
    assert engagement_score({"connector": "arxiv"}) == 0.0
    assert engagement_score(None) == 0.0


def test_buzz_increases_with_engagement_and_is_bounded():
    quiet = engagement_score({"connector": "hn", "score": 5, "comments": 1})
    loud = engagement_score({"connector": "hn", "score": 800, "comments": 600})
    assert 0.0 < quiet < loud <= 1.0


def test_x_metrics_are_aggregated():
    score = engagement_score(
        {
            "connector": "x",
            "metrics": {
                "like_count": 4000,
                "retweet_count": 800,
                "reply_count": 300,
                "quote_count": 100,
            },
        }
    )
    assert score > 0.5


def test_cluster_engagement_takes_max():
    metadata = [
        {"connector": "rss"},
        {"connector": "hn", "score": 400, "comments": 200},
        {"connector": "reddit", "score": 10, "num_comments": 2},
    ]
    assert cluster_engagement(metadata) == engagement_score(metadata[1])
    assert cluster_engagement([]) == 0.0
