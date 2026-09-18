"""Recover identified journal records from a supplied pre-deduplication snapshot.

Usage: python -m scripts.recover_history /path/to/old.csv
Only DOI/URL-identified journal records are restored. Relevance is recalculated.
This cannot prove that the resulting collection is exhaustive.
"""
import argparse
import json
import pandas as pd
from icpms_intel.database import evidence_identity
from icpms_intel.snapshots import SNAPSHOT_PATH, deduplicate_snapshot
from icpms_intel.quality import source_relevance


def recover(current, historical):
    old = historical.fillna('')
    old = old[old['source_type'].eq('journal')]
    old = old[old.apply(lambda r: evidence_identity(r)[0] in {'doi','journal-url'}, axis=1)]
    known = {evidence_identity(r) for r in current.fillna('').to_dict('records')}
    missing = old[old.apply(lambda r: evidence_identity(r) not in known, axis=1)].copy()
    missing['relevance'] = missing.apply(lambda r: source_relevance(str(r['title'])+' '+str(r['summary'])), axis=1)
    combined, _ = deduplicate_snapshot(pd.concat([current, missing], ignore_index=True))
    return combined, len(combined)-len(current)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('historical_csv')
    args = parser.parse_args()
    frame, restored = recover(pd.read_csv(SNAPSHOT_PATH), pd.read_csv(args.historical_csv))
    frame.to_csv(SNAPSHOT_PATH, index=False)
    print(json.dumps({'identified_records_restored': restored, 'records': len(frame)}))


if __name__ == '__main__':
    main()
