from __future__ import annotations

import hashlib
import html
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "source"}


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def parse_datetime(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).replace(microsecond=0).isoformat()


def digest_id(period: str, start: datetime, end: datetime) -> str:
    return stable_id("digest", period, start.isoformat(), end.isoformat())


def stable_id(*parts: object, length: int = 24) -> str:
    joined = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:length]


def canonicalize_url(url: str) -> str:
    if not url:
        return url
    split = urlsplit(url.strip())
    scheme = (split.scheme or "https").lower()
    netloc = split.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    query = []
    for key, value in parse_qsl(split.query, keep_blank_values=True):
        lower_key = key.lower()
        if lower_key in TRACKING_KEYS or any(lower_key.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query.append((key, value))
    path = re.sub(r"/+$", "", split.path) or "/"
    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def clean_text(value: str, *, max_chars: int | None = None) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "..."
    return text


def strip_html(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return clean_text(text)


def normalize_title(value: str) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def snippet(value: str, *, limit: int = 700) -> str:
    return clean_text(value, max_chars=limit)


def chunked(items: Iterable[object], size: int) -> Iterable[list[object]]:
    batch: list[object] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def period_bounds(period: str, now: datetime | None = None) -> tuple[datetime, datetime]:
    now = now or datetime.now(UTC)
    now = now.astimezone(UTC)
    if period == "daily":
        start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        return start, start + timedelta(days=1)
    if period == "weekly":
        start = datetime(now.year, now.month, now.day, tzinfo=UTC) - timedelta(days=now.weekday())
        return start, start + timedelta(days=7)
    raise ValueError("period must be daily or weekly")


def parse_period_start(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
