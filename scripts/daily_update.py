from __future__ import annotations

import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd

from icpms_intel.collectors import (
    collect_crossref, collect_europe_pmc, collect_gdelt_news, collect_nih_reporter,
    collect_openalex, collect_rss, collect_sam_gov, collect_ted_procurement,
)
from icpms_intel.database import init_db, insert_signals, signals_df
from icpms_intel.seed import DEFAULT_QUERIES, GRANT_QUERIES, starter_signals
from icpms_intel.snapshots import SNAPSHOT_PATH, STATUS_PATH, deduplicate_snapshot, load_public_snapshot
from icpms_intel.taxonomy import classify_product, classify_sector, classify_signal
from icpms_intel.quality import source_relevance
from icpms_intel.verification import retain_tender_history, append_observations, record_predictions
from icpms_intel.snapshots import read_update_status


class CollectionAudit:
    def __init__(self, previous):
        self.results = []
        self.previous = previous

    def run(self, source, query, fn, *args, **kwargs):
        started = time.monotonic()
        key = source + '|' + query
        prior = next((r for r in self.previous.get('collection_results', []) if r['key'] == key), {})
        report = {'key': key, 'source': source, 'query': query,
                  'last_success_utc': prior.get('last_success_utc'), 'status': 'failed'}
        try:
            rows = fn(*args, **kwargs)
            report.update(getattr(rows, 'coverage', {}))
            report.update(status='success' if rows else 'empty', records=len(rows),
                          last_success_utc=datetime.now(timezone.utc).isoformat(timespec='seconds'))
            return rows
        except Exception as exc:
            # Never serialize request URLs that may contain API credentials.
            report['error_type'] = type(exc).__name__
            raise RuntimeError(type(exc).__name__) from None
        finally:
            report['duration_seconds'] = round(time.monotonic() - started, 2)
            self.results.append(report)
            print(f"{source}: {report['status']} ({report.get('records', 0)} records, {report['duration_seconds']}s)", flush=True)



def main() -> int:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    collected: list[dict] = []
    previous_status = read_update_status()
    audit = CollectionAudit(previous_status)

    with tempfile.TemporaryDirectory() as temp_dir:
        db = str(Path(temp_dir) / "daily.db")
        init_db(db)
        load_public_snapshot(db=db)

        jobs = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            for query in DEFAULT_QUERIES:
                future = executor.submit(audit.run, "Europe PMC", query, collect_europe_pmc, query, 730, 100)
                jobs.append((future, "Europe PMC", query))

            for query in GRANT_QUERIES:
                future = executor.submit(audit.run, "NIH RePORTER", query, collect_nih_reporter, query, 1095, 25)
                jobs.append((future, "NIH RePORTER", query))

            for future, source_name, query in jobs:
                try:
                    collected.extend(future.result())
                except Exception as exc:  # one source must not stop the full update
                    errors.append(f"{source_name} [{query}]: {exc}")

        # Crossref and OpenAlex are intentionally paced to respect public limits.
        for query in DEFAULT_QUERIES:
            try:
                collected.extend(audit.run("OpenAlex", query, collect_openalex, query, days=730, limit=100))
            except Exception as exc:
                errors.append(f"OpenAlex [{query}]: {exc}")
            time.sleep(1)
            try:
                collected.extend(audit.run("Crossref", query, collect_crossref, query, days=730, limit=100))
            except Exception as exc:
                errors.append(f"Crossref [{query}]: {exc}")
            time.sleep(1)

        news_queries = [
            '"ICP-MS" (tender OR procurement OR installed OR commissioned)',
        ]
        for query in news_queries:
            try:
                collected.extend(audit.run("GDELT", query, collect_gdelt_news, query, limit=40))
            except Exception as exc:
                errors.append(f"GDELT [{query}]: {exc}")

        rss_queries = [
            '"ICP-MS" tender OR procurement',
            '"ICP-MS" "new laboratory" OR installed OR commissioned',
            '"ICP-MS" hiring OR vacancy OR analyst',
        ]
        for query in rss_queries:
            feed_url = (
                "https://news.google.com/rss/search?q=" + quote_plus(query)
                + "&hl=en-AU&gl=AU&ceid=AU:en"
            )
            try:
                collected.extend(audit.run("Public news RSS", query, collect_rss, feed_url, "Google News public RSS"))
            except Exception as exc:
                errors.append(f"Public news RSS [{query}]: {exc}")

        ted_succeeded = False
        try:
            collected.extend(audit.run("TED procurement", "CPV 38433100 active", collect_ted_procurement, days=730, limit=250))
            ted_succeeded = True
        except Exception as exc:
            errors.append(f"TED procurement: {exc}")

        sam_key = os.getenv("SAM_GOV_API_KEY", "").strip()
        if sam_key:
            for query in ('"ICP-MS"', '"mass spectrometer" elemental'):
                try:
                    collected.extend(audit.run("SAM.gov", query, collect_sam_gov, query, sam_key, days=90, limit=100))
                except Exception as exc:
                    errors.append(f"SAM.gov [{query}]: {exc}")

        inserted, skipped = insert_signals(collected, db)
        snapshot = signals_df(db).drop(columns=["id", "collected_at", "raw_json"], errors="ignore")
        snapshot = retain_tender_history(snapshot, collected, ted_succeeded)
        # Re-evaluate text-derived fields so taxonomy improvements also upgrade
        # previously stored news records rather than only brand-new URLs.
        text = (snapshot["title"].fillna("") + " " + snapshot["summary"].fillna(""))
        snapshot["relevance"] = text.map(source_relevance)
        research_mask = snapshot["source_type"].isin(["journal", "grant"])
        snapshot.loc[research_mask, "sector"] = text[research_mask].map(classify_sector)
        snapshot.loc[research_mask, "product_family"] = text[research_mask].map(classify_product)
        news_mask = snapshot["source_type"].eq("news")
        snapshot.loc[news_mask, "signal_kind"] = text[news_mask].map(classify_signal)
        snapshot.loc[news_mask, "sector"] = text[news_mask].map(classify_sector)
        snapshot.loc[news_mask, "product_family"] = text[news_mask].map(classify_product)
        intent = {
            "Procurement": .95, "Instrument installation": .88, "Facility expansion": .80,
            "Hiring": .70, "Funding": .65, "Regulation": .58, "Market development": .45,
            "Operational pain": .62, "Research activity": .32,
        }
        snapshot.loc[news_mask, "buying_intent"] = snapshot.loc[news_mask, "signal_kind"].map(intent).fillna(.32)
        snapshot["summary"] = snapshot["summary"].fillna("").astype(str).str.slice(0, 2000)
        snapshot = snapshot.sort_values(["published_date", "title"], ascending=[False, True], na_position="last")
        snapshot, duplicate_records_removed = deduplicate_snapshot(snapshot)
        snapshot = snapshot.sort_values(["published_date", "title"], ascending=[False, True], na_position="last")
        staged = SNAPSHOT_PATH.with_suffix(".tmp.csv")
        snapshot.to_csv(staged, index=False)
        # Fail before commit if a malformed or empty snapshot would replace good evidence.
        check = pd.read_csv(staged)
        required = {"title", "url", "source_name", "published_date", "sector", "signal_kind"}
        if not required.issubset(check.columns) or len(check) < 8:
            raise RuntimeError("Snapshot integrity check failed")
        staged.replace(SNAPSHOT_PATH)
        if collected:
            append_observations(snapshot, Path('data/observations.csv'))
            record_predictions(snapshot, Path('data/predictions.csv'))

    status = {
        "last_attempt_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "successful": bool(collected) and len(snapshot) >= 8,
        "complete": len(errors) == 0,
        "sources": ["Crossref", "Europe PMC", "OpenAlex", "NIH RePORTER", "GDELT", "Public news RSS", "TED procurement"]
        + (["SAM.gov"] if sam_key else []),
        "queries_run": (
            len(DEFAULT_QUERIES) * 3 + len(GRANT_QUERIES) + len(news_queries)
            + len(rss_queries) + 1 + (2 if sam_key else 0)
        ),
        "records_received": len(collected),
        "new_records": inserted,
        "duplicates_skipped": skipped,
        "duplicate_records_removed": duplicate_records_removed,
        "snapshot_records": len(snapshot),
        "ted_procurement_records": int(snapshot["source_name"].eq("TED (EU procurement)").sum()),
        "ted_buyers": int(snapshot.loc[snapshot["source_name"].eq("TED (EU procurement)"), "organization"].nunique()),
        "warnings": errors,
        "collection_results": sorted(audit.results, key=lambda r: r['key']),
        "last_success_utc": datetime.now(timezone.utc).isoformat(timespec='seconds') if collected else previous_status.get('last_success_utc'),
        "coverage_note": "Bounded searches; missing results do not prove absence of activity.",
    }
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))

    # Preserve useful partial results if one public service is temporarily down.
    return 0 if collected else 1


if __name__ == "__main__":
    raise SystemExit(main())
