from datetime import date
from pathlib import Path
import pandas as pd
import pytest
from icpms_intel.verification import (
    support_passages, evidence_key, source_fingerprint, benchmark_metrics,
    benchmark_candidates, retain_tender_history, append_observations,
    record_predictions, prospective_outcomes, corroboration_key,
)
from icpms_intel.database import init_db, insert_signals, signals_df, save_benchmark_label, benchmark_labels_df
from icpms_intel.quality import tender_state
from icpms_intel.scoring import organization_scores
from scripts.daily_update import CollectionAudit
from scripts.recover_history import recover
from icpms_intel import collectors

ROW = {'title':'ICP-MS installed at Example Lab', 'summary':'Example Lab commissioned an ICP-MS.',
       'url':'https://example.org/announcement', 'organization':'Example Lab',
       'source_type':'news','source_name':'Example', 'signal_kind':'Instrument installation',
       'sector':'General ICP-MS','region':'Global','published_date':'2026-09-18'}


def test_passages_are_exact_and_unknown_dates_are_not_invented():
    snippets = support_passages(ROW)
    for snippet in snippets:
        if snippet['field'] in {'title','summary'}:
            assert snippet['passage'] in ROW[snippet['field']]
        assert snippet['retrieved_at'] == 'Unknown (legacy record)'


def test_benchmark_unknowns_and_stale_truth_excluded():
    frame = pd.DataFrame([ROW])
    label = {**benchmark_candidates(frame).iloc[0].to_dict(), 'reviewer':'Tester',
             'reviewed_at':'2026-09-18', 'expected_relevance':'yes'}
    metrics, _ = benchmark_metrics(pd.DataFrame([label]), frame, date(2026,9,18))
    assert metrics.iloc[0]['accuracy'] == 1
    assert metrics.iloc[1]['reviewed_cases'] == 0
    changed = frame.copy(); changed.loc[0,'summary'] = 'Changed source'
    metrics, excluded = benchmark_metrics(pd.DataFrame([label]), changed)
    assert excluded == 1 and metrics.reviewed_cases.sum() == 0
    metrics, _ = benchmark_metrics(benchmark_candidates(frame), frame)
    assert metrics.reviewed_cases.sum() == 0


def test_benchmark_false_positive_and_false_negative():
    second = {**ROW, 'title':'Forest management', 'summary':'Tree planting', 'url':'https://example.org/forest'}
    frame = pd.DataFrame([ROW, second])
    labels = benchmark_candidates(frame)
    labels['reviewer'] = 'Tester'; labels['reviewed_at'] = '2026-09-18'
    labels['expected_relevance'] = labels.title.map(lambda t:'no' if 'ICP-MS' in t else 'yes')
    metrics,_ = benchmark_metrics(labels,frame)
    assert metrics.iloc[0]['false_positives'] == 1
    assert metrics.iloc[0]['false_negatives'] == 1


def test_tender_labels_expire_but_relevance_labels_do_not():
    frame = pd.DataFrame([ROW]); labels=benchmark_candidates(frame)
    labels['reviewer']='Tester'; labels['reviewed_at']='2026-09-17'
    labels['expected_relevance']='yes'; labels['expected_tender_open']='no'
    result,_ = benchmark_metrics(labels,frame,date(2026,9,18))
    assert result.set_index('task').loc['tender_open','reviewed_cases'] == 0
    assert result.set_index('task').loc['relevance','reviewed_cases'] == 1


def test_missing_tender_retained_without_fabricated_closure():
    row = {**ROW,'source_name':'TED (EU procurement)','notice_status':'active','response_deadline':'2099-01-01'}
    frame = pd.DataFrame([row])
    result=retain_tender_history(frame,[],True)
    assert len(result)==1 and result.iloc[0].notice_status=='not_returned'
    assert tender_state(result.iloc[0])!='Open'
    failed=retain_tender_history(frame,[],False)
    assert failed.iloc[0].notice_status=='active'
    expired=retain_tender_history(pd.DataFrame([{**row,'response_deadline':'2020-01-01'}]),[],False)
    assert expired.iloc[0].notice_status=='closed'


def test_collection_audit_distinguishes_empty_failure_and_cap():
    audit=CollectionAudit({})
    audit.run('X','q',lambda:collectors.CollectionResult([],0,0,100))
    assert audit.results[-1]['status']=='empty'
    with pytest.raises(RuntimeError):
        audit.run('Y','q',lambda:1/0)
    assert audit.results[-1]['status']=='failed'
    audit.run('Z','q',lambda:collectors.CollectionResult([ROW],100,400,100))
    assert audit.results[-1]['possibly_truncated']


def test_refresh_adds_abstract_without_resetting_first_seen(tmp_path):
    db=str(tmp_path/'db');init_db(db)
    insert_signals([{**ROW,'first_seen_at':'2026-09-01','last_seen_at':'2026-09-01'}],db)
    insert_signals([{**ROW,'summary':ROW['summary']+' Full abstract.', 'first_seen_at':'2026-09-18','last_seen_at':'2026-09-18'}],db)
    row=signals_df(db).iloc[0]
    assert row.first_seen_at=='2026-09-01' and row.last_seen_at=='2026-09-18'
    assert row.summary.endswith('Full abstract.')


def test_same_news_headline_does_not_increase_organisation_score():
    first={**ROW,'title':ROW['title']+' - Publisher A'}
    second={**ROW,'title':ROW['title']+' - Publisher B','url':'https://another.org/news'}
    assert corroboration_key(first)==corroboration_key(second)
    one=organization_scores(pd.DataFrame([first])).iloc[0]
    two=organization_scores(pd.DataFrame([first,second])).iloc[0]
    assert one.opportunity_score==two.opportunity_score
    assert two.signals==1


def test_observations_and_predictions_are_not_rewritten(tmp_path):
    frame=pd.DataFrame([ROW]); path=tmp_path/'obs.csv'; prediction=tmp_path/'pred.csv'
    original=append_observations(frame,path,'2026-09-18T10:00:00+00:00')
    repeated=append_observations(frame,path,'2026-09-18T12:00:00+00:00')
    assert len(repeated)==1 and repeated.iloc[0].observed_at==original.iloc[0].observed_at
    first=record_predictions(frame,prediction,'2026-09-18T10:01:00+00:00')
    second=record_predictions(frame,prediction,'2026-09-18T14:00:00+00:00')
    assert len(second)==1 and second.iloc[0].recorded_at==first.iloc[0].recorded_at


def test_prospective_outcomes_exclude_already_known_evidence(tmp_path):
    obs_path=tmp_path/'obs.csv'
    obs=append_observations(pd.DataFrame([ROW]),obs_path,'2026-09-18T10:00:00+00:00')
    predictions=record_predictions(pd.DataFrame([ROW]),tmp_path/'pred.csv','2026-09-18T11:00:00+00:00')
    obs=append_observations(pd.DataFrame([ROW]),obs_path,'2026-09-19T10:00:00+00:00')
    result=prospective_outcomes(predictions,obs,date(2026,9,20))
    assert result.iloc[0].evaluation=='Pending'
    later={**ROW,'title':'ICP-MS second installation','url':'https://example.org/new','published_date':'2026-09-20'}
    obs=append_observations(pd.DataFrame([later]),obs_path,'2026-09-20T10:00:00+00:00')
    assert prospective_outcomes(predictions,obs,date(2026,9,21)).iloc[0].evaluation=='Later public signal observed'


def test_recovery_preserves_distinct_identifiers():
    row={**ROW,'source_type':'journal','doi':'10.123/a','url':'https://doi.org/10.123/a'}
    other={**row,'doi':'10.123/b','url':'https://doi.org/10.123/b'}
    recovered,count=recover(pd.DataFrame([row]),pd.DataFrame([row,other]))
    assert count==1 and len(recovered)==2


def test_benchmark_reviews_survive_schema_init(tmp_path):
    db=str(tmp_path/'db');init_db(db)
    save_benchmark_label({**ROW,'reviewer':'Tester','expected_relevance':'yes'},db)
    init_db(db)
    assert benchmark_labels_df(db).iloc[0].expected_relevance=='yes'


def test_openalex_abstract_drives_relevance(monkeypatch):
    class Response:
        def json(self):
            return {'results':[{'title':'Element mapping','abstract_inverted_index':{'ICP-MS':[1],'Using':[0]}}]}
    monkeypatch.setattr(collectors,'_get',lambda *a,**kw:Response())
    row=collectors.collect_openalex('forest')[0]
    assert row['summary']=='Using ICP-MS' and row['relevance']==.85


def test_old_publication_recollected_later_is_not_prediction_success(tmp_path):
    predictions=record_predictions(pd.DataFrame([ROW]),tmp_path/'pred.csv','2026-09-18T11:00:00+00:00')
    old={**ROW,'title':'Old installation','url':'https://example.org/old','published_date':'2025-01-01'}
    obs=append_observations(pd.DataFrame([old]),tmp_path/'obs.csv','2026-09-20T10:00:00+00:00')
    assert prospective_outcomes(predictions,obs,date(2026,9,21)).iloc[0].evaluation=='Pending'


def test_primary_review_requires_valid_source_and_reviewer(tmp_path):
    from icpms_intel.database import save_primary_review, primary_reviews_df
    db=str(tmp_path/'db');init_db(db)
    with pytest.raises(ValueError):
        save_primary_review(1,'javascript:alert(1)','text','Tester',db)
    save_primary_review(1,'https://example.org/original','Original text','Tester',db)
    assert primary_reviews_df(db).iloc[0].reviewer=='Tester'


def test_starter_notes_are_not_live_evidence(tmp_path):
    from icpms_intel.seed import starter_signals
    db=str(tmp_path/'db');init_db(db)
    insert_signals(starter_signals(),db)
    assert signals_df(db).empty


def test_daily_pipeline_preserves_history_and_writes_coverage(tmp_path, monkeypatch):
    from scripts import daily_update as job
    from icpms_intel.snapshots import load_public_snapshot
    monkeypatch.chdir(tmp_path)
    data=tmp_path/'data';data.mkdir()
    snapshot=data/'public_signals.csv';status=data/'update_status.json'
    rows=[{**ROW,'title':f'ICP-MS study {i}','url':f'https://example.org/{i}', 'source_type':'journal'} for i in range(8)]
    tender={**ROW,'title':'ICP-MS tender','signal_kind':'Procurement','source_type':'procurement',
            'source_name':'TED (EU procurement)','notice_status':'active','response_deadline':'2099-01-01'}
    pd.DataFrame(rows+[tender]).to_csv(snapshot,index=False)
    monkeypatch.setattr(job,'SNAPSHOT_PATH',snapshot);monkeypatch.setattr(job,'STATUS_PATH',status)
    monkeypatch.setattr(job,'load_public_snapshot',lambda db:load_public_snapshot(snapshot,db))
    monkeypatch.setattr(job,'DEFAULT_QUERIES',['q']);monkeypatch.setattr(job,'GRANT_QUERIES',['q'])
    monkeypatch.setattr(job.time,'sleep',lambda _:None)
    for name in ('collect_crossref','collect_europe_pmc','collect_openalex','collect_nih_reporter','collect_gdelt_news','collect_rss'):
        monkeypatch.setattr(job,name,lambda *a,**kw:collectors.CollectionResult(rows,8,8,100))
    monkeypatch.setattr(job,'collect_ted_procurement',lambda *a,**kw:collectors.CollectionResult([],0,0,250))
    monkeypatch.delenv('SAM_GOV_API_KEY',raising=False)
    assert job.main()==0
    import json
    result=json.loads(status.read_text())
    assert len(result['collection_results'])==9
    assert len(pd.read_csv(snapshot))==9
    assert pd.read_csv(snapshot).query("source_type == 'procurement'").iloc[0].notice_status=='not_returned'
    assert (data/'observations.csv').exists() and (data/'predictions.csv').exists()
