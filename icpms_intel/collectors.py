from __future__ import annotations

import html
import os
import re
import time
from datetime import date, timedelta
from urllib.parse import quote

import feedparser
from .quality import source_relevance
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
TED_SEARCH_URL = "https://api.ted.europa.eu/v3/notices/search"
ICP_MASS_SPEC_TERMS = (
    "icp-ms", "icp ms", "icp–ms", "inductively coupled plasma",
    "plasma mass spectrom", "elemental mass spectrom", "elemental analys",
)


def _get(url: str, **kwargs):
    """GET a public endpoint with bounded backoff for rate limits and outages."""
    timeout = kwargs.pop("timeout", TIMEOUT)
    attempts = int(kwargs.pop("_attempts", 4))
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=HEADERS, timeout=timeout, **kwargs)
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(min(2 ** attempt, 15))
            continue
        if response.status_code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
            response.raise_for_status()
            return response
        retry_after = response.headers.get("Retry-After", "")
        delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 2 ** attempt
        time.sleep(min(delay, 15))
    raise RuntimeError("Public source request failed after retries")


def _post(url: str, **kwargs):
    """POST to a public endpoint with the same bounded retry policy as GET."""
    timeout = kwargs.pop("timeout", TIMEOUT)
    attempts = int(kwargs.pop("_attempts", 3))
    for attempt in range(attempts):
        try:
            response = requests.post(url, headers=HEADERS, timeout=timeout, **kwargs)
        except requests.RequestException:
            if attempt == attempts - 1:
                raise
            time.sleep(min(2 ** attempt, 15))
            continue
        if response.status_code not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
            response.raise_for_status()
            return response
        retry_after = response.headers.get("Retry-After", "")
        delay = float(retry_after) if retry_after.replace(".", "", 1).isdigit() else 2 ** attempt
        time.sleep(min(delay, 15))
    raise RuntimeError("Public source request failed after retries")


def _clean(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", html.unescape(str(value)))
    return re.sub(r"\s+", " ", value).strip()


def _date(value) -> str | None:
    if not value:
        return None
    # TED sometimes returns a date followed directly by an offset, without a
    # time component (for example 2026-09-18+02:00).
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", str(value))
    if match:
        return match.group(1)
    try:
        return date_parser.parse(str(value)).date().isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def _localized_text(value) -> str:
    """Return English TED text where available, with safe fallbacks."""
    if isinstance(value, dict):
        value = value.get("eng") or next((item for item in value.values() if item), "")
    if isinstance(value, list):
        value = " | ".join(_localized_text(item) for item in value if item)
    return _clean(value)


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
    response = _get(url)
    results = []
    for item in response.json().get("message", {}).get("items", []):
        title = _clean(" ".join(item.get("title", [])))
        summary = _clean(item.get("abstract", ""))
        text = f"{title} {summary}"
        date_parts = item.get("published", {}).get("date-parts", [[]])[0]
        published = "-".join(str(x).zfill(2) for x in date_parts) if date_parts else None
        results.append({
            "title": title or "Untitled Crossref record",
            "summary": summary[:2000],
            "url": item.get("URL", ""),
            "source_name": item.get("publisher", "Crossref"),
            "source_type": "journal",
            "doi": item.get("DOI", ""),
            "published_date": published,
            "sector": classify_sector(text),
            "region": "Global",
            "organization": _affiliation(item),
            "instrument_vendor": _vendor(text),
            "signal_kind": "Research activity",
            "product_family": classify_product(text),
            "credibility": SOURCE_CREDIBILITY["journal"],
            "relevance": source_relevance(text),
            "buying_intent": 0.28,
            "raw_json": item,
        })
    return results


def collect_europe_pmc(query: str, days: int = 730, limit: int = 40) -> list[dict]:
    start_year = (date.today() - timedelta(days=days)).year
    api = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    params = {"query": f'({query}) AND FIRST_PDATE:[{start_year}-01-01 TO *]', "format": "json", "pageSize": min(limit, 100)}
    response = _get(api, params=params)
    results = []
    for item in response.json().get("resultList", {}).get("result", []):
        title = _clean(item.get("title"))
        summary = _clean(item.get("journalTitle", ""))
        text = f"{title} {summary}"
        identifier = item.get("doi") or item.get("pmcid") or item.get("pmid", "")
        link = (f"https://doi.org/{item['doi']}" if item.get("doi") else
                f"https://europepmc.org/article/{item.get('source', 'MED')}/{item.get('id') or item.get('pmid')}"
                if item.get("id") or item.get("pmid") else "")
        results.append({
            "title": title or "Untitled Europe PMC record",
            "summary": summary,
            "url": link,
            "source_name": "Europe PMC",
            "doi": item.get("doi", ""),
            "source_type": "journal",
            "published_date": _date(item.get("firstPublicationDate") or item.get("firstIndexDate")),
            "sector": classify_sector(text),
            "region": "Global",
            "organization": "",
            "instrument_vendor": _vendor(text),
            "signal_kind": "Research activity",
            "product_family": classify_product(text),
            "credibility": SOURCE_CREDIBILITY["journal"],
            "relevance": source_relevance(text),
            "buying_intent": 0.26,
            "raw_json": {"id": identifier, **item},
        })
    return results


def collect_rss(feed_url: str, source_name: str = "Public RSS") -> list[dict]:
    response = _get(feed_url)
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


def collect_openalex(query: str, days: int = 730, limit: int = 40) -> list[dict]:
    start = (date.today() - timedelta(days=days)).isoformat()
    params = {"search": query, "filter": f"from_publication_date:{start}", "per-page": min(limit, 100)}
    if os.getenv("OPENALEX_MAILTO"):
        params["mailto"] = os.environ["OPENALEX_MAILTO"]
    response = _get(
        "https://api.openalex.org/works",
        params=params,
    )
    rows = []
    for item in response.json().get("results", []):
        title = _clean(item.get("title"))
        institutions = []
        for authorship in item.get("authorships", []):
            institutions.extend(authorship.get("institutions", []))
        institution = next((entry for entry in institutions if entry.get("display_name")), {})
        organization = _clean(institution.get("display_name"))
        text = title
        rows.append({
            "title": title or "Untitled OpenAlex record",
            "summary": _clean(item.get("type_crossref") or item.get("type", "")),
            "url": item.get("doi") or item.get("id", ""),
            "source_name": "OpenAlex",
            "doi": item.get("doi", ""),
            "source_type": "journal",
            "published_date": _date(item.get("publication_date")),
            "sector": classify_sector(text),
            "region": _clean((institution.get("country_code") or "Global")),
            "organization": organization,
            "organization_id": institution.get("id", ""),
            "instrument_vendor": _vendor(text),
            "signal_kind": "Research activity",
            "product_family": classify_product(text),
            "credibility": SOURCE_CREDIBILITY["journal"],
            "relevance": source_relevance(text),
            "buying_intent": 0.3,
            "raw_json": {"openalex_id": item.get("id"), "institution_id": institution.get("id")},
        })
    return rows


def collect_nih_reporter(query: str, days: int = 1095, limit: int = 40) -> list[dict]:
    """Collect recently funded US projects from the public NIH RePORTER API."""
    start = (date.today() - timedelta(days=days)).isoformat()
    payload = {
        "criteria": {"advanced_text_search": {"operator": "and", "search_field": "all", "search_text": query}},
        "include_fields": [
            "ProjectTitle", "AbstractText", "Organization", "ProjectStartDate",
            "ProjectEndDate", "AwardAmount", "ProjectNum", "AgencyIcAdmin",
        ],
        "offset": 0,
        "limit": min(limit, 100),
        "sort_field": "project_start_date",
        "sort_order": "desc",
    }
    response = requests.post(
        "https://api.reporter.nih.gov/v2/projects/search",
        json=payload,
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    rows = []
    for item in response.json().get("results", []):
        started = _date(item.get("project_start_date"))
        if started and started < start:
            continue
        org = item.get("organization") or {}
        title = _clean(item.get("project_title"))
        summary = _clean(item.get("abstract_text"))
        text = f"{title} {summary}"
        project_num = item.get("project_num", "")
        rows.append({
            "title": title or "Untitled NIH-funded project",
            "summary": summary[:2000],
            "url": f"https://reporter.nih.gov/project-details/{project_num}" if project_num else "https://reporter.nih.gov/",
            "source_name": "NIH RePORTER",
            "source_type": "grant",
            "published_date": started,
            "sector": classify_sector(text),
            "region": _clean(org.get("org_state") or org.get("org_country") or "United States"),
            "organization": _clean(org.get("org_name")),
            "instrument_vendor": _vendor(text),
            "signal_kind": "Funding",
            "product_family": classify_product(text),
            "credibility": SOURCE_CREDIBILITY["grant"],
            "relevance": source_relevance(text),
            "buying_intent": 0.67,
            "raw_json": {"project_num": project_num, "award_amount": item.get("award_amount")},
        })
    return rows


def collect_sam_gov(query: str, api_key: str, days: int = 90, limit: int = 100) -> list[dict]:
    """Collect US federal opportunities. SAM.gov requires a free API key."""
    if not api_key:
        raise ValueError("SAM.gov API key is required")
    posted_from = (date.today() - timedelta(days=days)).strftime("%m/%d/%Y")
    posted_to = date.today().strftime("%m/%d/%Y")
    response = _get(
        "https://api.sam.gov/opportunities/v2/search",
        params={
            "api_key": api_key, "q": query, "postedFrom": posted_from,
            "postedTo": posted_to, "limit": min(limit, 1000), "offset": 0,
        },
    )
    rows = []
    for item in response.json().get("opportunitiesData", []):
        title = _clean(item.get("title"))
        text = f"{title} {_clean(item.get('description'))}"
        notice_id = item.get("noticeId", "")
        rows.append({
            "title": title or "Untitled SAM.gov opportunity",
            "summary": _clean(item.get("description"))[:2000],
            "url": f"https://sam.gov/opp/{notice_id}/view" if notice_id else "https://sam.gov/content/opportunities",
            "source_name": "SAM.gov",
            "response_deadline": _date(item.get("responseDeadLine")),
            "notice_status": "active" if str(item.get("active", "")).lower() == "yes" and str(item.get("type", "")).lower() in {"solicitation", "combined synopsis/solicitation"} else "unverified",
            "source_type": "procurement",
            "published_date": _date(item.get("postedDate")),
            "sector": classify_sector(text), "region": "United States",
            "organization": _clean(item.get("fullParentPathName") or item.get("department")),
            "instrument_vendor": _vendor(text), "signal_kind": "Procurement",
            "product_family": classify_product(text),
            "credibility": SOURCE_CREDIBILITY["procurement"], "relevance": 0.94,
            "buying_intent": 0.98, "raw_json": {"notice_id": notice_id},
        })
    return rows


def collect_ted_procurement(days: int = 730, limit: int = 250) -> list[dict]:
    """Collect open ICP-relevant EU procurement notices from TED without authentication.

    TED's exact mass-spectrometer CPV category is queried first; a conservative
    text filter then excludes unrelated LC-MS, GC-MS and clinical-MS notices.
    Requiring a future response deadline keeps award notices and closed tenders
    from being presented as active sales opportunities.
    """
    del days  # Kept in the public signature for backwards compatibility.
    today = date.today().strftime("%Y%m%d")
    payload = {
        "query": (
            f"classification-cpv=38433100 AND deadline-receipt-tender-date-lot>={today} "
            "SORT BY publication-date DESC"
        ),
        "fields": [
            "publication-number", "notice-title", "title-lot", "title-proc",
            "description-lot", "publication-date", "deadline-receipt-tender-date-lot",
            "organisation-name-buyer", "organisation-country-buyer",
            "classification-cpv", "notice-type",
        ],
        "page": 1,
        "limit": min(max(int(limit), 10), 250),
        "scope": "ACTIVE",
        "paginationMode": "PAGE_NUMBER",
        "onlyLatestVersions": True,
    }
    response = _post(TED_SEARCH_URL, json=payload, timeout=max(TIMEOUT, 45))
    notices = response.json().get("notices", [])
    if not isinstance(notices, list):
        raise RuntimeError("TED response is missing notices")

    rows = []
    seen_opportunities: set[tuple[str, str]] = set()
    for item in notices:
        title = _localized_text(item.get("notice-title") or item.get("title-lot") or item.get("title-proc"))
        detail = _localized_text(item.get("description-lot"))
        text = f"{title} {detail}".strip()
        if not any(term in text.lower() for term in ICP_MASS_SPEC_TERMS):
            continue

        notice_number = _clean(item.get("publication-number"))
        buyer = _localized_text(item.get("organisation-name-buyer"))
        opportunity_key = (buyer.casefold(), title.casefold())
        if opportunity_key in seen_opportunities:
            continue
        seen_opportunities.add(opportunity_key)
        country = _localized_text(item.get("organisation-country-buyer")) or "European Union"
        deadlines = _localized_text(item.get("deadline-receipt-tender-date-lot"))
        cpv = _localized_text(item.get("classification-cpv"))
        notice_type = _clean(item.get("notice-type"))
        summary_parts = [detail, f"Buyer: {buyer}" if buyer else "", f"Deadline: {deadlines}" if deadlines else "", f"CPV: {cpv}" if cpv else "", f"Notice type: {notice_type}" if notice_type else ""]
        summary = " | ".join(part for part in summary_parts if part)
        rows.append({
            "title": title or f"TED ICP-MS procurement notice {notice_number}",
            "summary": summary[:2000],
            "url": f"https://ted.europa.eu/en/notice/-/detail/{notice_number}" if notice_number else "https://ted.europa.eu/",
            "source_name": "TED (EU procurement)",
            "response_deadline": max(re.findall(r"\d{4}-\d{2}-\d{2}", deadlines), default=""),
            "notice_status": "active",
            "source_type": "procurement",
            "published_date": _date(item.get("publication-date")),
            "sector": classify_sector(text),
            "region": country,
            "organization": buyer,
            "instrument_vendor": _vendor(text),
            "signal_kind": "Procurement",
            "product_family": classify_product(text),
            "credibility": SOURCE_CREDIBILITY["procurement"],
            "relevance": 0.98,
            "buying_intent": 0.98,
            "raw_json": {"publication_number": notice_number, "deadline": deadlines, "cpv": cpv},
        })
    return rows


def collect_gdelt_news(query: str, limit: int = 40) -> list[dict]:
    """Collect public announcements and news through GDELT's open document API."""
    # GDELT can be slow; news is supplementary, so do not hold the full daily run
    # through the retry window used for primary scientific and grant sources.
    response = _get(
        "https://api.gdeltproject.org/api/v2/doc/doc",
        params={
            "query": query, "mode": "ArtList", "format": "json",
            "maxrecords": min(limit, 250), "sort": "DateDesc", "timespan": "3months",
        },
        timeout=min(TIMEOUT, 20),
        _attempts=2,
    )
    rows = []
    for item in response.json().get("articles", []):
        title = _clean(item.get("title"))
        text = title
        lowered = text.lower()
        if not any(term in lowered for term in ("icp-ms", "icp ms", "mass spectrom", "elemental analy", "trace element")):
            continue
        rows.append({
            "title": title or "Untitled public announcement",
            "summary": _clean(item.get("seendate") or item.get("domain", "")),
            "url": item.get("url", ""),
            "source_name": _clean(item.get("domain") or "GDELT public news index"),
            "source_type": "news", "published_date": _date(item.get("seendate")),
            "sector": classify_sector(text), "region": _clean(item.get("sourcecountry") or "Global"),
            "organization": "", "instrument_vendor": _vendor(text),
            "signal_kind": classify_signal(text), "product_family": classify_product(text),
            "credibility": SOURCE_CREDIBILITY["news"], "relevance": 0.68,
            "buying_intent": 0.55 if classify_signal(text) != "Research activity" else 0.32,
            "raw_json": {"language": item.get("language"), "domain": item.get("domain")},
        })
    return rows
