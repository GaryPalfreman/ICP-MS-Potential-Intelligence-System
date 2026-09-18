"""Reclassify existing source text without re-running unrelated public APIs."""
import json
import pandas as pd
from icpms_intel.collectors import collect_ted_procurement
from icpms_intel.quality import source_relevance
from icpms_intel.snapshots import SNAPSHOT_PATH, STATUS_PATH, deduplicate_snapshot
from icpms_intel.taxonomy import classify_sector, classify_product


def main():
    frame = pd.read_csv(SNAPSHOT_PATH).fillna('')
    text = frame.title + ' ' + frame.summary
    frame['relevance'] = text.map(source_relevance)
    research = frame.source_type.isin(['journal', 'grant'])
    frame.loc[research, 'sector'] = text[research].map(classify_sector)
    frame.loc[research, 'product_family'] = text[research].map(classify_product)
    for column in ('doi', 'response_deadline', 'notice_status'):
        if column not in frame:
            frame[column] = ''
    # A failed tender fetch aborts this migration without changing the snapshot.
    tenders = pd.DataFrame(collect_ted_procurement()).drop(columns=['raw_json'], errors='ignore')
    frame = pd.concat([frame[frame.source_name.ne('TED (EU procurement)')], tenders], ignore_index=True).fillna('')
    frame, _ = deduplicate_snapshot(frame)
    frame.sort_values(['published_date', 'title'], ascending=[False, True]).to_csv(SNAPSHOT_PATH, index=False)
    status = json.loads(STATUS_PATH.read_text())
    status.update(snapshot_records=len(frame), ted_procurement_records=len(tenders),
                  ted_buyers=tenders.organization.nunique() if len(tenders) else 0,
                  accuracy_release='source-text relevance, identifier identity, structured deadlines')
    STATUS_PATH.write_text(json.dumps(status, indent=2) + '\n')
    print({'records': len(frame), 'explicit_icp_evidence': int(frame.relevance.ge(.8).sum()), 'tenders': len(tenders)})


if __name__ == '__main__':
    main()
