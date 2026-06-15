from __future__ import annotations

import re

from newsbot.types import TickerConfig, TopicConfig


def classify_topics(text: str, topics: list[TopicConfig], source_topics: tuple[str, ...] = ()) -> list[str]:
    haystack = f" {text.lower()} "
    matched = set(source_topics)
    for topic in topics:
        for keyword in topic.keywords:
            if _contains_phrase(haystack, keyword.lower()):
                matched.add(topic.slug)
                break
    return sorted(matched)


def classify_tickers(text: str, tickers: list[TickerConfig]) -> list[str]:
    matched: set[str] = set()
    for ticker in tickers:
        symbol_pattern = rf"(?<![A-Za-z0-9$])\$?{re.escape(ticker.symbol)}(?![A-Za-z0-9])"
        short_symbol_pattern = rf"(?<![A-Za-z0-9$])\${re.escape(ticker.symbol)}(?![A-Za-z0-9])"
        if re.search(short_symbol_pattern if len(ticker.symbol) <= 2 else symbol_pattern, text):
            matched.add(ticker.symbol)
            continue
        for alias in (ticker.name, *ticker.aliases):
            if _contains_phrase(text.lower(), alias.lower()):
                matched.add(ticker.symbol)
                break
    return sorted(matched)


def _contains_phrase(haystack: str, needle: str) -> bool:
    if not needle:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
    return bool(re.search(pattern, haystack, re.IGNORECASE))
