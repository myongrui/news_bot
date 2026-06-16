from __future__ import annotations

from newsbot.collectors.arxiv import ArxivCollector
from newsbot.collectors.base import BaseCollector, CollectorResult
from newsbot.collectors.devto import DevToCollector
from newsbot.collectors.gdelt import GdeltCollector
from newsbot.collectors.github_trending import GitHubTrendingCollector
from newsbot.collectors.hn import HackerNewsCollector
from newsbot.collectors.lobsters import LobstersCollector
from newsbot.collectors.reddit import RedditCollector
from newsbot.collectors.rss import RssCollector
from newsbot.collectors.sec import SecCollector
from newsbot.collectors.stocktwits import StockTwitsCollector
from newsbot.collectors.uploads import UploadsCollector
from newsbot.collectors.x import XCollector
from newsbot.types import Connector

COLLECTOR_TYPES: dict[Connector, type[BaseCollector]] = {
    Connector.RSS: RssCollector,
    Connector.HN: HackerNewsCollector,
    Connector.ARXIV: ArxivCollector,
    Connector.SEC: SecCollector,
    Connector.GDELT: GdeltCollector,
    Connector.REDDIT: RedditCollector,
    Connector.X: XCollector,
    Connector.UPLOADS: UploadsCollector,
    Connector.LOBSTERS: LobstersCollector,
    Connector.DEVTO: DevToCollector,
    Connector.STOCKTWITS: StockTwitsCollector,
    Connector.GITHUB_TRENDING: GitHubTrendingCollector,
}

__all__ = ["COLLECTOR_TYPES", "BaseCollector", "CollectorResult"]

