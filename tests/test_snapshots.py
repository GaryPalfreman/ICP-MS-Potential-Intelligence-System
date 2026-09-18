import json

import pandas as pd

from icpms_intel.database import init_db, signals_df
from icpms_intel.snapshots import load_public_snapshot, read_update_status


def test_snapshot_loads_and_deduplicates(tmp_path):
    snapshot = tmp_path / "signals.csv"
    db = str(tmp_path / "test.db")
    pd.DataFrame([{
        "title": "Test ICP-MS signal", "url": "https://example.com/evidence",
        "source_name": "Test source", "sector": "General ICP-MS",
        "signal_kind": "Research activity",
    }]).to_csv(snapshot, index=False)
    init_db(db)
    assert load_public_snapshot(snapshot, db) == (1, 0)
    assert load_public_snapshot(snapshot, db) == (0, 1)
    assert len(signals_df(db)) == 1


def test_update_status_is_readable(tmp_path):
    status_file = tmp_path / "status.json"
    status_file.write_text(json.dumps({"successful": True}), encoding="utf-8")
    assert read_update_status(status_file)["successful"] is True
