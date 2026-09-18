# 2.2.0 — Evidence verification and measurement

The release adds an Evidence & Accuracy workspace, source support passages, reviewer-attested original
announcement links, benchmark review/export/restore, per-query collection coverage, retained tender history,
and immutable daily research-priority snapshots with forward-only public-outcome tracking.

Research collection now requests up to 100 results per query and uses Europe PMC/OpenAlex abstracts.
Thirty DOI/URL-identified records were recovered from the pre-title-deduplication snapshot. The live run
received 2,223 records and inserted 1,089 additional identities. The release snapshot has 1,852 records after
excluding eight illustrative starter notes; it is not a count of confirmed purchase opportunities.

The initial benchmark contains 69 stratified, unlabelled real records. Accuracy remains unmeasured until
reviewers supply ground truth. Exact source snippets expose what is supported, but do not independently
verify claims. Original-announcement verification is a manual review workflow. No purchase probabilities
are advertised as calibrated.

Collection succeeded for Crossref, Europe PMC, OpenAlex, NIH RePORTER, public RSS and TED. GDELT timed out.
All 21 scientific query/source combinations reported more available records than were fetched. The new
coverage table exposes this bounded coverage; the dataset is not exhaustive. TED returned one active
notice. Historical recovery cannot establish that every previously lost record has been restored.

Production evidence/history remain repository-backed. Personal reviews remain in the Streamlit runtime
and require export for backup. Hosted redeployment must be confirmed separately from publication to GitHub.
