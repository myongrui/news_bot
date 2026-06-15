from newsbot.config import Settings, load_app_config


def test_load_app_config_from_yaml(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'newsbot.db'}",
        data_dir=tmp_path / "data",
        upload_dir=tmp_path / "uploads",
        config_dir="config",
    )

    config = load_app_config(settings)

    assert config.source_by_id("hacker_news") is not None
    assert any(ticker.symbol == "NVDA" for ticker in config.tickers)
    assert any(topic.slug == "ai" for topic in config.topics)

