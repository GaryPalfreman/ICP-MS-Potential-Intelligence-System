from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd


def intelligence_report(
    signals: pd.DataFrame,
    organizations: pd.DataFrame,
    sectors: pd.DataFrame,
    products: pd.DataFrame,
) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# ICP-MS Potential Intelligence Report",
        "",
        f"Generated: {generated}",
        "",
        "> Public-data market intelligence. Opportunity indices are scenario outputs, not revenue forecasts or purchasing guarantees.",
        "",
        "## Executive summary",
        "",
    ]
    if not sectors.empty:
        top = sectors.iloc[0]
        lines.append(
            f"The highest current sector opportunity is **{top['Sector']}**, "
            f"with an expected {int(top['Expected index'])} index against a 100 baseline."
        )
    lines.extend(["", "## Sector outlook", "", sectors.to_markdown(index=False), "", "## Product-family outlook", "", products.to_markdown(index=False)])
    if not organizations.empty:
        lines.extend(["", "## Potential organisations", "", organizations.head(30).to_markdown(index=False)])
    lines.extend(["", "## Evidence register", ""])
    for _, row in signals.head(50).iterrows():
        org = f" — {row['organization']}" if row.get("organization") else ""
        lines.append(
            f"- **{row['title']}**{org}  \n"
            f"  {row.get('source_name', '')} | {row.get('published_date', '')} | "
            f"[Source]({row.get('url', '')})"
        )
    lines.extend([
        "",
        "## Interpretation rules",
        "",
        "- Facts are retained with their original source URLs.",
        "- Organisation scores combine multiple public signals; they do not confirm a purchasing intention.",
        "- Simulation ranges express model uncertainty, not statistical confidence in future revenue.",
        "- Verify every priority organisation before commercial contact.",
    ])
    return "\n".join(lines)


def mirofish_seed_pack(signals: pd.DataFrame, sectors: pd.DataFrame, products: pd.DataFrame) -> str:
    payload = {
        "project": "ICP-MS Potential Intelligence System",
        "purpose": "Simulate public-market reactions and purchasing drivers in the ICP-MS ecosystem.",
        "prediction_question": (
            "Over the next 12, 24 and 36 months, which public developments are most likely "
            "to increase demand for ICP-MS sample-introduction and interface product families, "
            "in which sectors and regions, and what observable signals precede purchasing?"
        ),
        "agent_archetypes": [
            "ICP-MS laboratory manager", "analytical scientist", "procurement manager",
            "quality and regulatory manager", "instrument manufacturer product manager",
            "laboratory distributor", "university principal investigator",
            "semiconductor contamination-control scientist", "battery materials analyst",
            "environmental laboratory manager", "pharmaceutical elemental-impurities lead",
        ],
        "simulation_rules": [
            "Treat evidence as public signals, not confirmed buying intent.",
            "Separate observed facts, agent assumptions and generated scenarios.",
            "Produce conservative, expected and accelerated cases.",
            "Cite the source URL behind every factual claim.",
            "Do not infer personal characteristics or target individual people.",
        ],
        "sector_outlook": sectors.to_dict(orient="records"),
        "product_outlook": products.to_dict(orient="records"),
        "evidence": signals.head(200).to_dict(orient="records"),
    }
    return json.dumps(payload, indent=2, default=str)

