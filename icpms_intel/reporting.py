from __future__ import annotations

import json
import hashlib
import io
import zipfile
from datetime import datetime, timezone

import pandas as pd


def _markdown_table(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No records available."
    clean = frame.fillna("").astype(str)
    headers = [str(column).replace("|", "\\|") for column in clean.columns]
    rows = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for values in clean.itertuples(index=False, name=None):
        rows.append("| " + " | ".join(str(value).replace("|", "\\|").replace("\n", " ") for value in values) + " |")
    return "\n".join(rows)


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
    lines.extend(["", "## Sector outlook", "", _markdown_table(sectors), "", "## Product-family outlook", "", _markdown_table(products)])
    if not organizations.empty:
        lines.extend(["", "## Potential organisations", "", _markdown_table(organizations.head(30))])
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


DEFAULT_MIROFISH_QUESTION = (
    "Over the next 12, 24 and 36 months, which public developments are most likely "
    "to increase demand for ICP-MS sample-introduction and interface product families, "
    "in which sectors and regions, and what observable signals precede purchasing?"
)


def mirofish_seed_document(
    signals: pd.DataFrame,
    sectors: pd.DataFrame,
    products: pd.DataFrame,
    prediction_question: str = DEFAULT_MIROFISH_QUESTION,
    generated_at: datetime | None = None,
) -> str:
    """Build a Markdown seed document accepted by the official MiroFish uploader."""
    generated_at = generated_at or datetime.now(timezone.utc)
    generated = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    evidence_columns = [
        column for column in (
            "title", "organization", "source_name", "published_date", "signal_type",
            "sector", "product_family", "summary", "url",
        ) if column in signals.columns
    ]
    evidence = signals.loc[:, evidence_columns].head(200).copy()

    return "\n".join([
        "# ICP-MS Market Simulation Seed",
        "",
        f"Data snapshot generated: {generated}",
        "",
        "## Simulation requirement",
        "",
        prediction_question.strip(),
        "",
        "## Evidence-use rules",
        "",
        "- Treat the evidence below as public signals, not confirmed buying intent.",
        "- Keep observed facts, agent assumptions and generated scenarios separate.",
        "- Cite the source URL for factual claims and retain the source date.",
        "- Produce conservative, expected and accelerated cases.",
        "- Do not infer personal characteristics or target individual people.",
        "- Flag conflicting, stale or missing evidence instead of filling gaps with invented facts.",
        "",
        "## Suggested agent archetypes",
        "",
        "- ICP-MS laboratory manager and analytical scientist",
        "- Procurement manager and quality/regulatory manager",
        "- Instrument-manufacturer product manager and laboratory distributor",
        "- University principal investigator",
        "- Semiconductor contamination-control scientist",
        "- Battery-materials analyst",
        "- Environmental laboratory manager",
        "- Pharmaceutical elemental-impurities lead",
        "",
        "## Sector outlook",
        "",
        _markdown_table(sectors),
        "",
        "## Product-family outlook",
        "",
        _markdown_table(products),
        "",
        "## Evidence snapshot (maximum 200 records)",
        "",
        _markdown_table(evidence),
        "",
        "## Interpretation boundary",
        "",
        "This document is a dated simulation input. Scenario output is not a revenue forecast, "
        "purchasing guarantee, or statement of any organisation's intent.",
    ])


def mirofish_archive_bundle(
    signals: pd.DataFrame,
    sectors: pd.DataFrame,
    products: pd.DataFrame,
    prediction_question: str = DEFAULT_MIROFISH_QUESTION,
    histories: dict[str, pd.DataFrame] | None = None,
    generated_at: datetime | None = None,
) -> bytes:
    """Create a portable, checksummed archive for replaying a MiroFish run later."""
    generated_at = generated_at or datetime.now(timezone.utc)
    seed = mirofish_seed_document(
        signals, sectors, products, prediction_question, generated_at
    )
    files: dict[str, bytes] = {
        "mirofish/ICP-MS_MiroFish_Seed.md": seed.encode("utf-8"),
        "mirofish/simulation_requirement.txt": prediction_question.strip().encode("utf-8"),
        "snapshots/evidence.csv": signals.to_csv(index=False).encode("utf-8"),
        "snapshots/sector_outlook.csv": sectors.to_csv(index=False).encode("utf-8"),
        "snapshots/product_outlook.csv": products.to_csv(index=False).encode("utf-8"),
    }
    for name, frame in (histories or {}).items():
        safe_name = "".join(character for character in name if character.isalnum() or character in "-_")
        if safe_name:
            files[f"history/{safe_name}.csv"] = frame.to_csv(index=False).encode("utf-8")

    manifest = {
        "schema_version": 1,
        "generated_at": generated_at.astimezone(timezone.utc).isoformat(),
        "simulation_requirement": prediction_question.strip(),
        "evidence_rows": len(signals),
        "files": {
            name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
            for name, content in sorted(files.items())
        },
        "instructions": (
            "Upload mirofish/ICP-MS_MiroFish_Seed.md to MiroFish and use "
            "mirofish/simulation_requirement.txt as the simulation requirement."
        ),
    }
    files["manifest.json"] = json.dumps(manifest, indent=2).encode("utf-8")

    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    return output.getvalue()
