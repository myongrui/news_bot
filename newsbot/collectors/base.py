from __future__ import annotations

from dataclasses import dataclass, field

import httpx

from newsbot.config import AppConfig
from newsbot.types import RawItem, SourceConfig


@dataclass(frozen=True)
class CollectorResult:
    items: list[RawItem] = field(default_factory=list)
    status: str = "ok"
    error: str | None = None


class BaseCollector:
    def __init__(self, source: SourceConfig, config: AppConfig) -> None:
        self.source = source
        self.config = config

    async def collect(self, client: httpx.AsyncClient) -> CollectorResult:
        raise NotImplementedError

    def disabled(self, reason: str) -> CollectorResult:
        return CollectorResult(items=[], status="disabled", error=reason)

    def failed(self, error: Exception | str) -> CollectorResult:
        return CollectorResult(items=[], status="error", error=str(error))

