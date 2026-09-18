from __future__ import annotations

import io
import json
import os
from datetime import date, datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from icpms_intel.collectors import (
    collect_crossref, collect_europe_pmc, collect_gdelt_news, collect_nih_reporter,
    collect_openalex, collect_rss, collect_sam_gov,
)
from icpms_intel.database import (
    add_outcome,
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
from icpms_intel.intelligence import calibration_metrics, daily_briefing, enrich_signals, trend_acceleration
from icpms_intel.reporting import intelligence_report, mirofish_seed_pack
from icpms_intel.scenario import ScenarioInputs, run_scenario, scenario_label
from icpms_intel.scoring import organization_scores, score_signals
from icpms_intel.seed import seed_database
from icpms_intel.snapshots import load_public_snapshot, read_update_status
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
    "Trends", "Review & Backtesting", "Scenario Lab", "Reports & Export", "Settings",
]
page = st.sidebar.radio("Workspace", pages)
st.sidebar.caption("Public evidence only · No confidential company data")

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
    c2.metric("Named organisations", f"{signals['organization'].fillna('').str.strip().ne('').sum():,}" if not signals.empty else "0")
    c3.metric("High-value signals", f"{(signals['opportunity_score'] >= 70).sum():,}" if not signals.empty else "0")
    c4.metric("Watch queries", f"{len(watch_queries()):,}")
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
    recent = signals[recent_dates >= pd.Timestamp(date.today()) - pd.Timedelta(days=7)].copy()
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
    available_sources = ["Crossref", "Europe PMC", "OpenAlex", "NIH RePORTER", "GDELT News"]
    if os.getenv("SAM_GOV_API_KEY"):
        available_sources.append("SAM.gov")
    sources = col3.multiselect("Sources", available_sources, default=["Crossref", "Europe PMC", "OpenAlex"])
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
    st.caption("SAM.gov tender collection becomes available when a free SAM_GOV_API_KEY is added to Streamlit secrets. AusTender, EU TED and other public portals can be monitored through their approved RSS/Atom feeds above.")

elif page == "Signals":
    hero("Search, review and add auditable market evidence.")
    search = st.text_input("Search evidence")
    display = signals
    if search and not display.empty:
        mask = display.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)
        display = display[mask]
    st.dataframe(
        display[["opportunity_score", "evidence_confidence", "title", "organization", "sales_stage", "sector", "region", "signal_kind", "recommended_product", "product_fit_confidence", "published_date", "source_name", "url"]],
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
    hero("Export the evidence, scenario results and a MiroFish-ready simulation package.")
    inputs = ScenarioInputs()
    sector_outlook, product_outlook = run_scenario(signals, inputs)
    report = intelligence_report(signals, prospects, sector_outlook, product_outlook)
    seed_pack = mirofish_seed_pack(signals, sector_outlook, product_outlook)
    st.subheader("Current intelligence summary")
    st.markdown(report[:8000])
    c1, c2, c3 = st.columns(3)
    c1.download_button("Download report", report, "ICP-MS_Potential_Intelligence_Report.md", "text/markdown", width="stretch")
    c2.download_button("Download MiroFish seed pack", seed_pack, "ICP-MS_MiroFish_Seed_Pack.json", "application/json", width="stretch")
    workbook = io.BytesIO()
    with pd.ExcelWriter(workbook, engine="xlsxwriter") as writer:
        signals.to_excel(writer, sheet_name="Evidence", index=False)
        prospects.to_excel(writer, sheet_name="Organisations", index=False)
        sector_outlook.to_excel(writer, sheet_name="Sector Outlook", index=False)
        product_outlook.to_excel(writer, sheet_name="Product Outlook", index=False)
    c3.download_button("Download analysis workbook", workbook.getvalue(), "ICP-MS_Intelligence.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")

elif page == "Settings":
    hero("System status, methodology and responsible-use controls.")
    st.subheader("System status")
    update_status = read_update_status()
    st.json({
        "version": "2.0.0",
        "database": "SQLite runtime store restored from repository-backed public snapshot",
        "scheduled_update": "Daily at 19:00 UTC (05:00 AEST / 06:00 AEDT)",
        "last_update": update_status or "Waiting for first scheduled run",
        "live_collectors": ["Crossref", "Europe PMC", "OpenAlex", "NIH RePORTER", "GDELT News", "RSS/Atom", "SAM.gov with free API key"],
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
    if st.button("Restore starter evidence"):
        inserted, skipped = seed_database()
        st.success(f"Added {inserted}; {skipped} already present.")
        st.rerun()
