# ICP-MS Potential Intelligence System

A deployable public-data market-intelligence application for monitoring ICP-MS trends, identifying potential organisations, mapping demand signals to product families, testing predictions and exploring future scenarios.

It contains **no private company data or company branding**.

## What works

- Evidence-backed dashboard with source URLs
- Live collection from Crossref and Europe PMC
- Live collection from OpenAlex and NIH RePORTER
- Direct ICP-relevant procurement notices from the anonymous EU TED API
- Facility, hiring and installation announcements through GDELT public news
- Optional SAM.gov tender collection with a free API key
- RSS/Atom monitoring for approved public sources
- Manual and CSV evidence ingestion
- Automatic sector, signal and product-family classification
- Recency, credibility, relevance and purchasing-intent scoring
- DOI-first journal deduplication; distinct identifiers are never merged merely by title
- Organisation-level corroboration scoring
- Conservative organisation-name resolution
- Evidence confidence, sales-stage and product-fit explanations
- 90-day trend acceleration and a material-change daily briefing
- Human signal review and score adjustments
- Prediction outcome tracking with Brier-score calibration
- Conservative/expected/accelerated Monte Carlo scenarios
- Markdown, Excel, CSV and MiroFish-ready JSON exports
- SQLite persistence
- Automatic daily public-data refresh with a restart-safe repository snapshot
- Docker and Streamlit deployment support

## Quick start

### Python

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open <http://localhost:8501>.

### Docker

```bash
docker compose up --build
```

## Deploy on Streamlit Community Cloud

1. Create a GitHub repository and upload this project.
2. In Streamlit Community Cloud, select the repository.
3. Set the main file to `app.py`.
4. Deploy. No secret or paid API is required for the core system.

The included GitHub Actions workflow refreshes the public evidence snapshot every day at 19:00 UTC
(05:00 AEST / 06:00 AEDT in Melbourne) and can also be started manually from the repository's
**Actions** tab. Each successful snapshot commit triggers Streamlit Community Cloud to redeploy.

The repository snapshot preserves automatically collected public evidence across Streamlit restarts.
Manual entries, reviews and outcome observations made through the running Streamlit app remain local
to that runtime and can be exported as CSV. For durable multi-user editing, replace SQLite with managed
PostgreSQL and add authentication.

### Optional tender access

SAM.gov requires a free API key. Add it to Streamlit secrets as:

```toml
SAM_GOV_API_KEY = "your-key"
```

Add the same key as a GitHub Actions repository secret to include SAM.gov results in
the unattended daily snapshot. An optional `OPENALEX_MAILTO` secret identifies the
project to OpenAlex and improves free API reliability.

EU TED procurement monitoring is built in and requires no account or API key. It searches the official
mass-spectrometer procurement category, requires a future response deadline, and conservatively retains notices
with ICP, plasma or elemental-analysis evidence. Closed notices are removed by the next daily refresh. AusTender
publishes an official RSS URL, but it currently responds with HTTP 403 to this automated
environment and omits useful fields such as closing dates. The app therefore does not scrape AusTender pages or
claim unattended Australian tender coverage.

## Recommended workflow

1. Review the starter signals.
2. Use **Live Research** to collect current papers for the saved queries.
3. Add public tenders, grants, hiring notices and facility announcements.
4. Verify source URLs in **Signals**.
5. Review corroborated organisations.
6. Test assumptions in **Scenario Lab**.
7. Export the report, workbook or MiroFish seed pack.

## Intelligence model

### Accuracy-hardening release

Relevance and classification use source titles and summaries, never search terms.
Missing explicit ICP evidence is labelled for verification and receives a lower
relevance score; absence in an abstract is not proof of irrelevance. Existing
summaries may be truncated, and older title-only merges cannot be reconstructed
without recollecting their sources. DOI identity takes priority, followed by exact
source URL; identifier-free records use title, source and publication date.

An open tender requires an explicit active status and a deadline after today.
Due-today, expired and unverified notices are not counted as verified open tenders.
Multi-lot TED deadlines indicate that at least one lot remains open; verify the
specific ICP-MS lot before acting. Source outages retain prior evidence.

Runtime snapshot sync updates managed records when the repository snapshot changes,
preserving record IDs, reviews and manual entries. Removed managed records are
archived rather than deleted. Legacy untracked runtime rows remain preserved.
Confidence and product-fit scores remain heuristics—not calibrated probabilities.
Future-dated publications do not contribute to recent trend or briefing counts.

The application deliberately separates three concepts:

- **Evidence score** — strength, directness, recency and credibility of observed public evidence.
- **Opportunity and confidence** — a research-priority estimate plus an explanation of corroboration and completeness.
- **Scenario outlook** — conditional future cases; not a calibrated purchase probability.

The sales-stage funnel runs from research activity through funding, expansion, hiring, procurement,
installation and consumables demand. Direct tender and installation evidence outranks ordinary publication
activity. Human review can mark evidence as relevant, strong, duplicated or incorrectly classified.

The **Review & Backtesting** page records later public outcomes and calculates a Brier score. This allows
the assumed weights to be assessed over time instead of presenting permanently untested precision.

## Scoring

Signal score:

- 30% source credibility
- 25% ICP-MS relevance
- 30% purchasing-intent strength
- 15% recency

Organisation scoring combines up to six corroborating public signals. Scores indicate research priority only; they do not establish purchasing intent.

## Scenario model

The scenario engine runs 5,000 deterministic Monte Carlo trials around transparent sector-growth assumptions. A baseline index of 100 represents the present. Outputs are comparative opportunity indices with 10th–90th percentile ranges, not sales-volume or revenue promises.

## Public-data and privacy rules

- Retain a source URL for every factual claim.
- Separate verified facts, inferences and simulations.
- Do not upload confidential customer, employee or employer data.
- Do not infer sensitive personal characteristics.
- Verify prospective organisations before contact.
- Observe website terms and robots rules when adding new collectors.

## MiroFish

The **Reports & Export** page creates a domain-specific JSON seed pack containing:

- The prediction question
- Agent archetypes
- Simulation rules
- Sector and product outlooks
- Up to 200 evidence records

This can be supplied to a separately deployed MiroFish instance. MiroFish requires its own LLM and memory-service configuration; the core intelligence system does not.

## Test

```bash
pip install pytest xlsxwriter
pytest -q
```

## Disclaimer

This application is a research and decision-support tool. It does not provide financial advice, guarantee purchases, establish customer intent, or replace human technical and commercial review.
