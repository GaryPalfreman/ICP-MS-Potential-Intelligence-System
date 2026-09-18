from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .database import evidence_identity, insert_signals


SNAPSHOT_PATH = Path("data/public_signals.csv")
STATUS_PATH = Path("data/update_status.json")


def deduplicate_snapshot(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Keep the most complete representation of each evidence item."""
    if frame.empty:
        return frame.copy(), 0
    work = frame.copy()
    work["_identity"] = work.apply(lambda row: evidence_identity(row.to_dict()), axis=1)

    def column(name: str, default="") -> pd.Series:
        return work[name] if name in work.columns else pd.Series(default, index=work.index)

    url = column("url").fillna("").astype(str)
    org = column("organization").fillna("").astype(str)
    summary = column("summary").fillna("").astype(str)
    credibility = pd.to_numeric(column("credibility", 0), errors="coerce").fillna(0)
    work["_quality"] = (
        url.str.startswith(("http://", "https://")).astype(int) * 4
        + org.str.strip().ne("").astype(int) * 2
        + summary.str.len().clip(upper=1000) / 1000
        + credibility
    )
    work["_published"] = pd.to_datetime(column("published_date"), errors="coerce")
    work = work.sort_values(["_quality", "_published"], ascending=False, na_position="last")
    before = len(work)
    work = work.drop_duplicates("_identity", keep="first")
    removed = before - len(work)
    return work.drop(columns=["_identity", "_quality", "_published"]), removed


def load_public_snapshot(path: Path = SNAPSHOT_PATH, db: str | None = None) -> tuple[int, int]:
    """Load the repository-backed public-data snapshot into the runtime database."""
    if not path.exists() or path.stat().st_size == 0:
        return 0, 0
    frame, _ = deduplicate_snapshot(pd.read_csv(path))
    required = {"title", "url", "source_name", "sector", "signal_kind"}
    if not required.issubset(frame.columns):
        return 0, 0
    rows = frame.where(pd.notna, None).to_dict(orient="records")
    return insert_signals(rows, db)


def read_update_status(path: Path = STATUS_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
