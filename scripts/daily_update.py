from __future__ import annotations

import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from icpms_intel.collectors import collect_crossref, collect_europe_pmc
from icpms_intel.database import init_db, insert_signals, signals_df
from icpms_intel.seed import DEFAULT_QUERIES, starter_signals
from icpms_intel.snapshots import SNAPSHOT_PATH, STATUS_PATH, load_public_snapshot


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
        with ThreadPoolExecutor(max_workers=4) as executor:
            for query in DEFAULT_QUERIES:
                future = executor.submit(collect_europe_pmc, query, 730, 40)
                jobs.append((future, "Europe PMC", query))

            for future, source_name, query in jobs:
                try:
                    collected.extend(future.result())
                except Exception as exc:  # one source must not stop the full update
                    errors.append(f"{source_name} [{query}]: {exc}")

        # Crossref is intentionally paced to respect its public rate limits.
        for query in DEFAULT_QUERIES:
            try:
                collected.extend(collect_crossref(query, days=730, limit=40))
            except Exception as exc:
                errors.append(f"Crossref [{query}]: {exc}")
            time.sleep(1)

        inserted, skipped = insert_signals(collected, db)
        snapshot = signals_df(db).drop(columns=["id", "collected_at"], errors="ignore")
        snapshot = snapshot.sort_values(["published_date", "title"], ascending=[False, True], na_position="last")
        snapshot.to_csv(SNAPSHOT_PATH, index=False)

    status = {
        "last_attempt_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "successful": len(errors) == 0,
        "sources": ["Crossref", "Europe PMC"],
        "queries_run": len(DEFAULT_QUERIES),
        "records_received": len(collected),
        "new_records": inserted,
        "duplicates_skipped": skipped,
        "snapshot_records": len(snapshot),
        "errors": errors,
    }
    STATUS_PATH.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, indent=2))

    # Preserve useful partial results if one public service is temporarily down.
    return 0 if collected else 1


if __name__ == "__main__":
    raise SystemExit(main())
