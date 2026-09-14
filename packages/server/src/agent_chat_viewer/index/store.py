"""Local index cache.

Scanning every rollout file on each request does not scale past a few hundred
sessions, so summaries and message text are cached in a SQLite database with an
FTS5 table for search. Freshness is decided per source file by
``(mtime, size)``; nothing else is trusted.

The cache is disposable: deleting ``index.db`` only costs a rescan.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..models import (
    ProviderId,
    SearchHit,
    SearchResult,
    Session,
    SessionSummary,
    Stats,
    StatsBucket,
)
from ..util.text import message_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    uid           TEXT PRIMARY KEY,
    provider      TEXT NOT NULL,
    session_id    TEXT NOT NULL,
    title         TEXT,
    cwd           TEXT,
    project       TEXT,
    created_at    REAL,
    updated_at    REAL,
    message_count INTEGER,
    model         TEXT,
    parent_uid    TEXT,
    kind          TEXT,
    tokens_input  INTEGER,
    tokens_output INTEGER,
    cost          REAL,
    source_path   TEXT,
    source_mtime  REAL,
    source_size   INTEGER,
    parse_status  TEXT,
    summary_json  TEXT NOT NULL,
    indexed_at    REAL
);
CREATE INDEX IF NOT EXISTS sessions_updated ON sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS sessions_provider ON sessions(provider);
CREATE INDEX IF NOT EXISTS sessions_project ON sessions(project);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    uid UNINDEXED,
    message_id UNINDEXED,
    role UNINDEXED,
    text,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""

MAX_FTS_CHARS = 200_000


def _ts(value: datetime | None) -> float | None:
    return value.timestamp() if value else None


def _dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


class Index:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- writes ------------------------------------------------------------
    def fingerprints(self, provider: str) -> dict[str, tuple[float | None, int | None, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT uid, source_mtime, source_size, parse_status FROM sessions WHERE provider = ?",
                (provider,),
            ).fetchall()
        return {row["uid"]: (row["source_mtime"], row["source_size"], row["parse_status"]) for row in rows}

    def upsert(self, session: Session) -> None:
        summary = session.summary
        tokens = summary.tokens
        payload = summary.model_dump(mode="json")
        with self._lock:
            self._conn.execute("DELETE FROM messages_fts WHERE uid = ?", (summary.uid,))
            self._conn.execute(
                """
                INSERT INTO sessions (
                    uid, provider, session_id, title, cwd, project, created_at, updated_at,
                    message_count, model, parent_uid, kind, tokens_input, tokens_output, cost,
                    source_path, source_mtime, source_size, parse_status, summary_json, indexed_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(uid) DO UPDATE SET
                    title=excluded.title, cwd=excluded.cwd, project=excluded.project,
                    created_at=excluded.created_at, updated_at=excluded.updated_at,
                    message_count=excluded.message_count, model=excluded.model,
                    parent_uid=excluded.parent_uid, kind=excluded.kind,
                    tokens_input=excluded.tokens_input, tokens_output=excluded.tokens_output,
                    cost=excluded.cost, source_path=excluded.source_path,
                    source_mtime=excluded.source_mtime, source_size=excluded.source_size,
                    parse_status=excluded.parse_status, summary_json=excluded.summary_json,
                    indexed_at=excluded.indexed_at
                """,
                (
                    summary.uid,
                    summary.provider,
                    summary.id,
                    summary.title,
                    summary.cwd,
                    summary.project,
                    _ts(summary.created_at),
                    _ts(summary.updated_at),
                    summary.message_count,
                    summary.model,
                    summary.parent_uid,
                    summary.kind,
                    tokens.input if tokens else None,
                    tokens.output if tokens else None,
                    summary.cost,
                    summary.source_path,
                    summary.source_mtime,
                    summary.source_size,
                    summary.parse_status,
                    json.dumps(payload, ensure_ascii=False),
                    datetime.now(tz=UTC).timestamp(),
                ),
            )
            budget = MAX_FTS_CHARS
            for message in session.messages:
                text = message_text(message)
                if not text:
                    continue
                if budget <= 0:
                    break
                chunk = text[:budget]
                budget -= len(chunk)
                self._conn.execute(
                    "INSERT INTO messages_fts (uid, message_id, role, text) VALUES (?,?,?,?)",
                    (summary.uid, message.id, message.role, chunk),
                )
            self._conn.commit()

    def delete(self, uids: list[str]) -> None:
        if not uids:
            return
        with self._lock:
            self._conn.executemany("DELETE FROM sessions WHERE uid = ?", [(u,) for u in uids])
            self._conn.executemany("DELETE FROM messages_fts WHERE uid = ?", [(u,) for u in uids])
            self._conn.commit()

    # -- reads -------------------------------------------------------------
    def get(self, uid: str) -> SessionSummary | None:
        with self._lock:
            row = self._conn.execute("SELECT summary_json FROM sessions WHERE uid = ?", (uid,)).fetchone()
        return SessionSummary.model_validate_json(row["summary_json"]) if row else None

    def list_sessions(
        self,
        *,
        providers: list[str] | None = None,
        project: str | None = None,
        query: str | None = None,
        kind: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        sort: str = "updated",
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[SessionSummary], int]:
        where: list[str] = []
        args: list[Any] = []
        if providers:
            where.append(f"provider IN ({','.join('?' * len(providers))})")
            args.extend(providers)
        if project:
            where.append("(project = ? OR cwd = ?)")
            args.extend([project, project])
        if kind:
            where.append("kind = ?")
            args.append(kind)
        if since:
            where.append("COALESCE(updated_at, created_at, 0) >= ?")
            args.append(since.timestamp())
        if until:
            where.append("COALESCE(updated_at, created_at, 0) <= ?")
            args.append(until.timestamp())
        if query:
            where.append(
                "(LOWER(COALESCE(title,'')) LIKE ? OR LOWER(COALESCE(project,'')) LIKE ?"
                " OR uid IN (SELECT uid FROM messages_fts WHERE messages_fts MATCH ?))"
            )
            like = f"%{query.lower()}%"
            args.extend([like, like, _fts_query(query)])

        clause = f"WHERE {' AND '.join(where)}" if where else ""
        order = {
            "updated": "COALESCE(updated_at, created_at, 0) DESC",
            "created": "COALESCE(created_at, updated_at, 0) DESC",
            "messages": "COALESCE(message_count,0) DESC",
            "title": "LOWER(COALESCE(title,'')) ASC",
        }.get(sort, "COALESCE(updated_at, created_at, 0) DESC")

        with self._lock:
            try:
                total = self._conn.execute(
                    f"SELECT COUNT(*) FROM sessions {clause}",  # noqa: S608 - clause is parameterized
                    args,
                ).fetchone()[0]
                rows = self._conn.execute(
                    f"SELECT summary_json FROM sessions {clause} ORDER BY {order} LIMIT ? OFFSET ?",  # noqa: S608
                    [*args, limit, offset],
                ).fetchall()
            except sqlite3.OperationalError:
                # A malformed FTS expression must not 500 the listing.
                return [], 0
        return [SessionSummary.model_validate_json(row["summary_json"]) for row in rows], total

    def search(self, query: str, limit: int = 50) -> SearchResult:
        if not query.strip():
            return SearchResult(query=query)
        sql = """
            SELECT f.uid AS uid, f.message_id AS message_id, f.role AS role,
                   snippet(messages_fts, 3, '<<', '>>', '…', 14) AS snippet,
                   s.summary_json AS summary_json
            FROM messages_fts f JOIN sessions s ON s.uid = f.uid
            WHERE messages_fts MATCH ?
            ORDER BY rank LIMIT ?
        """
        with self._lock:
            try:
                rows = self._conn.execute(sql, (_fts_query(query), limit)).fetchall()
            except sqlite3.OperationalError:
                return SearchResult(query=query)
        hits: list[SearchHit] = []
        for row in rows:
            summary = SessionSummary.model_validate_json(row["summary_json"])
            hits.append(
                SearchHit(
                    uid=row["uid"],
                    provider=summary.provider,
                    title=summary.title,
                    project=summary.project,
                    role=row["role"],
                    message_id=row["message_id"],
                    snippet=row["snippet"] or "",
                    updated_at=summary.updated_at,
                )
            )
        return SearchResult(items=hits, total=len(hits), query=query)

    def projects(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT COALESCE(cwd, '') AS cwd,
                       COALESCE(project, '(unknown)') AS project,
                       COUNT(*) AS sessions,
                       MAX(COALESCE(updated_at, created_at, 0)) AS updated,
                       GROUP_CONCAT(DISTINCT provider) AS providers
                FROM sessions GROUP BY COALESCE(cwd, project) ORDER BY updated DESC
                """
            ).fetchall()
        return [
            {
                "cwd": row["cwd"] or None,
                "name": row["project"],
                "session_count": row["sessions"],
                "providers": sorted((row["providers"] or "").split(",")) if row["providers"] else [],
                "updated_at": _dt(row["updated"]),
            }
            for row in rows
        ]

    def stats(self) -> Stats:
        with self._lock:
            totals = self._conn.execute(
                """
                SELECT COUNT(*) AS sessions, COALESCE(SUM(message_count),0) AS messages,
                       COALESCE(SUM(tokens_input),0) AS ti, COALESCE(SUM(tokens_output),0) AS to_,
                       COALESCE(SUM(cost),0) AS cost
                FROM sessions
                """
            ).fetchone()
            by_provider = self._conn.execute(_bucket_sql("provider")).fetchall()
            by_model = self._conn.execute(_bucket_sql("COALESCE(model,'(unknown)')")).fetchall()
            by_day = self._conn.execute(
                _bucket_sql("DATE(COALESCE(updated_at, created_at, 0), 'unixepoch')")
            ).fetchall()
        return Stats(
            total_sessions=totals["sessions"],
            total_messages=totals["messages"],
            tokens_input=totals["ti"],
            tokens_output=totals["to_"],
            cost=totals["cost"],
            by_provider=[_bucket(row) for row in by_provider],
            by_model=[_bucket(row) for row in by_model],
            by_day=[_bucket(row) for row in by_day],
        )

    def provider_counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._conn.execute("SELECT provider, COUNT(*) AS n FROM sessions GROUP BY provider")
            return {row["provider"]: row["n"] for row in rows.fetchall()}

    def children(self, parent_uid: str) -> list[SessionSummary]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT summary_json FROM sessions WHERE parent_uid = ? ORDER BY created_at", (parent_uid,)
            ).fetchall()
        return [SessionSummary.model_validate_json(row["summary_json"]) for row in rows]


def _bucket_sql(expr: str) -> str:
    return f"""
        SELECT {expr} AS key, COUNT(*) AS sessions, COALESCE(SUM(message_count),0) AS messages,
               COALESCE(SUM(tokens_input),0) AS ti, COALESCE(SUM(tokens_output),0) AS to_,
               COALESCE(SUM(cost),0) AS cost
        FROM sessions GROUP BY key ORDER BY sessions DESC
    """  # noqa: S608 - expr is a fixed literal chosen by the caller


def _bucket(row: sqlite3.Row) -> StatsBucket:
    return StatsBucket(
        key=str(row["key"]),
        sessions=row["sessions"],
        messages=row["messages"],
        tokens_input=row["ti"],
        tokens_output=row["to_"],
        cost=row["cost"],
    )


def _fts_query(query: str) -> str:
    """Quote user input so FTS5 operators cannot produce a syntax error."""
    terms = [term for term in query.split() if term]
    if not terms:
        return '""'
    return " ".join('"' + term.replace('"', '""') + '"' for term in terms)


def provider_of(uid: str) -> ProviderId:  # pragma: no cover - trivial
    return uid.split(":", 1)[0]  # type: ignore[return-value]
