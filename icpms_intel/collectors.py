from __future__ import annotations

import html
import os
import re
from datetime import date, timedelta
from urllib.parse import quote

import feedparser
import requests
from dateutil import parser as date_parser

from .taxonomy import (
    SOURCE_CREDIBILITY,
    classify_product,
    classify_sector,
    classify_signal,
)

TIMEOUT = int(os.getenv("ICPMS_REQUEST_TIMEOUT", "20"))
HEADERS = {"User-Agent": "ICPMS-Potential-Intelligence-System/1.0 (public research)"}


def _clean(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", html.unescape(str(value)))
    return re.sub(r"\s+", " ", value).strip()


def _date(value) -> str | None:
    if not value:
        return None
    try:
        return date_parser.parse(str(value)).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def _vendor(text: str) -> str:
    names = ["Agilent", "Thermo Fisher", "PerkinElmer", "Analytik Jena", "Shimadzu", "Nu Instruments"]
    low = text.lower()
    return next((n for n in names if n.lower() in low), "")


def _affiliation(item: dict) -> str:
    for author in item.get("author", []):
        for affiliation in author.get("affiliation", []):
            name = _clean(affiliation.get("name"))
            if name:
                return name
    return ""


def collect_crossref(query: str, days: int = 730, limit: int = 40) -> list[dict]:
    start = (date.today() - timedelta(days=days)).isoformat()
    url = (
        "https://api.crossref.org/works"
        f"?query.bibliographic={quote(query)}&filter=from-pub-date:{start}"
        f"&rows={min(limit, 100)}&select=DOI,title,abstract,published,URL,author,publisher,container-title"
    )
    response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    results = []
    for item in response.json().get("message", {}).get("items", []):
        title = _clean(" ".join(item.get("title", [])))
        summary = _clean(item.get("abstract", ""))
        text = f"{title} {summary} {query}"
        date_parts = item.get("published", {}).get("date-parts", [[]])[0]
        published = "-".join(str(x).zfill(2) for x in date_parts) if date_parts else None
        results.append({
            "title": title or "Untitled Crossref record",
            "summary": summary[:2000],
            "url": item.get("URL", ""),
            "source_name": item.get("publisher", "Crossref"),
            "source_type": "journal",
            "published_date": published,
            "sector": classify_sector(text),
            "region": "Global",
            "organization": _affiliation(item),
            "instrument_vendor": _vendor(text),
            "signal_kind": "Research activity",
            "product_family": classify_product(text),
            "credibility": SOURCE_CREDIBILITY["journal"],
            "relevance": 0.78 if "icp" in text.lower() else 0.55,
            "buying_intent": 0.28,
            "raw_json": item,
        })
    return results


def collect_europe_pmc(query: str, days: int = 730, limit: int = 40) -> list[dict]:
    start_year = (date.today() - timedelta(days=days)).year
    api = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = {"query": f'({query}) AND FIRST_PDATE:[{start_year}-01-01 TO *]', "format": "json", "pageSize": min(limit, 100)}
    response = requests.get(api, params=params, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    results = []
    for item in response.json().get("resultList", {}).get("result", []):
        title = _clean(item.get("title"))
        summary = _clean(item.get("journalTitle", ""))
        text = f"{title} {summary} {query}"
        identifier = item.get("doi") or item.get("pmcid") or item.get("pmid", "")
        link = f"https://europepmc.org/article/MED/{item.get('pmid')}" if item.get("pmid") else ""
        results.append({
            "title": title or "Untitled Europe PMC record",
            "summary": summary,
            "url": link,
            "source_name": "Europe PMC",
            "source_type": "journal",
            "published_date": _date(item.get("firstPublicationDate") or item.get("firstIndexDate")),
            "sector": classify_sector(text),
            "region": "Global",
            "organization": "",
            "instrument_vendor": _vendor(text),
            "signal_kind": "Research activity",
            "product_family": classify_product(text),
            "credibility": SOURCE_CREDIBILITY["journal"],
            "relevance": 0.8 if "icp" in text.lower() else 0.55,
            "buying_intent": 0.26,
            "raw_json": {"id": identifier, **item},
        })
    return results


def collect_rss(feed_url: str, source_name: str = "Public RSS") -> list[dict]:
    response = requests.get(feed_url, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    rows = []
    for entry in feed.entries[:100]:
        title = _clean(entry.get("title"))
        summary = _clean(entry.get("summary") or entry.get("description"))
        text = f"{title} {summary}"
        if not any(term in text.lower() for term in ["icp-ms", "icp ms", "mass spectrom", "elemental", "semiconductor", "battery"]):
            continue
        rows.append({
            "title": title,
            "summary": summary[:2000],
            "url": entry.get("link", ""),
            "source_name": source_name,
            "source_type": "news",
            "published_date": _date(entry.get("published") or entry.get("updated")),
            "sector": classify_sector(text),
            "region": "Global",
            "organization": "",
            "instrument_vendor": _vendor(text),
            "signal_kind": classify_signal(text),
            "product_family": classify_product(text),
            "credibility": SOURCE_CREDIBILITY["news"],
            "relevance": 0.65,
            "buying_intent": 0.38,
            "raw_json": dict(entry),
        })
    return rows

