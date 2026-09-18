from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd


INTENT_WEIGHTS = {
    "Procurement": 1.00,
    "Instrument installation": 0.92,
    "Facility expansion": 0.82,
    "Hiring": 0.72,
    "Funding": 0.68,
    "Operational pain": 0.64,
    "Regulation": 0.55,
    "Market development": 0.45,
    "Research activity": 0.32,
}


def freshness(published_date: str | None, half_life_days: int = 365) -> float:
    if not published_date:
        return 0.45
    try:
        parsed = datetime.fromisoformat(str(published_date)[:10]).date()
    except ValueError:
        return 0.45
    age = max((date.today() - parsed).days, 0)
    return math.exp(-math.log(2) * age / half_life_days)


def signal_score(row: dict | pd.Series) -> float:
    kind = str(row.get("signal_kind", "Research activity"))
    intent = max(float(row.get("buying_intent", 0.2)), INTENT_WEIGHTS.get(kind, 0.3))
    score = (
        0.30 * float(row.get("credibility", 0.5))
        + 0.25 * float(row.get("relevance", 0.5))
        + 0.30 * intent
        + 0.15 * freshness(row.get("published_date"))
    )
    return round(min(max(score * 100, 0), 100), 1)


def score_signals(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.assign(opportunity_score=pd.Series(dtype=float))
    out = df.copy()
    out["opportunity_score"] = out.apply(signal_score, axis=1)
    return out


def organization_scores(signals: pd.DataFrame, manual: pd.DataFrame | None = None) -> pd.DataFrame:
    scored = score_signals(signals)
    scored = scored[scored["organization"].fillna("").str.strip() != ""]
    if scored.empty:
        base = pd.DataFrame(columns=[
            "organization", "sector", "region", "signals", "latest_signal",
            "opportunity_score", "evidence_strength", "top_product",
        ])
    else:
        grouped = []
        for org, group in scored.groupby("organization"):
            scores = sorted(group["opportunity_score"].tolist(), reverse=True)
            combined = 100 * (1 - math.prod(1 - min(s / 100, 0.95) * 0.55 for s in scores[:6]))
            grouped.append({
                "organization": org,
                "sector": group["sector"].mode().iat[0],
                "region": group["region"].mode().iat[0],
                "signals": len(group),
                "latest_signal": group["published_date"].dropna().max() if group["published_date"].notna().any() else "",
                "opportunity_score": round(min(combined, 100), 1),
                "evidence_strength": "High" if len(group) >= 3 else "Medium" if len(group) == 2 else "Early",
                "top_product": group["product_family"].mode().iat[0],
            })
        base = pd.DataFrame(grouped)
    if manual is not None and not manual.empty:
        missing = manual[~manual["name"].isin(base.get("organization", pd.Series(dtype=str)))]
        extra = pd.DataFrame({
            "organization": missing["name"],
            "sector": missing["sector"],
            "region": missing["region"],
            "signals": 0,
            "latest_signal": "",
            "opportunity_score": 10.0,
            "evidence_strength": "Watchlist",
            "top_product": "Unassigned",
        })
        base = pd.concat([base, extra], ignore_index=True)
    return base.sort_values(["opportunity_score", "signals"], ascending=False)

