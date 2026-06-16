from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from newsbot.types import Document, RawItem, SourceConfig
from newsbot.utils import canonicalize_url, parse_datetime, stable_id, utc_now


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  connector TEXT NOT NULL,
  url TEXT NOT NULL,
  trust_tier TEXT NOT NULL,
  enabled INTEGER NOT NULL,
  topics_json TEXT NOT NULL,
  options_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS raw_items (
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  external_id TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  published_at TEXT,
  author TEXT,
  content TEXT,
  payload_json TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE INDEX IF NOT EXISTS idx_raw_items_source ON raw_items(source_id);
CREATE INDEX IF NOT EXISTS idx_raw_items_published ON raw_items(published_at);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  raw_item_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  text TEXT NOT NULL,
  snippet TEXT NOT NULL,
  published_at TEXT,
  author TEXT,
  metadata_json TEXT NOT NULL,
  extracted_at TEXT NOT NULL,
  FOREIGN KEY(raw_item_id) REFERENCES raw_items(id),
  FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE INDEX IF NOT EXISTS idx_documents_source ON documents(source_id);
CREATE INDEX IF NOT EXISTS idx_documents_published ON documents(published_at);

CREATE TABLE IF NOT EXISTS story_clusters (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  first_seen_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  topic_slugs_json TEXT NOT NULL,
  ticker_symbols_json TEXT NOT NULL,
  reliability_score REAL NOT NULL,
  confidence TEXT NOT NULL,
  is_social_signal INTEGER NOT NULL,
  frontier_score REAL NOT NULL DEFAULT 0,
  frontier_category TEXT NOT NULL DEFAULT 'unscored',
  frontier_reasons_json TEXT NOT NULL DEFAULT '[]',
  buzz_score REAL NOT NULL DEFAULT 0,
  summary_json TEXT,
  alert_queued_at TEXT
);

CREATE TABLE IF NOT EXISTS cluster_documents (
  cluster_id TEXT NOT NULL,
  document_id TEXT NOT NULL,
  PRIMARY KEY(cluster_id, document_id),
  FOREIGN KEY(cluster_id) REFERENCES story_clusters(id),
  FOREIGN KEY(document_id) REFERENCES documents(id)
);

CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY,
  cluster_id TEXT NOT NULL,
  text TEXT NOT NULL,
  confidence TEXT NOT NULL,
  source_document_ids_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(cluster_id) REFERENCES story_clusters(id)
);

CREATE TABLE IF NOT EXISTS digests (
  id TEXT PRIMARY KEY,
  period TEXT NOT NULL,
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  title TEXT NOT NULL,
  summary_md TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_digests_period ON digests(period, period_start);

CREATE TABLE IF NOT EXISTS telegram_messages (
  id TEXT PRIMARY KEY,
  cluster_id TEXT,
  digest_id TEXT,
  text TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  sent_at TEXT,
  error TEXT,
  FOREIGN KEY(cluster_id) REFERENCES story_clusters(id),
  FOREIGN KEY(digest_id) REFERENCES digests(id)
);

CREATE INDEX IF NOT EXISTS idx_telegram_status ON telegram_messages(status);

CREATE TABLE IF NOT EXISTS source_health (
  source_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  checked_at TEXT NOT NULL,
  last_success_at TEXT,
  last_error TEXT,
  items_seen INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(source_id) REFERENCES sources(id)
);

CREATE TABLE IF NOT EXISTS story_feedback (
  cluster_id TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(cluster_id) REFERENCES story_clusters(id)
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(story_clusters)").fetchall()
        }
        if "frontier_score" not in columns:
            conn.execute("ALTER TABLE story_clusters ADD COLUMN frontier_score REAL NOT NULL DEFAULT 0")
        if "frontier_category" not in columns:
            conn.execute(
                "ALTER TABLE story_clusters ADD COLUMN frontier_category TEXT NOT NULL DEFAULT 'unscored'"
            )
        if "frontier_reasons_json" not in columns:
            conn.execute(
                "ALTER TABLE story_clusters ADD COLUMN frontier_reasons_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "buzz_score" not in columns:
            conn.execute("ALTER TABLE story_clusters ADD COLUMN buzz_score REAL NOT NULL DEFAULT 0")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS story_feedback (
              cluster_id TEXT PRIMARY KEY,
              label TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY(cluster_id) REFERENCES story_clusters(id)
            )
            """
        )

    def upsert_sources(self, sources: list[SourceConfig]) -> None:
        with self.connect() as conn:
            for source in sources:
                conn.execute(
                    """
                    INSERT INTO sources (
                      id, name, connector, url, trust_tier, enabled, topics_json,
                      options_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                      name=excluded.name,
                      connector=excluded.connector,
                      url=excluded.url,
                      trust_tier=excluded.trust_tier,
                      enabled=excluded.enabled,
                      topics_json=excluded.topics_json,
                      options_json=excluded.options_json,
                      updated_at=excluded.updated_at
                    """,
                    (
                        source.id,
                        source.name,
                        source.connector.value,
                        source.url,
                        source.trust_tier.value,
                        int(source.enabled),
                        json.dumps(list(source.topics)),
                        json.dumps(source.options),
                        utc_now(),
                    ),
                )

    def upsert_raw_item(self, item: RawItem) -> str:
        canonical_url = canonicalize_url(item.url)
        item_id = stable_id("raw", item.source_id, item.external_id or canonical_url or item.title)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO raw_items (
                  id, source_id, external_id, title, url, canonical_url, published_at,
                  author, content, payload_json, fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,
                  url=excluded.url,
                  canonical_url=excluded.canonical_url,
                  published_at=COALESCE(excluded.published_at, raw_items.published_at),
                  author=COALESCE(excluded.author, raw_items.author),
                  content=COALESCE(excluded.content, raw_items.content),
                  payload_json=excluded.payload_json,
                  fetched_at=excluded.fetched_at
                """,
                (
                    item_id,
                    item.source_id,
                    item.external_id,
                    item.title,
                    item.url,
                    canonical_url,
                    parse_datetime(item.published_at),
                    item.author,
                    item.content,
                    json.dumps(item.payload),
                    utc_now(),
                ),
            )
        return item_id

    def raw_items_without_documents(self, limit: int = 200) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT r.*
                FROM raw_items r
                LEFT JOIN documents d ON d.raw_item_id = r.id
                WHERE d.id IS NULL
                ORDER BY COALESCE(r.published_at, r.fetched_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return list(rows)

    def upsert_document(self, document: Document) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                  id, raw_item_id, source_id, title, url, canonical_url, text, snippet,
                  published_at, author, metadata_json, extracted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,
                  text=excluded.text,
                  snippet=excluded.snippet,
                  metadata_json=excluded.metadata_json,
                  extracted_at=excluded.extracted_at
                """,
                (
                    document.id,
                    document.raw_item_id,
                    document.source_id,
                    document.title,
                    document.url,
                    canonicalize_url(document.url),
                    document.text,
                    document.snippet,
                    parse_datetime(document.published_at),
                    document.author,
                    json.dumps(document.metadata),
                    utc_now(),
                ),
            )

    def get_document(self, document_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()

    def upsert_cluster(
        self,
        *,
        cluster_id: str,
        document_id: str,
        title: str,
        canonical_url: str,
        topic_slugs: list[str],
        ticker_symbols: list[str],
        reliability_score: float,
        confidence: str,
        is_social_signal: bool,
        frontier_score: float = 0,
        frontier_category: str = "unscored",
        frontier_reasons: list[str] | None = None,
        buzz_score: float = 0,
        summary: dict[str, Any] | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            existing = conn.execute(
                "SELECT first_seen_at, topic_slugs_json, ticker_symbols_json FROM story_clusters WHERE id = ?",
                (cluster_id,),
            ).fetchone()
            if existing:
                existing_topics = set(json.loads(existing["topic_slugs_json"]))
                existing_tickers = set(json.loads(existing["ticker_symbols_json"]))
                topic_slugs = sorted(existing_topics | set(topic_slugs))
                ticker_symbols = sorted(existing_tickers | set(ticker_symbols))
                first_seen = existing["first_seen_at"]
            else:
                first_seen = now
            conn.execute(
                """
                INSERT INTO story_clusters (
                  id, title, canonical_url, first_seen_at, updated_at, topic_slugs_json,
                  ticker_symbols_json, reliability_score, confidence, is_social_signal,
                  frontier_score, frontier_category, frontier_reasons_json, buzz_score,
                  summary_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,
                  updated_at=excluded.updated_at,
                  topic_slugs_json=excluded.topic_slugs_json,
                  ticker_symbols_json=excluded.ticker_symbols_json,
                  reliability_score=excluded.reliability_score,
                  confidence=excluded.confidence,
                  is_social_signal=excluded.is_social_signal,
                  frontier_score=excluded.frontier_score,
                  frontier_category=excluded.frontier_category,
                  frontier_reasons_json=excluded.frontier_reasons_json,
                  buzz_score=excluded.buzz_score,
                  summary_json=COALESCE(excluded.summary_json, story_clusters.summary_json)
                """,
                (
                    cluster_id,
                    title,
                    canonical_url,
                    first_seen,
                    now,
                    json.dumps(sorted(topic_slugs)),
                    json.dumps(sorted(ticker_symbols)),
                    reliability_score,
                    confidence,
                    int(is_social_signal),
                    frontier_score,
                    frontier_category,
                    json.dumps(frontier_reasons or []),
                    buzz_score,
                    json.dumps(summary) if summary else None,
                ),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO cluster_documents (cluster_id, document_id)
                VALUES (?, ?)
                """,
                (cluster_id, document_id),
            )

    def list_clusters(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        topic: str | None = None,
        include_not_interesting: bool = False,
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        clauses = []
        params: list[Any] = []
        if since:
            clauses.append("updated_at >= ?")
            params.append(since)
        if until:
            clauses.append("updated_at < ?")
            params.append(until)
        if topic:
            clauses.append("topic_slugs_json LIKE ?")
            params.append(f'%"{topic}"%')
        if not include_not_interesting:
            clauses.append(
                """
                NOT EXISTS (
                  SELECT 1 FROM story_feedback f
                  WHERE f.cluster_id = story_clusters.id
                    AND f.label = 'not_interesting'
                )
                """
            )
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM story_clusters
                {where}
                ORDER BY frontier_score DESC, reliability_score DESC, updated_at DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return list(rows)

    def get_cluster_feedback(self, cluster_id: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT label FROM story_feedback WHERE cluster_id = ?",
                (cluster_id,),
            ).fetchone()
        return str(row["label"]) if row else None

    def set_cluster_feedback(self, cluster_id: str, label: str) -> None:
        if label not in {"not_interesting", "interesting"}:
            raise ValueError("feedback label must be not_interesting or interesting")
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO story_feedback (cluster_id, label, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(cluster_id) DO UPDATE SET
                  label=excluded.label,
                  updated_at=excluded.updated_at
                """,
                (cluster_id, label, now, now),
            )

    def clear_cluster_feedback(self, cluster_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM story_feedback WHERE cluster_id = ?", (cluster_id,))

    def get_cluster(self, cluster_id: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM story_clusters WHERE id = ?",
                (cluster_id,),
            ).fetchone()

    def cluster_documents(self, cluster_id: str) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT d.*, s.name AS source_name, s.trust_tier AS source_trust_tier,
                       s.options_json AS source_options_json
                FROM documents d
                JOIN cluster_documents cd ON cd.document_id = d.id
                JOIN sources s ON s.id = d.source_id
                WHERE cd.cluster_id = ?
                ORDER BY COALESCE(d.published_at, d.extracted_at) DESC
                """,
                (cluster_id,),
            ).fetchall()
        return list(rows)

    def save_claims(self, cluster_id: str, claims: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM claims WHERE cluster_id = ?", (cluster_id,))
            seen_claim_ids: set[str] = set()
            for claim in claims:
                claim_id = stable_id("claim", cluster_id, claim.get("text"))
                if claim_id in seen_claim_ids:
                    continue
                seen_claim_ids.add(claim_id)
                conn.execute(
                    """
                    INSERT INTO claims (
                      id, cluster_id, text, confidence, source_document_ids_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        claim_id,
                        cluster_id,
                        claim.get("text", ""),
                        claim.get("confidence", "medium"),
                        json.dumps(claim.get("source_document_ids", [])),
                        utc_now(),
                    ),
                )

    def mark_cluster_alert_queued(self, cluster_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE story_clusters SET alert_queued_at = COALESCE(alert_queued_at, ?) WHERE id = ?",
                (utc_now(), cluster_id),
            )

    def update_cluster_frontier(
        self,
        cluster_id: str,
        *,
        frontier_score: float,
        frontier_category: str,
        frontier_reasons: list[str],
        buzz_score: float = 0,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE story_clusters
                SET frontier_score = ?,
                    frontier_category = ?,
                    frontier_reasons_json = ?,
                    buzz_score = ?,
                    updated_at = updated_at
                WHERE id = ?
                """,
                (
                    frontier_score,
                    frontier_category,
                    json.dumps(frontier_reasons),
                    buzz_score,
                    cluster_id,
                ),
            )

    def enqueue_telegram_message(
        self,
        *,
        text: str,
        cluster_id: str | None = None,
        digest_id: str | None = None,
    ) -> str:
        message_id = stable_id("telegram", cluster_id, digest_id, text)
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO telegram_messages (
                  id, cluster_id, digest_id, text, status, created_at
                )
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (message_id, cluster_id, digest_id, text, utc_now()),
            )
        return message_id

    def pending_telegram_messages(self, limit: int = 25) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM telegram_messages
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return list(rows)

    def list_telegram_messages(self, *, status: str | None = None, limit: int = 25) -> list[sqlite3.Row]:
        where = "WHERE status = ?" if status else ""
        params: tuple[Any, ...] = (status, limit) if status else (limit,)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM telegram_messages
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return list(rows)

    def delete_telegram_messages(self, *, status: str | None = None) -> int:
        where = "WHERE status = ?" if status else ""
        params: tuple[Any, ...] = (status,) if status else ()
        with self.connect() as conn:
            cursor = conn.execute(f"DELETE FROM telegram_messages {where}", params)
            return cursor.rowcount

    def mark_telegram_sent(self, message_id: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE telegram_messages SET status='sent', sent_at=?, error=NULL WHERE id=?",
                (utc_now(), message_id),
            )

    def mark_telegram_failed(self, message_id: str, error: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE telegram_messages SET status='failed', error=? WHERE id=?",
                (error[:1000], message_id),
            )

    def save_digest(
        self,
        *,
        digest_id: str,
        period: str,
        period_start: str,
        period_end: str,
        title: str,
        summary_md: str,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO digests (
                  id, period, period_start, period_end, title, summary_md, payload_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                  title=excluded.title,
                  summary_md=excluded.summary_md,
                  payload_json=excluded.payload_json,
                  created_at=excluded.created_at
                """,
                (
                    digest_id,
                    period,
                    period_start,
                    period_end,
                    title,
                    summary_md,
                    json.dumps(payload),
                    utc_now(),
                ),
            )

    def latest_digest(self, period: str = "daily") -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT *
                FROM digests
                WHERE period = ?
                ORDER BY period_start DESC
                LIMIT 1
                """,
                (period,),
            ).fetchone()

    def digest_by_start(self, period: str, period_start_prefix: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT *
                FROM digests
                WHERE period = ? AND period_start LIKE ?
                ORDER BY period_start DESC
                LIMIT 1
                """,
                (period, f"{period_start_prefix}%"),
            ).fetchone()

    def update_source_health(
        self,
        source_id: str,
        *,
        status: str,
        items_seen: int = 0,
        error: str | None = None,
    ) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO source_health (
                  source_id, status, checked_at, last_success_at, last_error, items_seen
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                  status=excluded.status,
                  checked_at=excluded.checked_at,
                  last_success_at=CASE
                    WHEN excluded.status = 'ok' THEN excluded.checked_at
                    ELSE source_health.last_success_at
                  END,
                  last_error=excluded.last_error,
                  items_seen=excluded.items_seen
                """,
                (
                    source_id,
                    status,
                    now,
                    now if status == "ok" else None,
                    error,
                    items_seen,
                ),
            )

    def health_rows(self) -> list[sqlite3.Row]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT s.id, s.name, s.connector, s.enabled, h.status, h.checked_at,
                       h.last_success_at, h.last_error, h.items_seen
                FROM sources s
                LEFT JOIN source_health h ON h.source_id = s.id
                ORDER BY s.connector, s.name
                """
            ).fetchall()
        return list(rows)

    def counts(self) -> dict[str, int]:
        tables = [
            "sources",
            "raw_items",
            "documents",
            "story_clusters",
            "claims",
            "digests",
            "telegram_messages",
            "story_feedback",
        ]
        with self.connect() as conn:
            return {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in tables
            }
