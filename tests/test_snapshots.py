import json

import pandas as pd

from icpms_intel.database import init_db, insert_signals, signals_df
from icpms_intel.snapshots import deduplicate_snapshot, load_public_snapshot, read_update_status


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


def test_missing_urls_do_not_bypass_deduplication(tmp_path):
    db = str(tmp_path / "test.db")
    init_db(db)
    rows = [
        {"title": "Same paper", "url": None, "source_type": "journal"},
        {"title": "Same paper", "url": None, "source_type": "journal"},
    ]
    assert insert_signals(rows, db) == (1, 1)
    assert len(signals_df(db)) == 1


def test_journal_deduplication_prefers_more_complete_record():
    frame = pd.DataFrame([
        {"title": "An ICP-MS Study", "url": "https://doi.org/10.1/example", "source_type": "journal", "summary": "", "credibility": .8},
        {"title": "An ICP–MS Study", "url": "https://doi.org/10.1/example", "source_type": "journal", "summary": "Full abstract", "credibility": .8},
    ])
    result, removed = deduplicate_snapshot(frame)
    assert removed == 1
    assert result.iloc[0]["url"] == "https://doi.org/10.1/example"


def test_distinct_non_journal_urls_are_preserved():
    frame = pd.DataFrame([
        {"title": "Annual instrument award", "url": "https://example.com/2025", "source_type": "grant"},
        {"title": "Annual instrument award", "url": "https://example.com/2026", "source_type": "grant"},
    ])
    result, removed = deduplicate_snapshot(frame)
    assert removed == 0
    assert len(result) == 2
