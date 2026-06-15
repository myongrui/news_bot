from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import AliasChoices, BaseModel, Field

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:  # pragma: no cover - local test fallback before dependencies are installed.
    BaseSettings = BaseModel  # type: ignore[assignment]

    def SettingsConfigDict(**kwargs: Any) -> dict[str, Any]:
        return {"extra": kwargs.get("extra", "ignore"), "populate_by_name": True}

from newsbot.types import Connector, SourceConfig, SourceTier, TickerConfig, TopicConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NEWSBOT_", extra="ignore")

    database_url: str = "sqlite:///data/newsbot.db"
    base_url: str = "http://127.0.0.1:8000"
    timezone: str = "Asia/Singapore"
    config_dir: Path = Path("config")
    data_dir: Path = Path("data")
    upload_dir: Path = Path("data/uploads")
    http_user_agent: str = "Newsbot/0.1 (+local personal research bot)"
    offline_summaries: bool = True

    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OPENAI_API_KEY", "NEWSBOT_OPENAI_API_KEY"),
    )
    telegram_bot_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TELEGRAM_BOT_TOKEN", "NEWSBOT_TELEGRAM_BOT_TOKEN"),
    )
    telegram_chat_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TELEGRAM_CHAT_ID", "NEWSBOT_TELEGRAM_CHAT_ID"),
    )
    reddit_client_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REDDIT_CLIENT_ID", "NEWSBOT_REDDIT_CLIENT_ID"),
    )
    reddit_client_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REDDIT_CLIENT_SECRET", "NEWSBOT_REDDIT_CLIENT_SECRET"),
    )
    reddit_user_agent: str = Field(
        default="newsbot/0.1 by local-user",
        validation_alias=AliasChoices("REDDIT_USER_AGENT", "NEWSBOT_REDDIT_USER_AGENT"),
    )
    x_bearer_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("X_BEARER_TOKEN", "NEWSBOT_X_BEARER_TOKEN"),
    )

    @property
    def sqlite_path(self) -> Path:
        if not self.database_url.startswith("sqlite:///"):
            raise ValueError("V1 supports only sqlite:/// database URLs")
        return Path(self.database_url.removeprefix("sqlite:///"))

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)


class AppConfig:
    def __init__(
        self,
        *,
        settings: Settings,
        sources: list[SourceConfig],
        topics: list[TopicConfig],
        tickers: list[TickerConfig],
        curation: dict[str, Any],
    ) -> None:
        self.settings = settings
        self.sources = sources
        self.topics = topics
        self.tickers = tickers
        self.curation = curation

    def enabled_sources(self, connector: str | None = None) -> list[SourceConfig]:
        sources = [source for source in self.sources if source.enabled]
        if connector and connector != "all":
            sources = [source for source in sources if source.connector.value == connector]
        return sources

    def source_by_id(self, source_id: str) -> SourceConfig | None:
        return next((source for source in self.sources if source.id == source_id), None)


def load_app_config(settings: Settings | None = None) -> AppConfig:
    settings = settings or Settings()
    settings.ensure_dirs()
    config_dir = settings.config_dir
    sources = _load_sources(config_dir / "sources.yaml")
    topics = _load_topics(config_dir / "topics.yaml")
    tickers = _load_tickers(config_dir / "basket.yaml")
    curation = _load_curation(config_dir / "curation.yaml")
    return AppConfig(
        settings=settings,
        sources=sources,
        topics=topics,
        tickers=tickers,
        curation=curation,
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    import yaml

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def _load_sources(path: Path) -> list[SourceConfig]:
    data = _load_yaml(path)
    items = data.get("sources", [])
    if not isinstance(items, list):
        raise ValueError("sources.yaml must contain a list under 'sources'")
    sources: list[SourceConfig] = []
    known = {
        "id",
        "name",
        "connector",
        "url",
        "trust_tier",
        "enabled",
        "topics",
    }
    for item in items:
        options = {key: value for key, value in item.items() if key not in known}
        sources.append(
            SourceConfig(
                id=str(item["id"]),
                name=str(item["name"]),
                connector=Connector(str(item["connector"])),
                url=str(item["url"]),
                trust_tier=SourceTier(str(item.get("trust_tier", SourceTier.UNKNOWN))),
                enabled=bool(item.get("enabled", True)),
                topics=tuple(str(topic) for topic in item.get("topics", [])),
                options=options,
            )
        )
    return sources


def _load_topics(path: Path) -> list[TopicConfig]:
    data = _load_yaml(path)
    topics = data.get("topics", [])
    if not isinstance(topics, list):
        raise ValueError("topics.yaml must contain a list under 'topics'")
    return [
        TopicConfig(
            slug=str(item["slug"]),
            name=str(item["name"]),
            keywords=tuple(str(keyword) for keyword in item.get("keywords", [])),
        )
        for item in topics
    ]


def _load_tickers(path: Path) -> list[TickerConfig]:
    data = _load_yaml(path)
    tickers = data.get("tickers", [])
    if not isinstance(tickers, list):
        raise ValueError("basket.yaml must contain a list under 'tickers'")
    return [
        TickerConfig(
            symbol=str(item["symbol"]).upper(),
            name=str(item["name"]),
            aliases=tuple(str(alias) for alias in item.get("aliases", [])),
            cik=str(item["cik"]) if item.get("cik") else None,
        )
        for item in tickers
    ]


def _load_curation(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "curation": {},
            "alerts": {},
            "digests": {},
        }
    return _load_yaml(path)
