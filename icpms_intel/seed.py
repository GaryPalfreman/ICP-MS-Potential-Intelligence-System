from __future__ import annotations

from datetime import date, timedelta

from .database import add_watch_query, insert_signals


def starter_signals() -> list[dict]:
    today = date.today()
    return [
        {
            "title": "Battery manufacturing quality control increases multielement screening demand",
            "summary": "Public instrument-vendor application material highlights ICP-MS multielement screening for quality control in battery manufacturing.",
            "url": "https://www.agilent.com/en/product/atomic-spectroscopy/inductively-coupled-plasma-mass-spectrometry-icp-ms",
            "source_name": "Instrument manufacturer application hub",
            "source_type": "manufacturer",
            "published_date": (today - timedelta(days=80)).isoformat(),
            "sector": "Battery & Critical Minerals",
            "region": "Global",
            "organization": "",
            "signal_kind": "Market development",
            "product_family": "Torches & injectors",
            "credibility": 0.78, "relevance": 0.91, "buying_intent": 0.55,
        },
        {
            "title": "ICP-MS interface cone selection and maintenance receives renewed technical focus",
            "summary": "A major instrument manufacturer published updated technical guidance on cone selection, maintenance, sensitivity, stability and reliability.",
            "url": "https://www.agilent.com/en/product/atomic-spectroscopy/inductively-coupled-plasma-mass-spectrometry-icp-ms",
            "source_name": "Instrument manufacturer technical resource",
            "source_type": "manufacturer",
            "published_date": "2025-08-14",
            "sector": "General ICP-MS",
            "region": "Global",
            "organization": "",
            "signal_kind": "Operational pain",
            "product_family": "Interface cones",
            "credibility": 0.78, "relevance": 0.94, "buying_intent": 0.62,
        },
        {
            "title": "Semiconductor ICP-MS resources emphasize ultra-trace contamination control",
            "summary": "Public application resources continue to position ICP-MS and ICP-QQQ for semiconductor and high-purity chemical analysis.",
            "url": "https://www.agilent.com/en/product/atomic-spectroscopy/inductively-coupled-plasma-mass-spectrometry-icp-ms",
            "source_name": "Instrument manufacturer semiconductor resources",
            "source_type": "manufacturer",
            "published_date": (today - timedelta(days=120)).isoformat(),
            "sector": "Semiconductor & High Purity",
            "region": "Global",
            "organization": "",
            "signal_kind": "Market development",
            "product_family": "High-efficiency introduction",
            "credibility": 0.78, "relevance": 0.90, "buying_intent": 0.56,
        },
        {
            "title": "Elemental impurity analysis remains a regulated pharmaceutical requirement",
            "summary": "Risk-based control of elemental impurities continues to support demand for validated trace-element analysis.",
            "url": "https://www.ich.org/page/quality-guidelines",
            "source_name": "ICH Quality Guidelines",
            "source_type": "regulator",
            "published_date": (today - timedelta(days=240)).isoformat(),
            "sector": "Pharma & Biopharma",
            "region": "Global",
            "organization": "",
            "signal_kind": "Regulation",
            "product_family": "Nebulizers",
            "credibility": 0.96, "relevance": 0.86, "buying_intent": 0.52,
        },
        {
            "title": "Expansion of critical-minerals processing increases complex-matrix testing",
            "summary": "Public investment in critical-minerals extraction, refining and recycling supports additional elemental-analysis capacity.",
            "url": "https://www.industry.gov.au/mining-oil-and-gas/minerals/critical-minerals",
            "source_name": "Australian Government",
            "source_type": "government",
            "published_date": (today - timedelta(days=45)).isoformat(),
            "sector": "Battery & Critical Minerals",
            "region": "Australia",
            "organization": "",
            "signal_kind": "Funding",
            "product_family": "Nebulizers",
            "credibility": 0.92, "relevance": 0.82, "buying_intent": 0.58,
        },
        {
            "title": "Mass-cytometry research sustains specialist ICP-TOF consumable demand",
            "summary": "Continued clinical and single-cell research creates a specialist market for ICP-TOF and mass-cytometry sample-interface components.",
            "url": "https://pubmed.ncbi.nlm.nih.gov/?term=mass+cytometry",
            "source_name": "PubMed research index",
            "source_type": "journal",
            "published_date": (today - timedelta(days=25)).isoformat(),
            "sector": "Clinical & Life Science",
            "region": "Global",
            "organization": "",
            "signal_kind": "Research activity",
            "product_family": "ICP-TOF / mass cytometry",
            "credibility": 0.88, "relevance": 0.80, "buying_intent": 0.30,
        },
        {
            "title": "Commercial laboratories prioritize faster washout and unattended operation",
            "summary": "High-throughput laboratories continue to seek lower carryover, shorter washout and fewer probe or nebulizer blockages.",
            "url": "https://www.nist.gov/laboratories",
            "source_name": "Public laboratory trend seed",
            "source_type": "other",
            "published_date": (today - timedelta(days=60)).isoformat(),
            "sector": "Commercial Testing",
            "region": "Global",
            "organization": "",
            "signal_kind": "Operational pain",
            "product_family": "Spray chambers",
            "credibility": 0.55, "relevance": 0.90, "buying_intent": 0.66,
        },
        {
            "title": "Laser-ablation ICP-MS remains active in geochronology and materials research",
            "summary": "Recent methods and applications preserve demand for robust laser-ablation transfer and interface components.",
            "url": "https://search.crossref.org/?q=laser%20ablation%20ICP-MS",
            "source_name": "Crossref public index",
            "source_type": "journal",
            "published_date": (today - timedelta(days=15)).isoformat(),
            "sector": "Research & Academia",
            "region": "Global",
            "organization": "",
            "signal_kind": "Research activity",
            "product_family": "Laser ablation interfaces",
            "credibility": 0.88, "relevance": 0.84, "buying_intent": 0.28,
        },
    ]


DEFAULT_QUERIES = [
    '"ICP-MS" battery',
    '"ICP-MS" semiconductor',
    '"ICP-MS" elemental impurities',
    '"ICP-MS" drinking water',
    '"ICP-MS" mass cytometry',
    '"laser ablation ICP-MS"',
    '"ICP-MS" critical minerals',
]

GRANT_QUERIES = [
    "inductively coupled plasma mass spectrometry",
    "mass cytometry",
    "trace element analysis",
    "elemental impurities analysis",
]


def seed_database(path: str | None = None) -> tuple[int, int]:
    result = (0, 0)  # Starter notes are illustrative, not dated public evidence.
    for query in DEFAULT_QUERIES:
        add_watch_query(query, path)
    return result
