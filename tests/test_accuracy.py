from datetime import date, timedelta
import pandas as pd

from icpms_intel.database import evidence_identity, init_db, insert_signals, signals_df, save_feedback, feedback_df
from icpms_intel.quality import source_relevance, tender_state
from icpms_intel.intelligence import sales_stage, trend_acceleration, product_fit
from icpms_intel.snapshots import sync_public_snapshot
from icpms_intel import collectors


def test_distinct_dois_same_title_not_merged():
    first = {"title": "Editorial", "source_type": "journal", "url": "https://doi.org/10.123/a"}
    second = {**first, "url": "https://doi.org/10.123/b"}
    assert evidence_identity(first) != evidence_identity(second)
    assert evidence_identity(first) == evidence_identity({**first, "title": "Different index title", "url": "https://dx.doi.org/10.123/A"})


def test_query_does_not_inflate_relevance(monkeypatch):
    class Response:
        def json(self):
            return {"message": {"items": [{"title": ["Forest management"], "published": {"date-parts": [[2026, 1, 1]]}}]}}
    monkeypatch.setattr(collectors, "_get", lambda *a, **kw: Response())
    row = collectors.collect_crossref('ICP-MS battery')[0]
    assert row['relevance'] == .15
    assert row['sector'] != 'Battery & Critical Minerals'


def test_tenders_require_future_deadline_and_status():
    row = {"signal_kind": "Procurement", "title": "ICP-MS tender"}
    assert sales_stage(row) != 'Active tender'
    row['response_deadline'] = (date.today() + timedelta(days=1)).isoformat()
    assert tender_state(row) == 'Unverified status'
    row['notice_status'] = 'active'
    assert tender_state(row) == 'Open'
    row['response_deadline'] = date.today().isoformat()
    assert tender_state(row) != 'Open'
    row.update(response_deadline='2099-01-01', notice_status='cancelled')
    assert tender_state(row) != 'Open'


def test_future_publications_not_counted_as_momentum():
    frame = pd.DataFrame({'sector': ['Test'] * 4, 'published_date': ['2099-01-01'] * 4})
    assert trend_acceleration(frame).iloc[0]['last_90_days'] == 0


def test_product_assignment_does_not_corroborate_itself():
    assert product_fit({'title': 'Study', 'summary': '', 'product_family': 'Nebulizers'})[1] == .58


def test_sync_updates_preserves_ids_reviews_and_manual_rows(tmp_path):
    db = str(tmp_path / 'test.db')
    path = tmp_path / 'snapshot.csv'
    init_db(db)
    row = {'title': 'ICP-MS study', 'url': 'https://doi.org/10.123/a', 'source_type': 'journal', 'source_name': 'Index', 'sector': 'General ICP-MS', 'signal_kind': 'Research activity', 'relevance': .8}
    pd.DataFrame([row]).to_csv(path, index=False)
    assert sync_public_snapshot(path, db)
    signal_id = int(signals_df(db).iloc[0]['id'])
    save_feedback(signal_id, 'Relevant', 'Keep this review', db)
    insert_signals([{'title': 'Manual note', 'url': 'https://example.com/manual'}], db)
    pd.DataFrame([{**row, 'relevance': .15}]).to_csv(path, index=False)
    assert sync_public_snapshot(path, db)
    updated = signals_df(db).set_index('id').loc[signal_id]
    assert updated['relevance'] == .15
    assert feedback_df(db).iloc[0]['notes'] == 'Keep this review'
    assert not sync_public_snapshot(path, db)
    pd.DataFrame([{**row, 'url': 'https://doi.org/10.123/b', 'title': 'New paper'}]).to_csv(path, index=False)
    sync_public_snapshot(path, db)
    assert 'Manual note' in signals_df(db).title.tolist()
    assert signal_id not in signals_df(db).id.tolist()
    assert len(feedback_df(db)) == 1
