from __future__ import annotations

import json
import os
import re
import sqlite3
import unicodedata
from urllib.parse import unquote
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_DB = os.getenv("ICPMS_DB_PATH", "data/intelligence.db")


def evidence_identity(row: dict | sqlite3.Row) -> tuple[str, ...]:
    """Return a conservative identity key for one public-evidence record.

    Prefer DOI, then exact URL. Title fallback is scoped by source and date;
    matching titles alone must not merge distinct identified publications.
    """
    def value(name: str, default: str = ""):
        if isinstance(row, sqlite3.Row):
            return row[name] if name in row.keys() else default
        return row.get(name, default)

    title = unicodedata.normalize("NFKC", str(value("title") or "")).casefold()
    title = re.sub(r"[^\w]+", " ", title, flags=re.UNICODE).strip()
    source_type = str(value("source_type", "other") or "other").strip().casefold()
    url = str(value("url") or "").strip()
    if source_type == "journal":
        doi = str(value("doi") or "").strip()
        if doi.lower() in {"nan", "none"}:
            doi = ""
        match = re.search(r"(?:https?://(?:dx\.)?doi.org/|^doi:\s*)(.+)", doi or url, re.I)
        if match:
            doi = match.group(1)
        if doi.startswith("10."):
            return ("doi", unquote(doi).casefold())
        if url and url.lower() not in {"nan", "none"}:
            return ("journal-url", url)
        return ("journal-fallback", title, str(value("source_name")), str(value("published_date")))
    return ("record", title, url)


def db_path(path: str | None = None) -> Path:
    target = Path(path or DEFAULT_DB)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


@contextmanager
def connection(path: str | None = None):
    conn = sqlite3.connect(db_path(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str | None = None) -> None:
    with connection(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                summary TEXT DEFAULT '',
                url TEXT DEFAULT '',
                source_name TEXT DEFAULT '',
                source_type TEXT DEFAULT 'other',
                published_date TEXT,
                collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                sector TEXT DEFAULT 'General ICP-MS',
                region TEXT DEFAULT 'Global',
                organization TEXT DEFAULT '',
                organization_id TEXT DEFAULT '',
                instrument_vendor TEXT DEFAULT '',
                instrument_model TEXT DEFAULT '',
                signal_kind TEXT DEFAULT 'Research activity',
                product_family TEXT DEFAULT 'General sample introduction',
                credibility REAL DEFAULT 0.5,
                relevance REAL DEFAULT 0.5,
                buying_intent REAL DEFAULT 0.2,
                raw_json TEXT DEFAULT '{}',
                UNIQUE(title, url)
            );
            CREATE INDEX IF NOT EXISTS idx_signals_sector ON signals(sector);
            CREATE INDEX IF NOT EXISTS idx_signals_org ON signals(organization);
            CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(published_date);
            CREATE TABLE IF NOT EXISTS snapshot_state (path TEXT PRIMARY KEY, digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS snapshot_members (
                path TEXT NOT NULL, signal_id INTEGER NOT NULL, active INTEGER NOT NULL,
                PRIMARY KEY(path, signal_id)
            );

            CREATE TABLE IF NOT EXISTS organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                website TEXT DEFAULT '',
                region TEXT DEFAULT 'Global',
                sector TEXT DEFAULT 'General ICP-MS',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS watch_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL UNIQUE,
                active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS signal_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                verdict TEXT NOT NULL,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(signal_id)
            );

            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization TEXT NOT NULL,
                prediction_date TEXT NOT NULL,
                predicted_probability REAL NOT NULL,
                predicted_stage TEXT DEFAULT '',
                outcome_date TEXT,
                outcome_observed INTEGER,
                outcome_type TEXT DEFAULT '',
                evidence_url TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(signals)").fetchall()}
        for name in ("organization_id", "instrument_model", "doi", "response_deadline", "notice_status", "first_seen_at", "last_seen_at", "collector_name"):
            if name not in columns:
                conn.execute(f"ALTER TABLE signals ADD COLUMN {name} TEXT DEFAULT ''")


def insert_signals(rows: Iterable[dict], path: str | None = None) -> tuple[int, int]:
    inserted = skipped = 0
    sql = """
        INSERT OR IGNORE INTO signals (
            title, summary, url, source_name, source_type, published_date,
            sector, region, organization, organization_id, instrument_vendor, instrument_model, signal_kind,
            product_family, credibility, relevance, buying_intent, raw_json,
            doi, response_deadline, notice_status, first_seen_at, last_seen_at, collector_name
        ) VALUES (
            :title, :summary, :url, :source_name, :source_type, :published_date,
            :sector, :region, :organization, :organization_id, :instrument_vendor, :instrument_model, :signal_kind,
            :product_family, :credibility, :relevance, :buying_intent, :raw_json,
            :doi, :response_deadline, :notice_status, :first_seen_at, :last_seen_at, :collector_name
        )
    """
    with connection(path) as conn:
        existing = conn.execute("SELECT * FROM signals").fetchall()
        seen = {evidence_identity(row): row["id"] for row in existing}
        for row in rows:
            def number(name: str, default: float) -> float:
                try:
                    value = row.get(name)
                    return float(value) if value not in (None, "") else default
                except (TypeError, ValueError):
                    return default

            clean = {
                "title": row.get("title") or "Untitled signal",
                "summary": row.get("summary") or "",
                "url": row.get("url") or "",
                "source_name": row.get("source_name") or "",
                "source_type": row.get("source_type") or "other",
                "published_date": row.get("published_date"),
                "sector": row.get("sector") or "General ICP-MS",
                "region": row.get("region") or "Global",
                "organization": row.get("organization") or "",
                "organization_id": row.get("organization_id") or "",
                "instrument_vendor": row.get("instrument_vendor") or "",
                "instrument_model": row.get("instrument_model") or "",
                "signal_kind": row.get("signal_kind") or "Research activity",
                "product_family": row.get("product_family") or "General sample introduction",
                "credibility": number("credibility", 0.5),
                "relevance": number("relevance", 0.5),
                "buying_intent": number("buying_intent", 0.2),
                "raw_json": row.get("raw_json", "{}"),
                "doi": row.get("doi") or "",
                "response_deadline": row.get("response_deadline") or "",
                "notice_status": row.get("notice_status") or "",
                "first_seen_at": row.get("first_seen_at") or "",
                "last_seen_at": row.get("last_seen_at") or "",
                "collector_name": row.get("collector_name") or "",
            }
            if not isinstance(clean["raw_json"], str):
                clean["raw_json"] = json.dumps(clean["raw_json"], default=str)
            identity = evidence_identity(clean)
            if identity in seen:
                # Refresh structured status fields without changing row IDs or reviews.
                for field in ("doi", "response_deadline", "notice_status", "last_seen_at", "collector_name"):
                    if clean[field]:
                        conn.execute(f"UPDATE signals SET {field}=? WHERE id=?", (clean[field], seen[identity]))
                # Fill richer abstracts/identity fields without erasing existing detail.
                old = conn.execute("SELECT * FROM signals WHERE id=?", (seen[identity],)).fetchone()
                for field in ("first_seen_at", "organization", "organization_id"):
                    if clean[field] and not old[field]:
                        conn.execute(f"UPDATE signals SET {field}=? WHERE id=?", (clean[field], seen[identity]))
                if len(clean["summary"]) > len(old["summary"] or ""):
                    conn.execute("UPDATE signals SET summary=? WHERE id=?", (clean["summary"], seen[identity]))
                skipped += 1
                continue
            cursor = conn.execute(sql, clean)
            if cursor.rowcount:
                inserted += 1
                seen[identity] = cursor.lastrowid
            else:
                skipped += 1
    return inserted, skipped


def signals_df(path: str | None = None) -> pd.DataFrame:
    with connection(path) as conn:
        frame = pd.read_sql_query(
            "SELECT * FROM signals WHERE id NOT IN (SELECT signal_id FROM snapshot_members WHERE active=0) ORDER BY COALESCE(published_date, collected_at) DESC", conn
        )
    # Legacy illustrative notes are retained in storage but are not evidence.
    from .seed import starter_signals
    seeds = {(r['title'], r['url']) for r in starter_signals()}
    return frame[~frame.apply(lambda r: (r['title'], r['url']) in seeds, axis=1)].copy()


def add_organization(row: dict, path: str | None = None) -> None:
    with connection(path) as conn:
        conn.execute(
            """
            INSERT INTO organizations(name, website, region, sector, notes)
            VALUES(:name, :website, :region, :sector, :notes)
            ON CONFLICT(name) DO UPDATE SET
                website=excluded.website, region=excluded.region,
                sector=excluded.sector, notes=excluded.notes
            """,
            {
                "name": row["name"],
                "website": row.get("website", ""),
                "region": row.get("region", "Global"),
                "sector": row.get("sector", "General ICP-MS"),
                "notes": row.get("notes", ""),
            },
        )


def organizations_df(path: str | None = None) -> pd.DataFrame:
    with connection(path) as conn:
        return pd.read_sql_query("SELECT * FROM organizations ORDER BY name", conn)


def add_watch_query(query: str, path: str | None = None) -> None:
    with connection(path) as conn:
        conn.execute("INSERT OR IGNORE INTO watch_queries(query) VALUES(?)", (query.strip(),))


def watch_queries(path: str | None = None) -> list[str]:
    with connection(path) as conn:
        rows = conn.execute(
            "SELECT query FROM watch_queries WHERE active=1 ORDER BY created_at"
        ).fetchall()
    return [r["query"] for r in rows]


def save_feedback(signal_id: int, verdict: str, notes: str = "", path: str | None = None) -> None:
    with connection(path) as conn:
        conn.execute(
            """INSERT INTO signal_feedback(signal_id, verdict, notes) VALUES(?, ?, ?)
               ON CONFLICT(signal_id) DO UPDATE SET verdict=excluded.verdict,
               notes=excluded.notes, created_at=CURRENT_TIMESTAMP""",
            (int(signal_id), verdict, notes),
        )


def feedback_df(path: str | None = None) -> pd.DataFrame:
    with connection(path) as conn:
        return pd.read_sql_query("SELECT * FROM signal_feedback ORDER BY created_at DESC", conn)


def add_outcome(row: dict, path: str | None = None) -> None:
    with connection(path) as conn:
        conn.execute(
            """INSERT INTO outcomes(
                organization, prediction_date, predicted_probability, predicted_stage,
                outcome_date, outcome_observed, outcome_type, evidence_url, notes
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                row["organization"], row["prediction_date"], float(row["predicted_probability"]),
                row.get("predicted_stage", ""), row.get("outcome_date"), row.get("outcome_observed"),
                row.get("outcome_type", ""), row.get("evidence_url", ""), row.get("notes", ""),
            ),
        )


def outcomes_df(path: str | None = None) -> pd.DataFrame:
    with connection(path) as conn:
        return pd.read_sql_query("SELECT * FROM outcomes ORDER BY prediction_date DESC", conn)


def save_benchmark_label(row, path=None):
    from .verification import evidence_key, source_fingerprint
    from datetime import datetime, timezone
    payload = dict(row)
    payload['evidence_key'] = evidence_key(row)
    payload['fingerprint'] = source_fingerprint(row)
    payload['reviewed_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    if not str(payload.get('reviewer','')).strip():
        raise ValueError('A reviewer name is required')
    with connection(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS benchmark_labels (evidence_key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        conn.execute("INSERT INTO benchmark_labels VALUES (?,?) ON CONFLICT(evidence_key) DO UPDATE SET payload=excluded.payload", (payload['evidence_key'], json.dumps(payload)))


def benchmark_labels_df(path=None):
    with connection(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS benchmark_labels (evidence_key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        rows = conn.execute("SELECT payload FROM benchmark_labels").fetchall()
    return pd.DataFrame([json.loads(row[0]) for row in rows])


def save_primary_review(signal_id, url, passage, reviewer, path=None):
    from urllib.parse import urlparse
    if urlparse(url).scheme not in {'http','https'} or not urlparse(url).hostname:
        raise ValueError('Enter a valid public source URL')
    if not passage.strip() or not reviewer.strip():
        raise ValueError('A source passage and reviewer are required')
    with connection(path) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS primary_reviews (
            signal_id INTEGER PRIMARY KEY, original_url TEXT, passage TEXT, reviewer TEXT,
            reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        conn.execute('''INSERT INTO primary_reviews(signal_id,original_url,passage,reviewer) VALUES(?,?,?,?)
            ON CONFLICT(signal_id) DO UPDATE SET original_url=excluded.original_url,
            passage=excluded.passage,reviewer=excluded.reviewer,reviewed_at=CURRENT_TIMESTAMP''',
            (int(signal_id),url,passage,reviewer))


def primary_reviews_df(path=None):
    with connection(path) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS primary_reviews (
            signal_id INTEGER PRIMARY KEY, original_url TEXT, passage TEXT, reviewer TEXT,
            reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)''')
        return pd.read_sql_query('SELECT * FROM primary_reviews',conn)
