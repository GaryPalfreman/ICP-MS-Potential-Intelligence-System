from datetime import date

import pandas as pd

from icpms_intel.scoring import freshness, organization_scores, signal_score


def test_fresh_signal_scores_higher_than_old_signal():
    assert freshness(date.today().isoformat()) > freshness("2020-01-01")


def test_procurement_signal_has_strong_score():
    score = signal_score({
        "signal_kind": "Procurement", "credibility": .92, "relevance": .9,
        "buying_intent": .95, "published_date": date.today().isoformat(),
    })
    assert score >= 85


def test_corroboration_increases_organisation_score():
    base = {
        "organization": "Example Laboratory", "sector": "Environmental & Water",
        "region": "Australia", "product_family": "Nebulizers",
        "signal_kind": "Research activity", "credibility": .8, "relevance": .8,
        "buying_intent": .4, "published_date": date.today().isoformat(),
    }
    one = organization_scores(pd.DataFrame([base]))
    three = organization_scores(pd.DataFrame([base, {**base, "signal_kind": "Hiring"}, {**base, "signal_kind": "Funding"}]))
    assert three.iloc[0]["opportunity_score"] > one.iloc[0]["opportunity_score"]

