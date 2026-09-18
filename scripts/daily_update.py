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


def main() -> int:
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    errors: list[str] = []
    collected: list[dict] = []

    with tempfile.TemporaryDirectory() as temp_dir:
        db = str(Path(temp_dir) / "daily.db")
        init_db(db)
        load_public_snapshot(db=db)
        insert_signals(starter_signals(), db)

        jobs = []
        with ThreadPoolExecutor(max_workers=5) as executor:
            for query in DEFAULT_QUERIES:
                future = executor.submit(collect_europe_pmc, query, 730, 40)
                jobs.append((future, "Europe PMC", query))

            for query in GRANT_QUERIES:
                future = executor.submit(collect_nih_reporter, query, 1095, 25)
                jobs.append((future, "NIH RePORTER", query))

            for future, source_name, query in jobs:
                try:
                    collected.extend(future.result())
                except Exception as exc:  # one source must not stop the full update
                    errors.append(f"{source_name} [{query}]: {exc}")

        # Crossref and OpenAlex are intentionally paced to respect public limits.
        for query in DEFAULT_QUERIES:
            try:
                collected.extend(collect_openalex(query, days=730, limit=40))
            except Exception as exc:
                errors.append(f"OpenAlex [{query}]: {exc}")
            time.sleep(1)
            try:
                collected.extend(collect_crossref(query, days=730, limit=40))
            except Exception as exc:
                errors.append(f"Crossref [{query}]: {exc}")
            time.sleep(1)

        news_queries = [
            '"ICP-MS" (tender OR procurement OR installed OR commissioned)',
        ]
        for query in news_queries:
            try:
                collected.extend(collect_gdelt_news(query, limit=40))
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
                collected.extend(collect_rss(feed_url, "Google News public RSS"))
            except Exception as exc:
                errors.append(f"Public news RSS [{query}]: {exc}")

        ted_succeeded = False
        try:
            collected.extend(collect_ted_procurement(days=730, limit=250))
            ted_succeeded = True
        except Exception as exc:
            errors.append(f"TED procurement: {exc}")

        sam_key = os.getenv("SAM_GOV_API_KEY", "").strip()
        if sam_key:
            for query in ('"ICP-MS"', '"mass spectrometer" elemental'):
                try:
                    collected.extend(collect_sam_gov(query, sam_key, days=90, limit=100))
                except Exception as exc:
                    errors.append(f"SAM.gov [{query}]: {exc}")

        inserted, skipped = insert_signals(collected, db)
        snapshot = signals_df(db).drop(columns=["id", "collected_at", "raw_json"], errors="ignore")
        # TED is an active-opportunity feed. Remove notices that are no longer
        # returned by today's future-deadline search instead of retaining them
        # forever in the historical snapshot.
        current_ted_urls = {
            row.get("url", "") for row in collected
            if row.get("source_name") == "TED (EU procurement)"
        }
        ted_mask = snapshot["source_name"].eq("TED (EU procurement)")
        if ted_succeeded:
            snapshot = snapshot[~ted_mask | snapshot["url"].isin(current_ted_urls)].copy()
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
        # TED can publish several amendments for the same buyer and procedure.
        # Count the newest version once so amendments do not mimic corroboration.
        ted_mask = snapshot["source_name"].eq("TED (EU procurement)")
        ted = snapshot[ted_mask].drop_duplicates(subset=["organization", "title"], keep="first")
        snapshot = pd.concat([snapshot[~ted_mask], ted], ignore_index=True)
        snapshot, duplicate_records_removed = deduplicate_snapshot(snapshot)
        snapshot = snapshot.sort_values(["published_date", "title"], ascending=[False, True], na_position="last")
        snapshot.to_csv(SNAPSHOT_PATH, index=False)
        # Fail before commit if a malformed or empty snapshot would replace good evidence.
        check = pd.read_csv(SNAPSHOT_PATH)
        required = {"title", "url", "source_name", "published_date", "sector", "signal_kind"}
        if not required.issubset(check.columns) or len(check) < 8:
            raise RuntimeError("Snapshot integrity check failed")

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
    }
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))

    # Preserve useful partial results if one public service is temporarily down.
    return 0 if collected else 1


if __name__ == "__main__":
    raise SystemExit(main())
