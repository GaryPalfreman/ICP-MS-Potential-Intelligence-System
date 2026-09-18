from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, datetime, timedelta

import pandas as pd
from .quality import source_relevance, tender_state


STAGE_ORDER = {
    "Research activity": 1,
    "Funding received": 2,
    "Laboratory expansion": 3,
    "ICP-MS hiring": 4,
    "Procurement planning": 5,
    "Active tender": 6,
    "Instrument installation": 7,
    "Consumables opportunity": 8,
}

KIND_TO_STAGE = {
    "Research activity": "Research activity",
    "Funding": "Funding received",
    "Facility expansion": "Laboratory expansion",
    "Hiring": "ICP-MS hiring",
    "Market development": "Procurement planning",
    "Procurement": "Procurement planning",
    "Instrument installation": "Instrument installation",
    "Operational pain": "Consumables opportunity",
    "Regulation": "Procurement planning",
}

VENDOR_MODELS = {
    "Agilent": ["agilent", "7700", "7800", "7850", "7900", "8800", "8900"],
    "Thermo Fisher": ["thermo fisher", "icap q", "icap tq", "element 2", "element xr", "neptune"],
    "PerkinElmer": ["perkinelmer", "nexion", "elans"],
    "Shimadzu": ["shimadzu", "icpms-2030", "icpms-2040", "icpms-2050"],
    "Analytik Jena": ["analytik jena", "plasmaquant"],
    "Nu Instruments": ["nu instruments", "nu plasma", "attom"],
}

PRODUCT_COMPATIBILITY = {
    "Interface cones": {
        "applications": ["high matrix", "sensitivity", "maintenance", "downtime", "cone", "interface"],
        "reason": "Interface wear, sensitivity stability or high-matrix operation",
    },
    "Nebulizers": {
        "applications": ["nebulizer", "nebuliser", "aerosol", "uptake", "blockage", "low flow"],
        "reason": "Sample aerosol generation, low-flow analysis or blockage reduction",
    },
    "Spray chambers": {
        "applications": ["washout", "carryover", "spray chamber", "temperature", "cyclonic"],
        "reason": "Washout, carryover or aerosol conditioning requirements",
    },
    "Torches & injectors": {
        "applications": ["torch", "injector", "plasma", "high matrix", "organics"],
        "reason": "Plasma robustness or matrix-specific sample introduction",
    },
    "Autosampler & tubing": {
        "applications": ["autosampler", "automation", "throughput", "probe", "tubing"],
        "reason": "Automation, throughput or liquid-path replacement demand",
    },
    "High-efficiency introduction": {
        "applications": ["ultra trace", "ultratrace", "semiconductor", "microvolume", "low sample"],
        "reason": "Ultra-trace sensitivity or restricted sample volume",
    },
    "Laser ablation interfaces": {
        "applications": ["laser ablation", "la-icp", "geochronology", "solid sampling"],
        "reason": "Direct solid-sample or laser-ablation workflows",
    },
    "ICP-TOF / mass cytometry": {
        "applications": ["mass cytometry", "cytof", "single cell", "icp-tof", "tof-icp"],
        "reason": "Single-cell, mass-cytometry or time-of-flight workflows",
    },
}


def canonical_organization(value: str | None) -> str:
    """Conservatively normalize names without merging distinct legal entities."""
    if not value:
        return ""
    name = re.sub(r"\s+", " ", str(value)).strip(" ,;.-")
    name = re.sub(r"^(the)\s+", "", name, flags=re.I)
    suffixes = r"\s+(?:pty\.?\s*ltd\.?|limited|inc\.?|llc|corp\.?)$"
    name = re.sub(suffixes, "", name, flags=re.I).strip()
    return name


def sales_stage(row: dict | pd.Series) -> str:
    text = " ".join(str(row.get(key, "")) for key in ("title", "summary", "signal_kind")).lower()
    if row.get("signal_kind") == "Procurement" or any(term in text for term in ("tender", "request for proposal", "request for tender", "rfp")):
        return "Active tender" if tender_state(row) == "Open" else "Procurement planning"
    if any(term in text for term in (
        "installed", "installation", "commissioned", "commissions", "new instrument",
        "now operational", "invests in new", "new equipment",
    )):
        return "Instrument installation"
    return KIND_TO_STAGE.get(str(row.get("signal_kind", "")), "Research activity")


def detect_vendor_and_model(text: str) -> tuple[str, str]:
    lowered = (text or "").lower()
    for vendor, terms in VENDOR_MODELS.items():
        for term in terms:
            if term in lowered:
                model = term.upper() if any(char.isdigit() for char in term) else ""
                return vendor, model
    return "", ""


def product_fit(row: dict | pd.Series) -> tuple[str, float, str]:
    text = " ".join(str(row.get(key, "")) for key in ("title", "summary")).lower()
    assigned = str(row.get("product_family", "General sample introduction"))
    scores = {
        family: sum(term in text for term in details["applications"])
        for family, details in PRODUCT_COMPATIBILITY.items()
    }
    best = max(scores, key=scores.get) if scores else assigned
    if scores.get(best, 0) == 0 and assigned in PRODUCT_COMPATIBILITY:
        best = assigned
        confidence = 0.58
    elif scores.get(best, 0) == 0:
        return assigned, 0.35, "General ICP-MS relevance; exact component fit requires verification"
    else:
        confidence = min(0.55 + 0.12 * scores[best], 0.91)
    return best, confidence, PRODUCT_COMPATIBILITY.get(best, {}).get("reason", "Verify technical fit")


def evidence_confidence(row: dict | pd.Series, corroboration: int = 1) -> float:
    credibility = float(row.get("credibility", 0.5) or 0.5)
    completeness = sum(bool(str(row.get(key, "") or "").strip()) for key in ("url", "published_date", "organization")) / 3
    directness = {
        "Procurement": 1.0,
        "Instrument installation": 0.94,
        "Facility expansion": 0.82,
        "Hiring": 0.72,
        "Funding": 0.72,
        "Regulation": 0.65,
        "Operational pain": 0.62,
        "Market development": 0.5,
        "Research activity": 0.38,
    }.get(str(row.get("signal_kind", "")), 0.4)
    if row.get("signal_kind") == "Procurement" and tender_state(row) != "Open":
        directness = .4
    support = min(math.log2(max(corroboration, 1) + 1) / 3, 1)
    confidence = 100 * (0.38 * credibility + 0.24 * completeness + 0.28 * directness + 0.10 * support)
    if source_relevance(f"{row.get('title', '')} {row.get('summary', '')}") < .8:
        confidence = min(confidence, 60)
    return round(confidence, 1)


def enrich_signals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    out = df.copy()
    defaults = {
        "organization": "", "title": "", "summary": "", "signal_kind": "Research activity",
        "product_family": "General sample introduction", "source_name": "Unknown",
        "url": "", "published_date": None, "credibility": 0.5,
    }
    for column, default in defaults.items():
        if column not in out.columns:
            out[column] = default
    out["organization"] = out["organization"].fillna("").map(canonical_organization)
    out["relevance_basis"] = out.apply(
        lambda row: "Explicit ICP evidence" if source_relevance(f"{row['title']} {row['summary']}") >= .8
        else "Needs source verification", axis=1)
    out["tender_status"] = out.apply(lambda row: tender_state(row) if row["signal_kind"] == "Procurement" else "Not a tender", axis=1)
    detected = out.apply(lambda row: detect_vendor_and_model(f"{row.get('title', '')} {row.get('summary', '')}"), axis=1)
    if "instrument_vendor" not in out.columns:
        out["instrument_vendor"] = ""
    if "instrument_model" not in out.columns:
        out["instrument_model"] = ""
    out["instrument_vendor"] = [existing or item[0] for existing, item in zip(out["instrument_vendor"].fillna(""), detected)]
    out["instrument_model"] = [existing or item[1] for existing, item in zip(out["instrument_model"].fillna(""), detected)]
    counts = out[out["organization"] != ""].groupby("organization").size().to_dict()
    out["sales_stage"] = out.apply(sales_stage, axis=1)
    out["stage_rank"] = out["sales_stage"].map(STAGE_ORDER).fillna(1).astype(int)
    fits = out.apply(product_fit, axis=1)
    out["recommended_product"] = [item[0] for item in fits]
    out["product_fit_confidence"] = [round(item[1] * 100, 1) for item in fits]
    out["product_fit_reason"] = [item[2] for item in fits]
    out["evidence_confidence"] = out.apply(
        lambda row: evidence_confidence(row, counts.get(row.get("organization", ""), 1)), axis=1
    )
    return out


def trend_acceleration(df: pd.DataFrame, today: date | None = None) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["sector", "last_90_days", "previous_90_days", "acceleration", "momentum"])
    current = today or date.today()
    work = df.copy()
    work["_date"] = pd.to_datetime(work["published_date"], errors="coerce").dt.date
    recent_start = current - timedelta(days=90)
    prior_start = current - timedelta(days=180)
    rows = []
    for sector, group in work.groupby("sector"):
        recent = int(group["_date"].apply(lambda value: bool(pd.notna(value) and recent_start <= value <= current)).sum())
        prior = int(group["_date"].apply(lambda value: bool(pd.notna(value) and prior_start <= value < recent_start)).sum())
        acceleration = (recent + 2) / (prior + 2)
        momentum = "Accelerating" if recent >= 3 and acceleration >= 1.35 else "Cooling" if prior >= 3 and acceleration <= 0.74 else "Stable"
        rows.append({"sector": sector, "last_90_days": recent, "previous_90_days": prior, "acceleration": round(acceleration, 2), "momentum": momentum})
    return pd.DataFrame(rows).sort_values(["acceleration", "last_90_days"], ascending=False)


def daily_briefing(df: pd.DataFrame, days: int = 7) -> dict:
    if df.empty:
        return {"new_signals": 0, "high_confidence": 0, "active_tenders": 0, "rising_organizations": [], "top_sectors": []}
    enriched = enrich_signals(df)
    cutoff = date.today() - timedelta(days=days)
    dates = pd.to_datetime(enriched["published_date"], errors="coerce").dt.date
    recent = enriched[dates.apply(lambda value: bool(pd.notna(value) and cutoff <= value <= date.today()))]
    organizations = recent[recent["organization"] != ""]["organization"].value_counts().head(5).index.tolist()
    sectors = recent["sector"].value_counts().head(5).index.tolist()
    return {
        "new_signals": len(recent),
        "high_confidence": int((recent["evidence_confidence"] >= 75).sum()),
        "active_tenders": int((recent["sales_stage"] == "Active tender").sum()),
        "rising_organizations": organizations,
        "top_sectors": sectors,
    }


def calibration_metrics(outcomes: pd.DataFrame) -> dict:
    if outcomes.empty:
        return {"evaluated": 0, "brier_score": None, "accuracy": None}
    work = outcomes.dropna(subset=["predicted_probability", "outcome_observed"]).copy()
    if work.empty:
        return {"evaluated": 0, "brier_score": None, "accuracy": None}
    predicted = work["predicted_probability"].astype(float).clip(0, 100) / 100
    actual = work["outcome_observed"].astype(int).clip(0, 1)
    brier = float(((predicted - actual) ** 2).mean())
    accuracy = float(((predicted >= 0.5).astype(int) == actual).mean())
    return {"evaluated": len(work), "brier_score": round(brier, 3), "accuracy": round(accuracy * 100, 1)}
