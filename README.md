# Soma - Your Biological Digital Twin

A local-first personal health data pipeline that turns scattered lab report PDFs into a structured, queryable health record. A "biological digital twin" you fully own and control. You'll have
* a well-structured local DuckDB database of all your recorded (and scanned) biomarkers
  - enables detailed tracking over time, longevity experiments, early alerts, etc.
* a docs folder with md files containing the medical narratives, doctors' statements, ...
  - provides the context around these biomarker rows (also one-off reports, findings, etc.)
* up to date artifacts (also md), like a data-driven history & a current snapshot of your biological state
  - are updated with `update-baseline` based on what's new in the db

Context is everything. Routinely dump your lab report PDFs into the data folder, and soma will set up a highly personalized knowledge base as ideal long-term infrastructure for health-related questions. Agent-friendly via CLI and docs ([AGENT_DATA_REFERENCE.md](AGENT_DATA_REFERENCE.md)), soma also opens up the possibility to run your own local agent specialized in giving you tailor-made medical advice, literally querying your biological facts while reasoning.

---

![Soma pipeline diagram](soma-diagram.png)

## Why

Most people accumulate lab reports from different providers over years, in different formats, with different units and reference ranges. The reports sit in folders or email attachments, making it hard to spot trends, compare values across time, or prepare meaningfully for a doctor's visit.

Soma fixes this by extracting biomarker data from your PDFs, standardizing everything to SI units, tracking changes over time, and generating clean markdown summaries. You can see at a glance which values are out of range, how they've trended, and whether a supplement or lifestyle change correlates with improvement.

Combined with a lifestyle and supplement profile, the generated knowledge base can provide an LLM agent the full context it needs to reason about your health - flag patterns a single lab report wouldn't reveal, prepare pre-visit summaries for your doctor, or help you design and evaluate personal health experiments.

## Privacy

Soma does not send any data anywhere by default. All health data - biomarkers, genetic variants, profile files, generated reports - stays on your machine in a local DuckDB database and gitignored files. Nothing is committed to version control.

Cloud LLM usage (Anthropic API) is opt-in and only triggered when you explicitly run the `extract` (part of `run`) or `update-baseline` command. When using the API, you can redact personal information (name, address, DOB, insurance IDs) before data is sent - copy `profile/templates/redact.template.yml` to `profile/redact.yml` and list the strings to redact. For PDFs, matches are blacked out in the copy sent to the API (the original file is never modified). For text-based API calls (like `update-baseline`), matches are replaced with `[REDACTED_N]` placeholders before sending and restored in the response so your local files keep the real values. For sensitive documents like genetic reports, you can use `--method manual` to extract data without the PDF ever leaving your machine.

For image-based PDFs (scanned or photographed documents), the software redaction in `redact.yml` may not catch all text reliably. The safest approach is to physically cover personal information - for example with small strips of paper - before scanning or photographing the document.

But keep in mind, genetic data in general is permanent and reveals information about your relatives. And biomarker panels can be re-identifying, redaction or not. Consider these risks before sending health data to any cloud provider, or use a local LLM. See [PRIVACY_DISCLAIMER.md](PRIVACY_DISCLAIMER.md) for a detailed discussion.

## Quick Start

```bash
# Set up environment
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy config files and add your API key
cp dbt_project/profiles.yml.example dbt_project/profiles.yml
cp .env.example .env  # then edit .env with your Anthropic API key

# Extract biomarkers from a lab report PDF
python cli.py extract --pdf /path/to/report.pdf

# Or run the full pipeline at once
python cli.py run --pdf /path/to/report.pdf
```

## Commands

### Ingest data

| Step | Command | Description |
|------|---------|-------------|
| 1-4 | **`run`** | **Full pipeline: extract, load, transform, render** |
| 1 | `extract` | Extract biomarkers from a PDF (API or manual) |
| 2 | `load` | Ingest JSON files into DuckDB |
| 3 | `transform` | Run dbt pipeline (seed, run, snapshot) |
| 4 | `render` | Generate profile markdown from dbt marts |
| (5) | `update-baseline` | Propose derived baseline updates via Claude |

### Query & maintain database

| Command | Description |
|---------|-------------|
| `status` | Show pipeline summary |
| `query` | Run a SQL query against DuckDB |
| `compare` | Compare biomarkers between a named environment and production |
| `reload` | Delete and re-load data for a source file |
| `reset` | Delete the database and start fresh |

Use `python cli.py <command> --help` to see options for any command, e.g. `python cli.py extract --help`.

## How It Works

1. **Extract** - Claude reads a lab report PDF and outputs structured JSON + a markdown summary
2. **Load** - JSON files are ingested into DuckDB raw tables (idempotent by source file)
3. **Transform** - dbt cleans, deduplicates, converts to SI units, and flags range compliance
4. **Render** - Generates markdown snapshots of your current biomarker status, timeline, and medical history

## Example Run

You set up your API key once, then run a single command:

```bash
python cli.py run --pdf /path/to/your_bloodwork.pdf
```

Without `--pdf`, `run` skips extraction and runs load -> transform -> render on existing JSON files in `data/raw/`. Useful for reprocessing after editing JSON or dbt models.

`run` chains four steps automatically:

**Step 1: Extract** - Reads your PDF, base64-encodes it, sends it to Claude Sonnet with the extraction prompt. Claude returns structured JSON (biomarker names, values, units, reference ranges, LOINC codes) and a markdown summary. Two files are written:
- `data/raw/2026-02-24_blood_panel_<provider>_<timestamp>.json` - the structured data
- `docs/findings/2026/2026-02-24_blood_panel_<provider>.md` - the narrative summary

**Step 2: Load** - Reads the JSON, validates it against the Pydantic schema, and inserts rows into DuckDB (`data/soma.duckdb`):
- `raw.lab_results` - one row per biomarker (value, unit, reference range, as-is from the report)
- `raw.documents` - one row for the report itself (date, provider, type, biomarker count)
- Idempotent by source file - if you run it again, it skips files whose source PDF has already been loaded. It is safe to leave all JSON files in `data/raw/` permanently

**Step 3: Transform** - dbt seed loads the 40-biomarker reference table with SI conversion factors. dbt run builds the analytical views:
- `stg_lab_results` - cleans values, parses detection limits (`<0.1` -> `0.05` + flag), deduplicates
- `fct_biomarkers` - joins with the seed, converts to SI units, flags values outside reference/optimal ranges
- `dim_documents` - document catalog
- dbt snapshot captures reference ranges for SCD2 tracking

**Step 4: Render** - Queries the dbt marts and generates three markdown files in `docs/profile/`:
- `current_snapshot.md` - latest value per biomarker, grouped by category, with trend arrows and range flags
- `timeline.md` - chronological list of all reports
- `medical_history.md` - conditions and findings from `profile/baseline.yml` (if it exists)

### What gets created

| Artifact | Type | Gitignored? |
|----------|------|-------------|
| `data/raw/<date>_<provider>_<time>.json` | New file | Yes |
| `docs/findings/2026/<date>_blood_panel_<provider>.md` | New file | Yes |
| `data/soma.duckdb` | Updated (new rows in raw tables, views refreshed) | Yes |
| `docs/profile/current_snapshot.md` | Regenerated | Yes |
| `docs/profile/timeline.md` | Regenerated | Yes |
| `docs/profile/medical_history.md` | Regenerated | Yes |

Profile YAMLs (`profile/*.yml`) are not touched by the pipeline. Those are only written by you (manually copying templates and filling in data) or by `soma update-baseline` (which calls Claude to propose derived findings, then asks you to approve the diff).

## Profile Layer

Copy templates from `profile/templates/` to `profile/` and fill in your data:

- `baseline.yml` - Static facts and agent-derived findings
- `lifestyle.yml` - Diet, exercise, sleep
- `supplements.yml` - Current and past supplements
- `medications.yml` - Current and past medications
- `experiments.yml` - Time-bounded health protocols
- `redact.yml` - PII strings to redact before API calls (PDFs and text)

## Data Access

Query the database directly from the CLI:

```bash
python cli.py query "SELECT * FROM fct_biomarkers WHERE report_date = '2026-02-24'"
python cli.py query "SELECT source_file, COUNT(*) FROM raw.lab_results GROUP BY source_file"
```

For interactive analysis in Python, load any table as a pandas DataFrame:

```python
import duckdb
con = duckdb.connect("data/soma.duckdb", read_only=True)
df = con.sql("SELECT * FROM fct_biomarkers").df()
```

For a complete reference of all tables, profile files, SQL patterns, and how to use the data programmatically, see [AGENT_DATA_REFERENCE.md](AGENT_DATA_REFERENCE.md).
