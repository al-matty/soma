# Soma

A local-first personal health data pipeline that turns scattered lab report PDFs into a structured, queryable health record. A "biological digital twin" you fully own and control.

## Why

Most people accumulate lab reports from different providers over years, in different formats, with different units and reference ranges. The reports sit in folders or email attachments, making it hard to spot trends, compare values across time, or prepare meaningfully for a doctor's visit.

Soma fixes this by extracting biomarker data from your PDFs, standardizing everything to SI units, tracking changes over time, and generating clean markdown summaries. You can see at a glance which values are out of range, how they've trended, and whether a supplement or lifestyle change correlates with improvement.

Combined with a lifestyle and supplement profile, the generated knowledge base gives an LLM agent ("Dr. Claude") the full context it needs to reason about your health - flag patterns a single lab report wouldn't reveal, prepare pre-visit summaries for your doctor, or help you design and evaluate personal health experiments.

## Privacy

Soma does not send any data anywhere by default. All health data - biomarkers, genetic variants, profile files, generated reports - stays on your machine in a local DuckDB database and gitignored files. Nothing is committed to version control.

Cloud LLM usage (Anthropic API) is opt-in and only triggered when you explicitly run extraction commands. For sensitive documents like genetic reports, you can use `--method manual` to extract data without the PDF ever leaving your machine.

Genetic data is permanent and reveals information about your relatives. Biomarker panels can be re-identifying. Consider these risks before sending health data to any cloud provider. See [PRIVACY_DISCLAIMER.md](PRIVACY_DISCLAIMER.md) for a detailed discussion.

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

| Command | Description |
|---------|-------------|
| `extract` | Extract biomarkers from a PDF (API or manual) |
| `load` | Ingest JSON files into DuckDB |
| `transform` | Run dbt pipeline (seed, run, snapshot) |
| `render` | Generate profile markdown from dbt marts |
| `update-baseline` | Propose derived baseline updates via Claude |
| `status` | Show pipeline summary |
| `run` | Full pipeline: extract, load, transform, render |

## How It Works

1. **Extract** - Claude reads a lab report PDF and outputs structured JSON + a markdown summary
2. **Load** - JSON files are ingested into DuckDB raw tables (idempotent by source file)
3. **Transform** - dbt cleans, deduplicates, converts to SI units, and flags range compliance
4. **Render** - Generates markdown snapshots of your current biomarker status, timeline, and medical history

## Profile Layer

Copy templates from `profile/templates/` to `profile/` and fill in your data:

- `baseline.yml` - Static facts and agent-derived findings
- `lifestyle.yml` - Diet, exercise, sleep
- `supplements.yml` - Current and past supplements
- `medications.yml` - Current and past medications
- `experiments.yml` - Time-bounded health protocols
