from __future__ import annotations

SECTORS = {
    "Battery & Critical Minerals": [
        "battery", "lithium", "cathode", "anode", "critical mineral", "rare earth",
        "nickel", "cobalt", "recycling", "geochemistry", "mining",
    ],
    "Semiconductor & High Purity": [
        "semiconductor", "wafer", "cleanroom", "ultrapure", "ultra-pure",
        "electronic chemical", "silicon", "contamination control",
    ],
    "Environmental & Water": [
        "environment", "drinking water", "wastewater", "groundwater", "soil",
        "pollution", "epa", "water quality", "particulate",
    ],
    "Pharma & Biopharma": [
        "pharma", "drug", "elemental impurities", "ich q3d", "usp 232", "usp <232",
        "biopharma", "therapeutic", "oligonucleotide",
    ],
    "Food & Agriculture": [
        "food", "beverage", "agriculture", "crop", "nutrition", "contaminant",
        "novel food", "seafood",
    ],
    "Clinical & Life Science": [
        "clinical", "biological", "biomarker", "single cell", "mass cytometry",
        "cytometry", "metallomics", "toxicology",
    ],
    "Research & Academia": [
        "university", "institute", "research", "geochronology", "isotope",
        "laser ablation", "academic",
    ],
    "Commercial Testing": [
        "contract lab", "commercial laboratory", "testing laboratory", "accredited lab",
        "quality control", "quality assurance", "high throughput",
    ],
}

PRODUCT_FAMILIES = {
    "Interface cones": ["cone", "interface", "sampler", "skimmer", "sensitivity", "vacuum"],
    "Nebulizers": ["nebulizer", "nebuliser", "aerosol", "uptake", "low flow", "blockage"],
    "Spray chambers": ["spray chamber", "washout", "carryover", "peltier", "cyclonic"],
    "Torches & injectors": ["torch", "injector", "plasma", "matrix", "ceramic"],
    "Autosampler & tubing": ["autosampler", "probe", "tubing", "peristaltic", "automation"],
    "High-efficiency introduction": ["high efficiency", "he-sis", "microvolume", "low sample"],
    "Laser ablation interfaces": ["laser ablation", "la-icp", "geochronology", "solid sampling"],
    "ICP-TOF / mass cytometry": ["tof-icp", "mass cytometry", "single cell", "cytof"],
}

SIGNAL_KINDS = {
    "Procurement": ["tender", "procurement", "request for proposal", "rfp", "purchase"],
    "Facility expansion": ["new facility", "expansion", "cleanroom", "new laboratory", "new lab"],
    "Funding": ["grant", "funding", "award", "investment"],
    "Hiring": ["hiring", "vacancy", "job", "recruit", "analyst"],
    "Instrument installation": ["installed", "installation", "new instrument", "commissioned"],
    "Regulation": ["regulation", "standard", "guideline", "method update", "compliance"],
    "Research activity": ["study", "research", "publication", "method", "application"],
    "Operational pain": ["carryover", "blockage", "downtime", "washout", "maintenance", "drift"],
    "Market development": ["market", "demand", "growth", "supply chain", "manufacturing"],
}

SOURCE_CREDIBILITY = {
    "regulator": 0.96,
    "government": 0.92,
    "procurement": 0.92,
    "journal": 0.88,
    "grant": 0.88,
    "manufacturer": 0.78,
    "university": 0.82,
    "company": 0.70,
    "news": 0.62,
    "other": 0.50,
}


def match_taxonomy(text: str, taxonomy: dict[str, list[str]], default: str) -> str:
    lowered = (text or "").lower()
    best_name, best_hits = default, 0
    for name, terms in taxonomy.items():
        hits = sum(1 for term in terms if term in lowered)
        if hits > best_hits:
            best_name, best_hits = name, hits
    return best_name


def classify_sector(text: str) -> str:
    return match_taxonomy(text, SECTORS, "General ICP-MS")


def classify_product(text: str) -> str:
    return match_taxonomy(text, PRODUCT_FAMILIES, "General sample introduction")


def classify_signal(text: str) -> str:
    return match_taxonomy(text, SIGNAL_KINDS, "Research activity")

