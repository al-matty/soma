# Soma - Agent Data Reference

How to find and use the user's health data when answering questions, analyzing trends, or preparing recommendations.

## Quick Start

The fastest way to answer a health question is usually a SQL query against the marts layer:

```bash
python cli.py query "SELECT biomarker_key, value_si, unit_si, report_date, is_within_ref_range, is_within_optimal_range FROM main.fct_biomarkers ORDER BY report_date DESC, biomarker_key"
```

For richer context, combine SQL results with the profile YAMLs and generated markdown.

---

## Data Sources (by usefulness)

### 1. DuckDB Marts - structured biomarker data

The primary analytical layer. All values are SI-converted and range-flagged.

**`main.fct_biomarkers`** - one row per biomarker measurement

| Column | Description |
|--------|-------------|
| `biomarker_key` | Standardized name (e.g. "Vitamin D (25-OH)") |
| `value_si` | SI-converted numeric value |
| `unit_si` | SI unit |
| `value_raw` | Original value string (preserves `<0.1` etc.) |
| `report_date` | When the lab work was done |
| `provider` | Lab provider name |
| `category` | metabolic, lipid, hormonal, thyroid, vitamin, iron, inflammatory, liver, kidney, hematology |
| `is_within_ref_range` | true/false/null (provider reference range) |
| `is_within_optimal_range` | true/false/null (longevity-optimized range) |
| `reference_range_low_si`, `reference_range_high_si` | Provider ranges in SI |
| `optimal_range_low_si`, `optimal_range_high_si` | Optimal ranges from seed |
| `is_below_detection_limit` | true if value was e.g. `<0.1` |
| `source_file` | Original PDF filename |

**`main.dim_documents`** - one row per lab report

| Column | Description |
|--------|-------------|
| `source_file` | PDF filename |
| `report_date` | Report date |
| `provider` | Lab provider |
| `report_type` | blood_panel, genetics, radiology, specialist, prescription, other |
| `tags` | Comma-separated metadata tags |
| `biomarker_count` | Number of biomarkers in this report |

**`dim_biomarker_meta`** - reference table (40 biomarkers)

| Column | Description |
|--------|-------------|
| `biomarker_key` | Standardized name |
| `loinc_code` | LOINC identifier |
| `conventional_unit`, `si_unit` | Unit pair |
| `conversion_factor` | Multiply conventional by this to get SI |
| `category` | Biomarker category |
| `optimal_range_low_si`, `optimal_range_high_si` | Longevity-optimized range |

**`snapshots.snap_reference_ranges`** - SCD2 history of provider reference ranges (tracks when a lab changes its ranges)

### 2. Profile YAMLs - user context

All in `profile/`. Read these to understand who the user is and what they're doing.

| File | Contains |
|------|----------|
| `baseline.yml` | DOB, sex, height, blood type, allergies (static). Genetic variants, chronic patterns, conditions (derived). |
| `lifestyle.yml` | Diet, exercise, sleep habits |
| `supplements.yml` | Current and past supplements with doses and dates |
| `medications.yml` | Current and past medications with doses and dates |
| `experiments.yml` | Time-bounded health protocols with hypotheses and relevant biomarkers |

### 3. Generated Markdown - pre-rendered summaries

| File | Contains |
|------|----------|
| `docs/profile/current_snapshot.md` | Latest value per biomarker, grouped by category, with trend arrows and range flags |
| `docs/profile/timeline.md` | Chronological list of all reports |
| `docs/profile/medical_history.md` | Conditions, genetic variants, chronic patterns from baseline |
| `docs/profile/report_index.md` | Index of all reports with metadata and relative links to findings docs |
| `docs/findings/YYYY/*.md` | Per-report narrative summaries from extraction |

### 4. Raw JSON - extraction output

`data/raw/*.json` files contain the raw extraction results. Rarely needed directly since the marts layer has everything cleaned and converted. Useful if you need to inspect what Claude extracted before any transformation.

### 5. Document Summaries - clinical narrative

Each raw JSON file contains a `document_summary` key with a markdown-formatted clinical narrative. This includes diagnoses, imaging findings, treatment history, medication, and clinical recommendations - context that biomarker rows alone cannot provide.
```bash
python3 cli.py query "SELECT source_file, report_date, report_type, tags FROM main.dim_documents ORDER BY report_date"
```

Then read the corresponding JSON for narrative context:
```python
import json
from pathlib import Path
data = json.loads(Path("data/raw/<filename>.json").read_text())
print(data["document_summary"])
```

**Note:** Document summaries are not yet surfaced in the marts layer. You must read the raw JSON directly.

### 6. Environment isolation (`--env`)

All CLI commands accept a global `--env <name>` flag that redirects data to `data/envs/<name>/` (isolated DB, raw JSON, and findings). Use this to test new extraction methods or models without affecting production data.

```bash
python cli.py --env cli-test extract --pdf reports/bloodwork_2025.pdf
python cli.py --env cli-test load
python cli.py --env cli-test transform
python cli.py compare cli-test
```

The `compare` command uses DuckDB ATTACH to diff `fct_biomarkers` between production and the named environment, showing changed values, missing biomarkers, and environment-only biomarkers.

---

## Common Queries

**Latest value for each biomarker:**
```sql
SELECT biomarker_key, value_si, unit_si, report_date, category,
       is_within_ref_range, is_within_optimal_range
FROM main.fct_biomarkers
WHERE (biomarker_key, report_date) IN (
    SELECT biomarker_key, MAX(report_date)
    FROM main.fct_biomarkers GROUP BY biomarker_key
)
ORDER BY category, biomarker_key
```

**Trend for a specific biomarker over time:**
```sql
SELECT report_date, value_si, unit_si, provider,
       is_within_ref_range, is_within_optimal_range
FROM main.fct_biomarkers
WHERE biomarker_key = 'Vitamin D (25-OH)'
ORDER BY report_date
```

**All out-of-range values from most recent report:**
```sql
SELECT biomarker_key, value_si, unit_si, reference_range_low_si, reference_range_high_si
FROM main.fct_biomarkers
WHERE report_date = (SELECT MAX(report_date) FROM main.fct_biomarkers)
  AND is_within_ref_range = FALSE
ORDER BY biomarker_key
```

**Values outside optimal range (longevity targets):**
```sql
SELECT biomarker_key, value_si, unit_si,
       optimal_range_low_si, optimal_range_high_si, report_date
FROM main.fct_biomarkers
WHERE is_within_optimal_range = FALSE
ORDER BY report_date DESC, biomarker_key
```

**Report inventory:**
```sql
SELECT report_date, provider, report_type, biomarker_count, tags
FROM main.dim_documents
ORDER BY report_date DESC
```

**Category summary across all reports:**
```sql
SELECT category,
       COUNT(DISTINCT biomarker_key) AS unique_biomarkers,
       COUNT(DISTINCT report_date) AS report_count
FROM main.fct_biomarkers
GROUP BY category
ORDER BY category
```

---

## Important Details

- **Units are SI in the marts layer.** Raw/original units are in the staging layer and raw tables. If the user asks about a value in conventional units, convert back using `dim_biomarker_meta.conversion_factor`.
- **Detection limits:** Values like `<0.1` are stored as `value_si = 0.05` (half the limit) with `is_below_detection_limit = TRUE`. Always check the flag before interpreting low values literally.
- **Optimal vs reference ranges:** Reference ranges come from the lab provider. Optimal ranges come from the seed table and represent longevity-optimized targets - they're usually tighter.
- **PII redaction:** Before sending any data from this project to an external API, use `redact_pii()` from `redact.py` to replace PII with placeholders, and `restore_pii()` on the response.
- **Deduplication:** The staging layer deduplicates by (report_date, biomarker_name, provider), keeping the latest extraction.
- **All health data is gitignored.** The `data/`, `profile/*.yml`, `docs/findings/`, and `docs/profile/` directories never leave the local machine unless the user explicitly sends them.
- **Category coverage:** The `category` column in `fct_biomarkers` only populates for biomarkers matching the 40 keys in `biomarker_meta.csv`. Many extracted biomarkers (oral microbiome species, genetic markers, less common analytes) will have `category = NULL`. Don't rely on category-based filtering for completeness.
- **Document summaries in raw JSON:** The richest clinical context (diagnoses, imaging, recommendations) lives in `data/raw/*.json` under the `document_summary` key. The documented SQL path covers structured biomarker data; check the summaries when you need clinical narrative.