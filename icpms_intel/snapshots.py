from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .database import insert_signals


SNAPSHOT_PATH = Path("data/public_signals.csv")
STATUS_PATH = Path("data/update_status.json")


def load_public_snapshot(path: Path = SNAPSHOT_PATH, db: str | None = None) -> tuple[int, int]:
    """Load the repository-backed public-data snapshot into the runtime database."""
    if not path.exists() or path.stat().st_size == 0:
        return 0, 0
    rows = pd.read_csv(path).where(pd.notna, None).to_dict(orient="records")
    return insert_signals(rows, db)


def read_update_status(path: Path = STATUS_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
