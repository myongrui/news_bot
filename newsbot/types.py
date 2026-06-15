from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SourceTier(StrEnum):
    PRIMARY_OFFICIAL = "primary_official"
    TRUSTED_MEDIA = "trusted_media"
    RESEARCH = "research"
    COMMUNITY_SOCIAL = "community_social"
    UNKNOWN = "unknown"


class Connector(StrEnum):
    RSS = "rss"
    HN = "hn"
    ARXIV = "arxiv"
    SEC = "sec"
    GDELT = "gdelt"
    REDDIT = "reddit"
    X = "x"
    UPLOADS = "uploads"


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    CAUTION = "caution"


@dataclass(frozen=True)
class SourceConfig:
    id: str
    name: str
    connector: Connector
    url: str
    trust_tier: SourceTier = SourceTier.UNKNOWN
    enabled: bool = True
    topics: tuple[str, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TopicConfig:
    slug: str
    name: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class TickerConfig:
    symbol: str
    name: str
    aliases: tuple[str, ...] = ()
    cik: str | None = None


@dataclass(frozen=True)
class RawItem:
    source_id: str
    external_id: str
    title: str
    url: str
    published_at: str | None = None
    author: str | None = None
    content: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Document:
    id: str
    raw_item_id: str
    source_id: str
    title: str
    url: str
    text: str
    snippet: str
    published_at: str | None = None
    author: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

