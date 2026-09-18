from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .taxonomy import PRODUCT_FAMILIES, SECTORS


SECTOR_GROWTH = {
    "Battery & Critical Minerals": 0.105,
    "Semiconductor & High Purity": 0.095,
    "Environmental & Water": 0.060,
    "Pharma & Biopharma": 0.070,
    "Food & Agriculture": 0.045,
    "Clinical & Life Science": 0.085,
    "Research & Academia": 0.035,
    "Commercial Testing": 0.060,
    "General ICP-MS": 0.040,
}

PRODUCT_SECTOR_FIT = {
    "Interface cones": {"Semiconductor & High Purity": 1.25, "Battery & Critical Minerals": 1.15, "Environmental & Water": 1.08},
    "Nebulizers": {"Battery & Critical Minerals": 1.22, "Commercial Testing": 1.18, "Environmental & Water": 1.12},
    "Spray chambers": {"Commercial Testing": 1.28, "Environmental & Water": 1.20, "Food & Agriculture": 1.12},
    "Torches & injectors": {"Battery & Critical Minerals": 1.25, "Commercial Testing": 1.15, "Semiconductor & High Purity": 1.10},
    "Autosampler & tubing": {"Commercial Testing": 1.30, "Environmental & Water": 1.22, "Food & Agriculture": 1.12},
    "High-efficiency introduction": {"Clinical & Life Science": 1.30, "Pharma & Biopharma": 1.20, "Semiconductor & High Purity": 1.16},
    "Laser ablation interfaces": {"Research & Academia": 1.30, "Battery & Critical Minerals": 1.18},
    "ICP-TOF / mass cytometry": {"Clinical & Life Science": 1.38, "Research & Academia": 1.18},
    "General sample introduction": {},
}


@dataclass
class ScenarioInputs:
    horizon_years: int = 2
    macro_factor: float = 1.0
    regulation_factor: float = 1.0
    technology_factor: float = 1.0
    seed: int = 42
    simulations: int = 5000


def run_scenario(signals: pd.DataFrame, inputs: ScenarioInputs) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(inputs.seed)
    counts = signals["sector"].value_counts().to_dict() if not signals.empty else {}
    sector_rows = []
    sector_draws: dict[str, np.ndarray] = {}
    for sector in list(SECTORS) + ["General ICP-MS"]:
        evidence = counts.get(sector, 0)
        evidence_factor = min(1 + np.log1p(evidence) / 12, 1.35)
        base = SECTOR_GROWTH.get(sector, 0.04)
        mean = base * inputs.macro_factor * inputs.regulation_factor * inputs.technology_factor * evidence_factor
        annual = rng.normal(mean, max(0.025, base * 0.45), inputs.simulations)
        annual = np.clip(annual, -0.20, 0.45)
        index = 100 * np.power(1 + annual, inputs.horizon_years)
        sector_draws[sector] = index
        sector_rows.append({
            "Sector": sector,
            "Evidence signals": evidence,
            "Expected index": round(float(np.mean(index)), 1),
            "Low (10%)": round(float(np.quantile(index, 0.10)), 1),
            "High (90%)": round(float(np.quantile(index, 0.90)), 1),
            "Positive-growth probability": round(float(np.mean(index > 100) * 100), 1),
        })
    sector_df = pd.DataFrame(sector_rows).sort_values("Expected index", ascending=False)

    product_rows = []
    for product in list(PRODUCT_FAMILIES) + ["General sample introduction"]:
        fits = PRODUCT_SECTOR_FIT.get(product, {})
        weighted = []
        for sector, draws in sector_draws.items():
            fit = fits.get(sector, 1.0)
            evidence_weight = 1 + min(counts.get(sector, 0), 20) / 20
            weighted.append(draws * fit * evidence_weight)
        combined = np.mean(weighted, axis=0)
        combined = 100 + (combined - 100) * 0.62
        product_rows.append({
            "Product family": product,
            "Expected opportunity index": round(float(np.mean(combined)), 1),
            "Low (10%)": round(float(np.quantile(combined, 0.10)), 1),
            "High (90%)": round(float(np.quantile(combined, 0.90)), 1),
        })
    product_df = pd.DataFrame(product_rows).sort_values("Expected opportunity index", ascending=False)
    return sector_df, product_df


def scenario_label(value: float) -> str:
    if value < 0.9:
        return "Constrained"
    if value > 1.1:
        return "Accelerated"
    return "Expected"

