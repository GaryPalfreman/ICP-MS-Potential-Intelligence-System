from __future__ import annotations
# MiroFish-compatible export and reproducible history archive

import io
import json
import os
from pathlib import Path
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from icpms_intel.collectors import (
    collect_crossref, collect_europe_pmc, collect_gdelt_news, collect_nih_reporter,
    collect_openalex, collect_rss, collect_sam_gov, collect_ted_procurement,
)
from icpms_intel.database import (
    add_outcome,
    benchmark_labels_df,
    save_benchmark_label,
    primary_reviews_df,
    save_primary_review,
    add_organization,
    add_watch_query,
    feedback_df,
    init_db,
    insert_signals,
    organizations_df,
    outcomes_df,
    save_feedback,
    signals_df,
    watch_queries,
)
from icpms_intel.verification import (
    support_passages, primary_source_status, benchmark_candidates, benchmark_metrics,
    evidence_key, source_fingerprint, prospective_outcomes,
)
from icpms_intel.intelligence import calibration_metrics, daily_briefing, enrich_signals, trend_acceleration
from icpms_intel.reporting import (
    DEFAULT_MIROFISH_QUESTION,
    intelligence_report,
    mirofish_archive_bundle,
    mirofish_seed_document,
)
from icpms_intel.scenario import ScenarioInputs, run_scenario, scenario_label
from icpms_intel.scoring import organization_scores, score_signals
from icpms_intel.seed import seed_database
from icpms_intel.snapshots import load_public_snapshot, read_update_status, sync_public_snapshot
from icpms_intel.taxonomy import PRODUCT_FAMILIES, SECTORS, SOURCE_CREDIBILITY, classify_product, classify_sector, classify_signal


st.set_page_config(page_title="ICP-MS Potential Intelligence System", page_icon="◉", layout="wide")

CUSTOM_CSS = """
<style>
.block-container {padding-top: 1.3rem; padding-bottom: 3rem;}
.hero {padding: 1.3rem 1.5rem; border: 1px solid #1d5362; border-radius: 18px;
background: linear-gradient(120deg, #0d2434 0%, #0b3138 100%); margin-bottom: 1rem;}
.hero h1 {margin:0; font-size:2rem; color:#f2ffff;}
.hero p {margin:.4rem 0 0; color:#a9ced1;}
.evidence {border-left: 3px solid #12B8B0; padding-left: .8rem; color:#b8d4d6;}
[data-testid="stMetric"] {background:#0d2231; border:1px solid #1b4251; padding:14px; border-radius:14px;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

init_db()
try:
    sync_public_snapshot()
except (ValueError, OSError) as exc:
    st.warning(f"Snapshot refresh unavailable; saved evidence retained: {exc}")
if signals_df().empty:
    load_public_snapshot()
if signals_df().empty:
    seed_database()


def hero(subtitle: str) -> None:
    st.markdown(
        f'<div class="hero"><h1>ICP-MS Potential Intelligence System</h1>'
        f'<p>{subtitle}</p></div>', unsafe_allow_html=True
    )


def filtered_signals() -> pd.DataFrame:
    df = enrich_signals(score_signals(signals_df()))
    if df.empty:
        return df
    feedback = feedback_df()
    if not feedback.empty:
        df = df.merge(feedback[["signal_id", "verdict", "notes"]], how="left", left_on="id", right_on="signal_id")
        df.loc[df["verdict"].eq("Strong purchase signal"), "opportunity_score"] = (
            df.loc[df["verdict"].eq("Strong purchase signal"), "opportunity_score"] + 7
        ).clip(upper=100)
        df.loc[df["verdict"].isin(["Not relevant", "Duplicate"]), "opportunity_score"] = 0
    else:
        df["verdict"] = ""
    sectors = st.sidebar.multiselect("Sector", sorted(df["sector"].dropna().unique()))
    regions = st.sidebar.multiselect("Region", sorted(df["region"].dropna().unique()))
    if sectors:
        df = df[df["sector"].isin(sectors)]
    if regions:
        df = df[df["region"].isin(regions)]
    return df


pages = [
    "Overview", "Daily Briefing", "Live Research", "Signals", "Potential Organisations",
    "Trends", "Evidence & Accuracy", "Review & Backtesting", "Scenario Lab", "Reports & Export", "Settings",
]
page = st.sidebar.radio("Workspace", pages)
st.sidebar.caption("Public evidence only · No confidential company data")
st.sidebar.caption("Scores are heuristic research priorities, not calibrated purchase probabilities.")

signals = filtered_signals()
orgs = organizations_df()
prospects = organization_scores(signals, orgs)

if page == "Overview":
    hero("Evidence-backed monitoring of ICP-MS markets, applications and potential purchasing signals.")
    update_status = read_update_status()
    if update_status.get("last_attempt_utc"):
        try:
            updated = datetime.fromisoformat(update_status["last_attempt_utc"]).strftime("%d %b %Y, %H:%M UTC")
        except ValueError:
            updated = update_status["last_attempt_utc"]
        if update_status.get("successful") and update_status.get("complete", True):
            st.caption(f"Daily public-data update: healthy · Last completed {updated}")
        elif update_status.get("successful"):
            st.caption(f"Daily public-data update: completed with temporary source warnings · {updated}")
        else:
            st.warning(f"The latest scheduled update completed with source warnings ({updated}). Existing evidence remains available.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Evidence signals", f"{len(signals):,}")
    named_organizations = signals.loc[
        signals["organization"].fillna("").str.strip().ne(""), "organization"
    ].nunique() if not signals.empty else 0
    c2.metric("Named organisations", f"{named_organizations:,}")
    c3.metric("High-value signals", f"{(signals['opportunity_score'] >= 70).sum():,}" if not signals.empty else "0")
    c4.metric("Verified open tenders", f"{signals['tender_status'].eq('Open').sum():,}" if not signals.empty else "0")
    brief = daily_briefing(signals)
    st.caption(
        f"Last 7 days: {brief['new_signals']} new public signals · "
        f"{brief['high_confidence']} high-confidence · {brief['active_tenders']} active-tender signals"
    )
    if not signals.empty:
        left, right = st.columns([1.2, 1])
        with left:
            sector_count = signals.groupby("sector").size().reset_index(name="Signals").sort_values("Signals")
            fig = px.bar(sector_count, x="Signals", y="sector", orientation="h", color="Signals", color_continuous_scale="Teal")
            fig.update_layout(title="Evidence by sector", coloraxis_showscale=False, height=430)
            st.plotly_chart(fig, width="stretch")
        with right:
            product_count = signals.groupby("product_family").size().reset_index(name="Signals")
            fig = px.pie(product_count, names="product_family", values="Signals", hole=.55)
            fig.update_layout(title="Product-family relevance", height=430, legend_title_text="")
            st.plotly_chart(fig, width="stretch")
        st.subheader("Highest-priority public signals")
        st.dataframe(
            signals[["opportunity_score", "evidence_confidence", "title", "sales_stage", "sector", "signal_kind", "recommended_product", "published_date", "source_name", "url"]]
            .sort_values("opportunity_score", ascending=False).head(12),
            width="stretch", hide_index=True,
            column_config={"url": st.column_config.LinkColumn("Evidence")}
        )

elif page == "Daily Briefing":
    hero("Only material changes and high-priority public signals from the latest collection cycle.")
    brief = daily_briefing(signals)
    a, b, c = st.columns(3)
    a.metric("New signals · 7 days", brief["new_signals"])
    b.metric("High-confidence signals", brief["high_confidence"])
    c.metric("Active tenders", brief["active_tenders"])
    left, right = st.columns(2)
    left.markdown("**Rising organisations**")
    left.write(brief["rising_organizations"] or "No named organisations in the latest window.")
    right.markdown("**Most active sectors**")
    right.write(brief["top_sectors"] or "No sector changes in the latest window.")
    recent_dates = pd.to_datetime(signals.get("published_date"), errors="coerce")
    recent = signals[recent_dates.between(pd.Timestamp(date.today()) - pd.Timedelta(days=7), pd.Timestamp(date.today()))].copy()
    if recent.empty:
        st.info("No newly published evidence was found in the last seven days.")
    else:
        st.dataframe(
            recent.sort_values(["stage_rank", "evidence_confidence", "opportunity_score"], ascending=False)[
                ["sales_stage", "evidence_confidence", "opportunity_score", "title", "organization", "sector", "recommended_product", "url"]
            ].head(50),
            width="stretch", hide_index=True, column_config={"url": st.column_config.LinkColumn("Evidence")},
        )

elif page == "Live Research":
    hero("Refresh the evidence base from public scientific indexes and approved RSS sources.")
    st.info("The built-in collectors use public APIs. Results are deduplicated and retain their original source URL.")
    query = st.text_input("Research query", value='"ICP-MS" battery')
    col1, col2, col3 = st.columns(3)
    days = col1.selectbox("Lookback", [365, 730, 1825, 3650], index=1, format_func=lambda x: f"{x // 365} year(s)")
    limit = col2.slider("Maximum per source", 10, 100, 40, 10)
    available_sources = ["Crossref", "Europe PMC", "OpenAlex", "NIH RePORTER", "TED Procurement", "GDELT News"]
    if os.getenv("SAM_GOV_API_KEY"):
        available_sources.append("SAM.gov")
    sources = col3.multiselect("Sources", available_sources, default=["Crossref", "Europe PMC", "OpenAlex", "TED Procurement"])
    if st.button("Collect public research", type="primary", width="stretch"):
        collected, errors = [], []
        with st.spinner("Collecting and classifying public evidence…"):
            for source in sources:
                try:
                    collectors = {
                        "Crossref": lambda: collect_crossref(query, days, limit),
                        "Europe PMC": lambda: collect_europe_pmc(query, days, limit),
                        "OpenAlex": lambda: collect_openalex(query, days, limit),
                        "NIH RePORTER": lambda: collect_nih_reporter(query, days, limit),
                        "TED Procurement": lambda: collect_ted_procurement(days, min(limit, 250)),
                        "GDELT News": lambda: collect_gdelt_news(query, limit),
                        "SAM.gov": lambda: collect_sam_gov(query, os.getenv("SAM_GOV_API_KEY", ""), min(days, 365), limit),
                    }
                    rows = collectors[source]()
                    collected.extend(rows)
                except Exception as exc:
                    errors.append(f"{source}: {exc}")
            inserted, skipped = insert_signals(collected)
            add_watch_query(query)
        st.success(f"Added {inserted} new signals; {skipped} duplicates skipped.")
        for error in errors:
            st.warning(error)
        st.rerun()
    st.divider()
    st.subheader("Monitor a public RSS feed")
    rss_url = st.text_input("RSS or Atom feed URL")
    rss_name = st.text_input("Source name", value="Public industry feed")
    if st.button("Collect RSS feed", disabled=not rss_url):
        try:
            rows = collect_rss(rss_url, rss_name)
            inserted, skipped = insert_signals(rows)
            st.success(f"Added {inserted} relevant items; {skipped} duplicates skipped.")
            st.rerun()
        except Exception as exc:
            st.error(f"Feed could not be collected: {exc}")
    with st.expander("Active watch queries"):
        st.write(watch_queries())
    st.caption("TED procurement works without an account or API key. SAM.gov remains optional. AusTender's official RSS endpoint currently blocks this automated environment, so the app does not claim unattended Australian coverage.")

elif page == "Signals":
    hero("Search, review and add auditable market evidence.")
    search = st.text_input("Search evidence")
    display = signals
    if search and not display.empty:
        mask = display.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
        display = display[mask]
    st.dataframe(
        display[["opportunity_score", "evidence_confidence", "relevance_basis", "title", "organization", "sales_stage", "tender_status", "response_deadline", "sector", "region", "signal_kind", "recommended_product", "product_fit_confidence", "published_date", "source_name", "url"]],
        width="stretch", hide_index=True,
        column_config={"url": st.column_config.LinkColumn("Evidence URL"), "opportunity_score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100)}
    )
    st.download_button("Download filtered evidence CSV", display.to_csv(index=False), "icpms_evidence.csv", "text/csv")
    with st.expander("Add a public signal manually"):
        with st.form("manual_signal"):
            title = st.text_input("Title")
            summary = st.text_area("Evidence summary")
            url = st.text_input("Public source URL")
            source_name = st.text_input("Source or publisher")
            organization = st.text_input("Organisation named in source")
            published = st.date_input("Published date", value=date.today())
            text = f"{title} {summary}"
            submitted = st.form_submit_button("Save signal")
            if submitted and title:
                kind = classify_signal(text)
                intent = {"Procurement": .95, "Instrument installation": .88, "Facility expansion": .8, "Hiring": .7, "Funding": .65}.get(kind, .3)
                insert_signals([{
                    "title": title, "summary": summary, "url": url, "source_name": source_name,
                    "source_type": "other", "published_date": published.isoformat(),
                    "sector": classify_sector(text), "region": "Global", "organization": organization,
                    "signal_kind": kind, "product_family": classify_product(text),
                    "credibility": SOURCE_CREDIBILITY["other"], "relevance": .7, "buying_intent": intent,
                }])
                st.success("Signal saved.")
                st.rerun()

elif page == "Potential Organisations":
    hero("Rank organisations using corroborated public evidence—not inferred personal data.")
    st.warning("A score indicates public evidence worth verifying. It does not confirm that an organisation intends to purchase.")
    if prospects.empty:
        st.info("No named organisations have been collected yet. Run Live Research or import public evidence.")
    else:
        st.dataframe(
            prospects, width="stretch", hide_index=True,
            column_config={
                "opportunity_score": st.column_config.ProgressColumn("Opportunity", min_value=0, max_value=100),
                "confidence": st.column_config.ProgressColumn("Confidence", min_value=0, max_value=100),
            }
        )
        st.caption("Opportunity combines public evidence strength; confidence measures source quality, completeness and corroboration. Neither confirms a purchase.")
    with st.expander("Add an organisation to the watchlist"):
        with st.form("add_org"):
            name = st.text_input("Organisation name")
            website = st.text_input("Public website")
            region = st.text_input("Region", value="Global")
            sector = st.selectbox("Sector", list(SECTORS) + ["General ICP-MS"])
            notes = st.text_area("Public-data research notes")
            if st.form_submit_button("Add to watchlist") and name:
                add_organization({"name": name, "website": website, "region": region, "sector": sector, "notes": notes})
                st.success("Organisation added.")
                st.rerun()
    st.subheader("Import public evidence")
    st.caption("Required column: title. Optional: summary, url, source_name, source_type, published_date, sector, region, organization, signal_kind, product_family, credibility, relevance, buying_intent.")
    uploaded = st.file_uploader("CSV evidence file", type=["csv"])
    if uploaded is not None:
        imported = pd.read_csv(uploaded).fillna("")
        if "title" not in imported.columns:
            st.error("The CSV must contain a title column.")
        elif st.button("Import CSV"):
            rows = []
            for row in imported.to_dict(orient="records"):
                text = f"{row.get('title', '')} {row.get('summary', '')}"
                row.setdefault("sector", classify_sector(text))
                row.setdefault("signal_kind", classify_signal(text))
                row.setdefault("product_family", classify_product(text))
                rows.append(row)
            inserted, skipped = insert_signals(rows)
            st.success(f"Imported {inserted}; skipped {skipped} duplicates.")
            st.rerun()

elif page == "Trends":
    hero("Detect acceleration without confusing raw publication volume with purchase intent.")
    trends = trend_acceleration(signals)
    if trends.empty:
        st.info("No dated evidence is available for trend analysis.")
    else:
        fig = px.bar(
            trends, x="acceleration", y="sector", orientation="h", color="momentum",
            hover_data=["last_90_days", "previous_90_days"],
            color_discrete_map={"Accelerating": "#12B8B0", "Stable": "#66808d", "Cooling": "#d9785f"},
        )
        fig.add_vline(x=1, line_dash="dash", line_color="#a9ced1")
        fig.update_layout(title="90-day signal acceleration", yaxis={"categoryorder": "total ascending"}, height=500)
        st.plotly_chart(fig, width="stretch")
        st.dataframe(trends, width="stretch", hide_index=True)
    st.markdown('<p class="evidence">Acceleration uses smoothed recent-versus-prior 90-day counts and requires minimum evidence before labelling a sector. It is a leading indicator, not a revenue forecast.</p>', unsafe_allow_html=True)

elif page == "Evidence & Accuracy":
    hero("Inspect claim support, measure reviewed classifications and track collection coverage.")
    support_tab, benchmark_tab, coverage_tab, history_tab = st.tabs([
        "Evidence support", "Reviewed benchmark", "Source coverage", "Tender & prediction history"])
    all_evidence = signals_df()
    with support_tab:
        if not signals.empty:
            selection = st.selectbox("Inspect evidence", signals['id'].tolist(),
                format_func=lambda value: str(signals.loc[signals['id'].eq(value), 'title'].iloc[0])[:140])
            selected = signals.loc[signals['id'].eq(selection)].iloc[0].fillna('').to_dict()
            st.write(selected['title'])
            st.caption(primary_source_status(selected))
            st.caption("Passages show wording in the stored record. They do not prove an installation, purchase, or exact product compatibility.")
            st.dataframe(pd.DataFrame(support_passages(selected)), hide_index=True, width="stretch")
            st.text(selected.get('summary', ''))
            st.link_button("Read source", selected['url'], disabled=not bool(selected['url']))
            st.caption(f"First retrieved: {selected.get('first_seen_at') or 'Unknown (legacy)'} · Last retrieved: {selected.get('last_seen_at') or 'Unknown (legacy)'}")
            if selected.get('source_type') == 'news':
                related = signals[signals['corroboration_group'].eq(selected['corroboration_group'])]
                st.write(f"{len(related)} stored news record(s) share this normalized headline; counted once for corroboration.")
                st.caption("Original-announcement verification is manual. Similar headlines do not establish that two sources are independent.")
                primary = primary_reviews_df()
                previous = primary[primary['signal_id'].eq(selection)]
                if not previous.empty:
                    st.dataframe(previous, hide_index=True, width='stretch')
                with st.form('original_source_review'):
                    original_url = st.text_input('Original announcement URL')
                    original_passage = st.text_area('Exact supporting passage from the original announcement')
                    original_reviewer = st.text_input('Source reviewer')
                    confirmed = st.checkbox('I opened the original source and verified this passage')
                    if st.form_submit_button('Save original-source review'):
                        if confirmed:
                            try:
                                save_primary_review(selection, original_url, original_passage, original_reviewer)
                                st.rerun()
                            except ValueError as exc:
                                st.error(str(exc))
                        else:
                            st.error('Verify the original announcement before saving.')
                if not primary.empty:
                    st.download_button('Export original-source reviews', primary.to_csv(index=False), 'ICP-MS_original_source_reviews.csv', 'text/csv')
                st.caption('Original-source reviews are reviewer attestations, not automatic fact checks. Export local reviews before a runtime reset.')
    with benchmark_tab:
        st.info("No accuracy percentage is claimed without reviewed labels. This benchmark measures the reviewed sample, not the entire market or purchase probability.")
        labels = benchmark_labels_df()
        metrics, excluded = benchmark_metrics(labels, all_evidence)
        st.dataframe(metrics, hide_index=True, width="stretch")
        st.caption(f"{excluded} stale, missing or unsigned labels excluded. Tender labels must be reviewed on the evaluation date. Blank labels are unknown, never negative.")
        candidates = benchmark_candidates(all_evidence)
        st.download_button("Download stratified benchmark template", candidates.to_csv(index=False), "ICP-MS_benchmark_template.csv", "text/csv")
        if not all_evidence.empty:
            options = all_evidence['id'].tolist()
            selected_id = st.selectbox("Benchmark evidence", options, format_func=lambda value: str(all_evidence.loc[all_evidence['id'].eq(value), 'title'].iloc[0])[:140])
            row = all_evidence.loc[all_evidence['id'].eq(selected_id)].iloc[0].fillna('').to_dict()
            st.write(row['title'])
            st.text(row.get('summary',''))
            st.link_button("Check benchmark source", row['url'], disabled=not bool(row['url']))
            with st.form('benchmark_review'):
                reviewer = st.text_input('Reviewer name')
                relevant = st.selectbox('Does the source explicitly support ICP relevance?', ['', 'yes', 'no'])
                expected_org = st.text_input('Correct organisation (blank = unreviewed; [none] = no organisation supported)')
                expected_open = st.selectbox('Is this an open tender today?', ['', 'yes', 'no'])
                notes = st.text_area('Supporting passage / review notes')
                checked = st.checkbox('I reviewed the source and these labels')
                if st.form_submit_button('Save benchmark review'):
                    if reviewer.strip() and checked and any((relevant, expected_org, expected_open)):
                        save_benchmark_label({**row, 'reviewer': reviewer, 'expected_relevance': relevant,
                            'expected_organization': expected_org, 'expected_tender_open': expected_open, 'notes': notes})
                        st.rerun()
                    else:
                        st.error('Enter a reviewer, review confirmation and at least one label.')
        if not labels.empty:
            st.download_button('Export benchmark reviews', labels.to_csv(index=False), 'ICP-MS_benchmark_reviews.csv', 'text/csv')
        st.caption('Reviews are stored in this runtime database. Export them before a restart; repository snapshots do not back up private reviews.')
        uploaded = st.file_uploader('Restore benchmark review export', type=['csv'], key='benchmark_import')
        if uploaded is not None and st.button('Restore reviewed labels'):
            from icpms_intel.database import connection
            imported = pd.read_csv(uploaded).fillna('')
            required = {'evidence_key', 'fingerprint', 'reviewer', 'reviewed_at'}
            if not required.issubset(imported.columns):
                st.error('Not a benchmark review export.')
            else:
                current = {evidence_key(r): source_fingerprint(r) for r in all_evidence.fillna('').to_dict('records')}
                count = 0
                with connection() as conn:
                    for item in imported.to_dict('records'):
                        if current.get(item['evidence_key']) == item['fingerprint'] and item['reviewer'] and item['reviewed_at']:
                            conn.execute('INSERT INTO benchmark_labels VALUES (?,?) ON CONFLICT(evidence_key) DO UPDATE SET payload=excluded.payload', (item['evidence_key'], json.dumps(item)))
                            count += 1
                st.success(f'Restored {count} matching reviews; unchanged review dates retained.')
    with coverage_tab:
        status = read_update_status()
        reports = status.get('collection_results', [])
        st.caption('Each row is one source/query attempt. A successful bounded search does not guarantee complete coverage. Zero matches and request failures are different outcomes.')
        if reports:
            st.dataframe(pd.DataFrame(reports), hide_index=True, width='stretch')
            st.download_button('Export source coverage', pd.DataFrame(reports).to_csv(index=False), 'ICP-MS_source_coverage.csv', 'text/csv')
            last = pd.to_datetime(status.get('last_success_utc'), utc=True, errors='coerce')
            if pd.isna(last) or pd.Timestamp.now(tz='UTC') - last > pd.Timedelta(hours=36):
                st.warning('No successful collection confirmed within the last 36 hours.')
        else:
            st.info('Per-query coverage will appear after the next upgraded daily collection.')
    with history_tab:
        tenders = signals[signals['signal_kind'].eq('Procurement')]
        st.subheader('Retained procurement records')
        st.dataframe(tenders.reindex(columns=['title','organization','tender_status','notice_status','response_deadline','url']), hide_index=True, width='stretch')
        st.caption('Not returned means absent from the latest bounded search; it does not mean awarded or cancelled. Deadline expiry excludes an item from active opportunities.')
        observation_path = Path('data/observations.csv')
        prediction_path = Path('data/predictions.csv')
        if observation_path.exists() and prediction_path.exists():
            observations = pd.read_csv(observation_path)
            predictions = pd.read_csv(prediction_path)
            st.subheader('Forward-only outcome tracking')
            st.dataframe(prospective_outcomes(predictions, observations), hide_index=True, width='stretch')
            st.caption('90-day research-priority snapshots are frozen at collection time. Only later first-observed public signals count. No observed signal is not proof of no purchase. Scores are not probabilities.')
            st.download_button('Export frozen predictions', predictions.to_csv(index=False), 'ICP-MS_predictions.csv', 'text/csv')
            st.download_button('Export observation history', observations.to_csv(index=False), 'ICP-MS_observations.csv', 'text/csv')
        else:
            st.info('Forward-only history starts with the upgraded collector; earlier predictions are not fabricated.')

elif page == "Review & Backtesting":
    hero("Improve classifications with human review and test whether earlier predictions produced observable outcomes.")
    review_tab, outcome_tab = st.tabs(["Signal review", "Outcome calibration"])
    with review_tab:
        candidates = signals.sort_values(["opportunity_score", "evidence_confidence"], ascending=False).head(250)
        if candidates.empty:
            st.info("No signals are available to review.")
        else:
            options = {f"#{int(row.id)} · {row.title[:100]}": int(row.id) for row in candidates.itertuples()}
            label = st.selectbox("Evidence signal", list(options))
            selected_id = options[label]
            selected = candidates[candidates["id"] == selected_id].iloc[0]
            st.write(selected["title"])
            st.caption(f"{selected['source_name']} · {selected['published_date']} · {selected['sales_stage']} · confidence {selected['evidence_confidence']}%")
            st.link_button("Open original evidence", selected["url"], disabled=not bool(selected["url"]))
            verdict = st.selectbox("Review verdict", ["Relevant", "Strong purchase signal", "Not relevant", "Wrong organisation", "Wrong product family", "Duplicate", "Monitor"])
            notes = st.text_area("Reviewer notes")
            if st.button("Save review", type="primary"):
                save_feedback(selected_id, verdict, notes)
                st.success("Review saved and applied to the opportunity score.")
                st.rerun()
        feedback = feedback_df()
        if not feedback.empty:
            st.download_button("Export review history", feedback.to_csv(index=False), "ICP-MS_signal_reviews.csv", "text/csv")
    with outcome_tab:
        st.info("Manually entered historical probabilities are retrospective diagnostics, not validated forecasts. Forward-only observations are in Evidence & Accuracy.")
        history = outcomes_df()
        metrics = calibration_metrics(history)
        a, b, c = st.columns(3)
        a.metric("Evaluated predictions", metrics["evaluated"])
        b.metric("Brier score · lower is better", metrics["brier_score"] if metrics["brier_score"] is not None else "Waiting")
        c.metric("Threshold accuracy", f"{metrics['accuracy']}%" if metrics["accuracy"] is not None else "Waiting")
        with st.form("record_outcome"):
            st.markdown("**Record a public outcome**")
            organization = st.text_input("Organisation")
            prediction_date = st.date_input("Prediction date", value=date.today())
            probability = st.slider("Prediction probability at that time", 0, 100, 50)
            predicted_stage = st.selectbox("Predicted stage", ["Research activity", "Funding received", "Laboratory expansion", "ICP-MS hiring", "Procurement planning", "Active tender", "Instrument installation", "Consumables opportunity"])
            observed = st.selectbox("Observable outcome", ["Pending", "Occurred", "Did not occur"])
            outcome_type = st.selectbox("Outcome type", ["", "Tender", "Grant", "Facility opening", "Instrument installation", "Continued ICP-MS activity", "No observable outcome"])
            outcome_date = st.date_input("Outcome/check date", value=date.today())
            evidence_url = st.text_input("Public evidence URL")
            outcome_notes = st.text_area("Outcome notes")
            if st.form_submit_button("Save outcome") and organization:
                add_outcome({
                    "organization": organization, "prediction_date": prediction_date.isoformat(),
                    "predicted_probability": probability, "predicted_stage": predicted_stage,
                    "outcome_date": outcome_date.isoformat(),
                    "outcome_observed": None if observed == "Pending" else int(observed == "Occurred"),
                    "outcome_type": outcome_type, "evidence_url": evidence_url, "notes": outcome_notes,
                })
                st.success("Outcome saved for future calibration.")
                st.rerun()
        if not history.empty:
            st.dataframe(history, width="stretch", hide_index=True, column_config={"evidence_url": st.column_config.LinkColumn("Evidence")})
            st.download_button("Export outcome history", history.to_csv(index=False), "ICP-MS_prediction_outcomes.csv", "text/csv")

elif page == "Scenario Lab":
    hero("Test conservative, expected and accelerated ICP-MS market conditions.")
    a, b, c, d = st.columns(4)
    horizon = a.select_slider("Horizon", [1, 2, 3, 5], value=2, format_func=lambda x: f"{x} years")
    macro = b.slider("Capital investment", .70, 1.30, 1.0, .05)
    regulation = c.slider("Regulatory demand", .70, 1.30, 1.0, .05)
    technology = d.slider("ICP-MS adoption", .70, 1.30, 1.0, .05)
    inputs = ScenarioInputs(horizon, macro, regulation, technology)
    sector_outlook, product_outlook = run_scenario(signals, inputs)
    st.caption(
        f"Scenario: {scenario_label((macro + regulation + technology) / 3)} · "
        "Baseline index = 100 · 5,000 deterministic Monte Carlo trials"
    )
    left, right = st.columns(2)
    with left:
        fig = px.bar(sector_outlook.head(10), x="Expected index", y="Sector", orientation="h", error_x="High (90%)")
        fig.update_layout(title="Sector opportunity index", yaxis={"categoryorder": "total ascending"}, height=480)
        st.plotly_chart(fig, width="stretch")
    with right:
        fig = px.bar(product_outlook, x="Expected opportunity index", y="Product family", orientation="h")
        fig.update_layout(title="Product-family opportunity", yaxis={"categoryorder": "total ascending"}, height=480)
        st.plotly_chart(fig, width="stretch")
    st.subheader("Sector outlook with uncertainty")
    st.dataframe(sector_outlook, width="stretch", hide_index=True)
    st.markdown('<p class="evidence">These indices compare relative opportunity under explicit assumptions. They are not unit-sales or revenue forecasts.</p>', unsafe_allow_html=True)

elif page == "Reports & Export":
    hero("Export evidence, scenario results and a replayable MiroFish simulation package.")
    inputs = ScenarioInputs()
    sector_outlook, product_outlook = run_scenario(signals, inputs)
    report = intelligence_report(signals, prospects, sector_outlook, product_outlook)
    st.subheader("MiroFish simulation question")
    simulation_question = st.text_area(
        "What should the agents explore?",
        value=DEFAULT_MIROFISH_QUESTION,
        height=120,
        help="This is included in the seed document and saved separately for pasting into MiroFish.",
    )
    seed_document = mirofish_seed_document(
        signals, sector_outlook, product_outlook, simulation_question
    )
    histories = {
        "signal_reviews": feedback_df(),
        "primary_source_reviews": primary_reviews_df(),
        "benchmark_labels": benchmark_labels_df(),
        "prediction_outcomes": outcomes_df(),
    }
    for archive_name, archive_path in (
        ("observations", Path("data/observations.csv")),
        ("predictions", Path("data/predictions.csv")),
    ):
        if archive_path.exists():
            histories[archive_name] = pd.read_csv(archive_path)
    archive_bundle = mirofish_archive_bundle(
        signals, sector_outlook, product_outlook, simulation_question, histories
    )
    st.subheader("Current intelligence summary")
    st.markdown(report[:8000])
    st.info(
        "In MiroFish, create a project, upload the Markdown seed, and paste the saved simulation "
        "requirement. Keep the ZIP as the dated audit and recovery copy for that run."
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.download_button("Download report", report, "ICP-MS_Potential_Intelligence_Report.md", "text/markdown", width="stretch")
    c2.download_button("Download MiroFish seed", seed_document, "ICP-MS_MiroFish_Seed.md", "text/markdown", width="stretch")
    c3.download_button("Download history archive", archive_bundle, "ICP-MS_MiroFish_History.zip", "application/zip", width="stretch")
    workbook = io.BytesIO()
    with pd.ExcelWriter(workbook, engine="xlsxwriter") as writer:
        signals.to_excel(writer, sheet_name="Evidence", index=False)
        prospects.to_excel(writer, sheet_name="Organisations", index=False)
        sector_outlook.to_excel(writer, sheet_name="Sector Outlook", index=False)
        product_outlook.to_excel(writer, sheet_name="Product Outlook", index=False)
    c4.download_button("Download analysis workbook", workbook.getvalue(), "ICP-MS_Intelligence.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")

elif page == "Settings":
    hero("System status, methodology and responsible-use controls.")
    st.subheader("System status")
    update_status = read_update_status()
    st.json({
        "version": "2.3.0",
        "database": "SQLite runtime store restored from repository-backed public snapshot",
        "scheduled_update": "Daily at 19:00 UTC (05:00 AEST / 06:00 AEDT)",
        "last_update": update_status or "Waiting for first scheduled run",
        "live_collectors": ["Crossref", "Europe PMC", "OpenAlex", "NIH RePORTER", "TED Procurement (no key)", "GDELT News", "RSS/Atom", "SAM.gov with free API key"],
        "paid_API_required": False,
        "evidence_signals": len(signals_df()),
        "reviewed_signals": len(feedback_df()),
        "backtest_outcomes": len(outcomes_df()),
    })
    st.subheader("Scoring methodology")
    st.markdown(
        """
        Each signal is scored from source credibility, ICP-MS relevance, purchasing-intent strength and recency.
        Multiple independent signals increase an organisation's opportunity score, while the interface continues
        to label the result as a hypothesis requiring verification.

        **Responsible-use rules**

        - Use public organisational information only.
        - Do not infer sensitive characteristics about individuals.
        - Keep facts, model assumptions and scenarios visibly separate.
        - Verify sources before any commercial decision or contact.
        - Do not interpret the opportunity index as promised revenue.
        """
    )
    if st.button("Restore default watch queries"):
        inserted, skipped = seed_database()
        st.success(f"Added {inserted}; {skipped} already present.")
        st.rerun()
