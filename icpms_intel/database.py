from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

import pandas as pd


DEFAULT_DB = os.getenv("ICPMS_DB_PATH", "data/intelligence.db")


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
                instrument_vendor TEXT DEFAULT '',
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
            """
        )


def insert_signals(rows: Iterable[dict], path: str | None = None) -> tuple[int, int]:
    inserted = skipped = 0
    sql = """
        INSERT OR IGNORE INTO signals (
            title, summary, url, source_name, source_type, published_date,
            sector, region, organization, instrument_vendor, signal_kind,
            product_family, credibility, relevance, buying_intent, raw_json
        ) VALUES (
            :title, :summary, :url, :source_name, :source_type, :published_date,
            :sector, :region, :organization, :instrument_vendor, :signal_kind,
            :product_family, :credibility, :relevance, :buying_intent, :raw_json
        )
    """
    with connection(path) as conn:
        for row in rows:
            clean = {
                "title": row.get("title", "Untitled signal"),
                "summary": row.get("summary", ""),
                "url": row.get("url", ""),
                "source_name": row.get("source_name", ""),
                "source_type": row.get("source_type", "other"),
                "published_date": row.get("published_date"),
                "sector": row.get("sector", "General ICP-MS"),
                "region": row.get("region", "Global"),
                "organization": row.get("organization", ""),
                "instrument_vendor": row.get("instrument_vendor", ""),
                "signal_kind": row.get("signal_kind", "Research activity"),
                "product_family": row.get("product_family", "General sample introduction"),
                "credibility": float(row.get("credibility", 0.5)),
                "relevance": float(row.get("relevance", 0.5)),
                "buying_intent": float(row.get("buying_intent", 0.2)),
                "raw_json": row.get("raw_json", "{}"),
            }
            if not isinstance(clean["raw_json"], str):
                clean["raw_json"] = json.dumps(clean["raw_json"], default=str)
            cursor = conn.execute(sql, clean)
            if cursor.rowcount:
                inserted += 1
            else:
                skipped += 1
    return inserted, skipped


def signals_df(path: str | None = None) -> pd.DataFrame:
    with connection(path) as conn:
        return pd.read_sql_query(
            "SELECT * FROM signals ORDER BY COALESCE(published_date, collected_at) DESC", conn
        )


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

