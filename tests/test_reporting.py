from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone

import pandas as pd

from icpms_intel.reporting import mirofish_archive_bundle, mirofish_seed_document


NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


def frames():
    signals = pd.DataFrame([{
        "title": "New trace-metals laboratory",
        "organization": "Example Institute",
        "source_name": "Public register",
        "published_date": "2026-09-01",
        "summary": "A public evidence record.",
        "url": "https://example.org/evidence",
    }])
    sectors = pd.DataFrame([{"Sector": "Environmental", "Expected index": 112}])
    products = pd.DataFrame([{"Product family": "Cones", "Expected opportunity index": 108}])
    return signals, sectors, products


def test_mirofish_seed_is_uploadable_markdown():
    signals, sectors, products = frames()
    seed = mirofish_seed_document(signals, sectors, products, "Test this market.", NOW)

    assert seed.startswith("# ICP-MS Market Simulation Seed")
    assert "Test this market." in seed
    assert "https://example.org/evidence" in seed
    assert "2026-09-18 12:00 UTC" in seed


def test_mirofish_archive_contains_replay_inputs_and_checksums():
    signals, sectors, products = frames()
    archive_bytes = mirofish_archive_bundle(
        signals,
        sectors,
        products,
        "Test this market.",
        {"predictions": pd.DataFrame([{"organization": "Example Institute"}])},
        NOW,
    )

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = set(archive.namelist())
        assert "mirofish/ICP-MS_MiroFish_Seed.md" in names
        assert "mirofish/simulation_requirement.txt" in names
        assert "snapshots/evidence.csv" in names
        assert "history/predictions.csv" in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["evidence_rows"] == 1
        assert "sha256" in manifest["files"]["snapshots/evidence.csv"]
