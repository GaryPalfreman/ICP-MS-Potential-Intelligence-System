"""Auditable evidence support and benchmark evaluation; no invented ground truth."""
from __future__ import annotations
import hashlib
import json
import re
from datetime import date, datetime, timezone
from urllib.parse import urlparse
import pandas as pd
from .database import evidence_identity
from .quality import source_relevance, tender_state


def text_value(row, field):
    value = row.get(field, '')
    return '' if value is None or pd.isna(value) else str(value)


def evidence_key(row):
    return hashlib.sha256(json.dumps(evidence_identity(row), ensure_ascii=False).encode()).hexdigest()[:24]


def source_fingerprint(row):
    fields = ('title', 'summary', 'organization', 'response_deadline', 'notice_status', 'url')
    return hashlib.sha256(json.dumps([text_value(row, k) for k in fields]).encode()).hexdigest()


def support_passages(row):
    """Exact snippets from stored source fields, not generated explanations."""
    claims = {
        'ICP relevance': r'\bicp[\s–—-]*(?:ms|tof)\b|inductively coupled plasma|mass cytometry|\bcytof\b',
        'Installation wording (verify context)': r'installed|commissioned|now operational|installation',
        'Procurement wording (verify context)': r'tender|procurement|solicitation',
    }
    for field in ('instrument_vendor', 'instrument_model'):
        if text_value(row, field):
            claims[field + ' wording'] = re.escape(text_value(row, field))
    org = text_value(row, 'organization')
    if org:
        claims['Named organisation'] = re.escape(org)
    result = []
    for claim, pattern in claims.items():
        for field in ('title', 'summary'):
            value = text_value(row, field)
            match = re.search(pattern, value, re.I)
            if match:
                result.append({'claim': claim, 'field': field,
                               'passage': value[max(0, match.start()-90):min(len(value), match.end()+150)],
                               'url': text_value(row, 'url'),
                               'retrieved_at': text_value(row, 'last_seen_at') or 'Unknown (legacy record)'})
                break
    for field in ('organization', 'response_deadline', 'notice_status'):
        if text_value(row, field):
            result.append({'claim': field, 'field': 'Structured collector field', 'passage': text_value(row, field),
                           'url': text_value(row, 'url'), 'retrieved_at': text_value(row, 'last_seen_at') or 'Unknown (legacy record)'})
    return result


def corroboration_key(row):
    if text_value(row, 'source_type') == 'news':
        # Exact normalized headline groups are conservative; never claim verified syndication.
        title = re.sub(r'\s+[-–|]\s+[^-–|]+$', '', text_value(row, 'title'))
        title = re.sub(r'\W+', ' ', title.casefold()).strip()
        return 'news:' + title if title else evidence_key(row)
    return evidence_key(row)


def primary_source_status(row):
    if text_value(row, 'source_type') == 'news':
        return 'Original announcement not verified'
    return 'Structured record; individual claims require review'


def benchmark_candidates(frame, per_type=12):
    work = frame.copy().fillna('')
    if work.empty:
        return work
    work['evidence_key'] = work.apply(evidence_key, axis=1)
    work['fingerprint'] = work.apply(source_fingerprint, axis=1)
    # Stable stratified sample, including weak and explicit matches.
    work['stratum'] = work.apply(lambda r: f"{r.get('source_type', 'other')}:{source_relevance(str(r.get('title',''))+' '+str(r.get('summary',''))) >= .8}", axis=1)
    work = work.sort_values('evidence_key').groupby('stratum', group_keys=False).head(per_type)
    fields = ['evidence_key', 'fingerprint', 'title', 'summary', 'url', 'source_type', 'organization', 'response_deadline', 'notice_status']
    work = work.reindex(columns=fields, fill_value='')
    for field in ('expected_relevance', 'expected_organization', 'expected_tender_open', 'reviewer', 'reviewed_at', 'notes'):
        work[field] = ''
    return work


def benchmark_metrics(labels, frame, today=None):
    """Only explicit reviewed labels matching the exact current source version count."""
    current = {evidence_key(r): r for r in frame.fillna('').to_dict('records')}
    comparisons = {'relevance': [], 'organization': [], 'tender_open': []}
    excluded = 0
    for row in labels.fillna('').to_dict('records'):
        target = current.get(row.get('evidence_key'))
        if not target or not str(row.get('reviewer','')).strip() or not row.get('reviewed_at') or row.get('fingerprint') != source_fingerprint(target):
            excluded += 1
            continue
        predicted = {'relevance': 'yes' if source_relevance(text_value(target,'title')+' '+text_value(target,'summary')) >= .8 else 'no',
                     'organization': text_value(target,'organization').casefold().strip(),
                     'tender_open': 'yes' if tender_state(target, today) == 'Open' else 'no'}
        for task in comparisons:
            expected = str(row.get('expected_'+task, '')).strip().casefold()
            # Tender truth is date-sensitive. Older judgements must be reviewed again.
            if task == 'tender_open' and str(row['reviewed_at'])[:10] != (today or date.today()).isoformat():
                continue
            if task == 'organization' and expected == '[none]':
                expected = ''
            elif not expected:
                continue
            if task != 'organization' and expected not in {'yes', 'no'}:
                continue
            comparisons[task].append((expected, predicted[task]))
    metrics = []
    for task, pairs in comparisons.items():
        tp = sum(a == b == 'yes' for a,b in pairs)
        fp = sum(a == 'no' and b == 'yes' for a,b in pairs)
        fn = sum(a == 'yes' and b == 'no' for a,b in pairs)
        metrics.append({'task': task, 'reviewed_cases': len(pairs),
                        'accuracy': sum(a==b for a,b in pairs)/len(pairs) if pairs else None,
                        'precision': tp/(tp+fp) if tp+fp else None,
                        'recall': tp/(tp+fn) if tp+fn else None,
                        'false_positives': fp if task != 'organization' else None,
                        'false_negatives': fn if task != 'organization' else None})
    return pd.DataFrame(metrics), excluded


def retain_tender_history(snapshot, collected, source_succeeded, now=None):
    work = snapshot.copy()
    current = {r['url']: r for r in collected if r.get('source_name') == 'TED (EU procurement)'}
    for index, row in work.iterrows():
        if row.get('source_name') != 'TED (EU procurement)':
            continue
        if row.get('url') in current:
            for field in ('notice_status', 'response_deadline'):
                work.at[index, field] = current[row['url']].get(field, '')
        elif source_succeeded:
            # Absence from a capped search does NOT prove cancellation or award.
            work.at[index, 'notice_status'] = 'not_returned'
        if tender_state(work.loc[index], now) == 'Closed / due today':
            work.at[index, 'notice_status'] = 'closed'
    return work


def append_observations(frame, path, now=None):
    """Append daily first-observed facts without rewriting previous observations."""
    timestamp = now or datetime.now(timezone.utc).isoformat(timespec='seconds')
    rows = []
    for row in frame.fillna('').to_dict('records'):
        rows.append({'observed_at': timestamp, 'observation_day': timestamp[:10], 'evidence_key': evidence_key(row),
                     'fingerprint': source_fingerprint(row), 'organization': row.get('organization',''),
                     'signal_kind': row.get('signal_kind',''), 'notice_status': row.get('notice_status',''),
                     'response_deadline': row.get('response_deadline',''), 'published_date': row.get('published_date',''), 'url': row.get('url','')})
    old = pd.read_csv(path).fillna('') if path.exists() else pd.DataFrame()
    combined = pd.concat([old, pd.DataFrame(rows)], ignore_index=True)
    combined = combined.drop_duplicates(['observation_day','evidence_key','fingerprint'], keep='first')
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    return combined


def record_predictions(frame, path, now=None):
    """Freeze forward-looking research-priority scores; never manufacture probabilities."""
    from .scoring import organization_scores
    timestamp = now or datetime.now(timezone.utc).isoformat(timespec='seconds')
    ranked = organization_scores(frame)
    rows = ranked[['organization', 'opportunity_score', 'sales_stage']].copy()
    rows['prediction_date'] = timestamp[:10]
    rows['recorded_at'] = timestamp
    rows['horizon_days'] = 90
    rows['target'] = 'Later public procurement or installation signal'
    old = pd.read_csv(path) if path.exists() else pd.DataFrame()
    combined = pd.concat([old, rows], ignore_index=True).drop_duplicates(['organization','prediction_date'], keep='first')
    combined.to_csv(path, index=False)
    return combined


def prospective_outcomes(predictions, observations, today=None):
    """Only genuinely later first-observed evidence may satisfy a frozen prediction."""
    from .intelligence import canonical_organization
    today = pd.Timestamp(today or date.today(), tz='UTC')
    if predictions.empty:
        return pd.DataFrame()
    observed = observations.copy().fillna('')
    if not observed.empty:
        observed['time'] = pd.to_datetime(observed['observed_at'], utc=True, errors='coerce')
        observed = observed.sort_values('time').drop_duplicates('evidence_key', keep='first')
        observed['organization'] = observed['organization'].map(canonical_organization)
        observed['published'] = pd.to_datetime(observed.get('published_date', pd.Series(index=observed.index, dtype=str)), utc=True, errors='coerce')
    rows = []
    for row in predictions.to_dict('records'):
        start = pd.to_datetime(row['recorded_at'], utc=True)
        end = start + pd.Timedelta(int(row['horizon_days']), unit='D')
        hits = observed if observed.empty else observed[
            observed['organization'].eq(canonical_organization(row['organization'])) &
            observed['time'].gt(start) & observed['time'].le(min(end, today + pd.Timedelta(1, unit='D'))) &
            observed['published'].ge(start.normalize()) & observed['published'].le(today + pd.Timedelta(1, unit='D')) &
            observed['signal_kind'].isin(['Procurement', 'Instrument installation'])]
        state = 'Later public signal observed' if len(hits) else 'Pending' if today < end else 'No later signal observed (not a negative purchase label)'
        rows.append({**row, 'evaluation': state, 'supporting_url': hits.iloc[0]['url'] if len(hits) else ''})
    return pd.DataFrame(rows)
