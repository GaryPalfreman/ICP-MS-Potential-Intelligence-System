from datetime import date, timedelta

import pandas as pd

from icpms_intel.intelligence import (
    calibration_metrics,
    canonical_organization,
    enrich_signals,
    sales_stage,
    trend_acceleration,
)


def test_entity_normalisation_is_conservative():
    assert canonical_organization("The Example University  ") == "Example University"
    assert canonical_organization("Example Labs Pty Ltd") == "Example Labs"


def test_direct_tender_reaches_active_stage():
    row = {"title": "Request for tender for an ICP-MS system", "signal_kind": "Procurement"}
    assert sales_stage(row) == "Active tender"


def test_signal_enrichment_explains_product_fit():
    frame = pd.DataFrame([{
        "title": "Laboratory needs faster washout and lower carryover",
        "summary": "New ICP-MS workflow", "product_family": "Spray chambers",
        "signal_kind": "Operational pain", "organization": "Example Lab",
        "source_name": "Public source", "url": "https://example.org",
        "published_date": date.today().isoformat(), "credibility": .8,
    }])
    enriched = enrich_signals(frame)
    assert enriched.iloc[0]["recommended_product"] == "Spray chambers"
    assert enriched.iloc[0]["evidence_confidence"] > 50


def test_acceleration_detects_growth():
    today = date.today()
    dates = [today - timedelta(days=i) for i in (5, 10, 20, 30, 40)] + [today - timedelta(days=120)]
    frame = pd.DataFrame({"sector": ["Environmental & Water"] * len(dates), "published_date": [d.isoformat() for d in dates]})
    result = trend_acceleration(frame, today)
    assert result.iloc[0]["momentum"] == "Accelerating"


def test_calibration_uses_brier_score():
    outcomes = pd.DataFrame({"predicted_probability": [80, 20], "outcome_observed": [1, 0]})
    result = calibration_metrics(outcomes)
    assert result == {"evaluated": 2, "brier_score": 0.04, "accuracy": 100.0}
