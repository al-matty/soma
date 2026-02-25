"""Profile markdown renderer - generates docs from dbt marts."""

import os
from datetime import date
from pathlib import Path

import duckdb

from config import DB_PATH, PROFILE_DIR, PROFILE_DOCS_DIR


def _query(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    """Run a query and return results as list of dicts."""
    result = con.execute(sql)
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def render_current_snapshot(con: duckdb.DuckDBPyConnection) -> str:
    """Generate current_snapshot.md - latest value for each biomarker with trends."""
    rows = _query(con, """
        with latest as (
            select
                biomarker_key,
                value_si,
                unit_si,
                value_original,
                unit_original,
                report_date,
                provider,
                category,
                is_within_ref_range,
                is_within_optimal_range,
                is_below_detection_limit,
                row_number() over (
                    partition by biomarker_key
                    order by report_date desc
                ) as rn
            from main.fct_biomarkers
        ),
        previous as (
            select
                biomarker_key,
                value_si,
                report_date,
                row_number() over (
                    partition by biomarker_key
                    order by report_date desc
                ) as rn
            from main.fct_biomarkers
        )
        select
            l.biomarker_key,
            l.value_si,
            l.unit_si,
            l.value_original,
            l.unit_original,
            l.report_date,
            l.provider,
            l.category,
            l.is_within_ref_range,
            l.is_within_optimal_range,
            l.is_below_detection_limit,
            p.value_si as prev_value_si,
            p.report_date as prev_date
        from latest l
        left join previous p
            on l.biomarker_key = p.biomarker_key and p.rn = 2
        where l.rn = 1
        order by l.category, l.biomarker_key
    """)

    lines = [
        "# Current Biomarker Snapshot",
        f"*Generated: {date.today()}*",
        "",
    ]

    current_category = None
    for r in rows:
        if r["category"] != current_category:
            current_category = r["category"]
            cat_label = (current_category or "uncategorized").title()
            lines.extend(["", f"## {cat_label}", ""])
            lines.append("| Biomarker | Value (SI) | Original | Date | Status | Trend |")
            lines.append("|-----------|-----------|----------|------|--------|-------|")

        # Trend arrow
        trend = ""
        if r["prev_value_si"] is not None and r["value_si"] is not None:
            diff = r["value_si"] - r["prev_value_si"]
            pct = abs(diff / r["prev_value_si"]) * 100 if r["prev_value_si"] != 0 else 0
            if pct < 3:
                trend = "-"
            elif diff > 0:
                trend = "^"
            else:
                trend = "v"

        # Status
        if r["is_below_detection_limit"]:
            status = "BDL"
        elif r["is_within_optimal_range"] is True:
            status = "Optimal"
        elif r["is_within_ref_range"] is True:
            status = "Normal"
        elif r["is_within_ref_range"] is False:
            status = "**OUT**"
        else:
            status = "-"

        val_si = f"{r['value_si']:.2f}" if r["value_si"] is not None else "-"
        original = f"{r['value_original']} {r['unit_original']}"

        lines.append(
            f"| {r['biomarker_key']} | {val_si} {r['unit_si']} "
            f"| {original} | {r['report_date']} | {status} | {trend} |"
        )

    lines.append("")
    return "\n".join(lines)


def render_timeline(con: duckdb.DuckDBPyConnection) -> str:
    """Generate timeline.md - chronological encounter summary."""
    docs = _query(con, """
        select
            report_date,
            provider,
            report_type,
            source_file,
            biomarker_count,
            tags
        from main.dim_documents
        order by report_date desc
    """)

    lines = [
        "# Report Timeline",
        f"*Generated: {date.today()}*",
        "",
        f"Total reports: {len(docs)}",
        "",
    ]

    for d in docs:
        tags = f" [{d['tags']}]" if d["tags"] else ""
        lines.append(
            f"- **{d['report_date']}** - {d['report_type']} "
            f"({d['provider']}, {d['biomarker_count']} biomarkers){tags}"
        )

    lines.append("")
    return "\n".join(lines)


def render_medical_history(con: duckdb.DuckDBPyConnection) -> str:
    """Generate medical_history.md from baseline.yml and document metadata."""
    import yaml

    lines = [
        "# Medical History",
        f"*Generated: {date.today()}*",
        "",
    ]

    # Load baseline if it exists
    baseline_path = PROFILE_DIR / "baseline.yml"
    if baseline_path.exists():
        baseline = yaml.safe_load(baseline_path.read_text()) or {}
        derived = baseline.get("derived", {})

        if derived.get("conditions"):
            lines.extend(["## Conditions", ""])
            for c in derived["conditions"]:
                status = c.get("status", "unknown")
                lines.append(f"- **{c['name']}** ({status}) - discovered {c.get('discovered_date', 'unknown')}")
            lines.append("")

        if derived.get("genetic_variants"):
            lines.extend(["## Genetic Variants", ""])
            for g in derived["genetic_variants"]:
                lines.append(f"- **{g['finding']}**")
                lines.append(f"  - Implication: {g.get('implication', '-')}")
                lines.append(f"  - Relevance: {g.get('relevance', '-')}")
            lines.append("")

        if derived.get("chronic_patterns"):
            lines.extend(["## Chronic Patterns", ""])
            for p in derived["chronic_patterns"]:
                lines.append(f"- {p['finding']} (last confirmed: {p.get('last_confirmed', 'unknown')})")
            lines.append("")
    else:
        lines.extend([
            "No baseline profile found. Copy `profile/templates/baseline.template.yml` "
            "to `profile/baseline.yml` and fill in your data.",
            "",
        ])

    # Add document-sourced info
    docs = _query(con, """
        select report_date, provider, report_type, tags
        from main.dim_documents
        order by report_date
    """)

    if docs:
        lines.extend(["## Report Sources", ""])
        for d in docs:
            lines.append(f"- {d['report_date']}: {d['report_type']} ({d['provider']})")
        lines.append("")

    return "\n".join(lines)


def render_report_index(con: duckdb.DuckDBPyConnection) -> str:
    """Generate report_index.md - links profile docs to per-report findings."""
    rows = _query(con, """
        select
            d.report_date,
            d.provider,
            d.report_type,
            d.biomarker_count,
            d.tags,
            d.markdown_path,
            count(case when f.is_within_ref_range = false then 1 end) as out_of_range_count
        from main.dim_documents d
        left join main.fct_biomarkers f
            on d.source_file = f.source_file
        group by d.report_date, d.provider, d.report_type,
                 d.biomarker_count, d.tags, d.markdown_path
        order by d.report_date desc
    """)

    lines = [
        "# Report Index",
        f"*Generated: {date.today()}*",
        "",
        f"Total reports: {len(rows)}",
        "",
        "| Date | Type | Provider | Biomarkers | Out of Range | Tags | Findings |",
        "|------|------|----------|------------|--------------|------|----------|",
    ]

    for r in rows:
        tags = r["tags"] or ""
        oor = r["out_of_range_count"]

        # Build relative link from docs/profile/ to the findings doc
        link = ""
        if r["markdown_path"]:
            rel = os.path.relpath(r["markdown_path"], "docs/profile")
            filename = Path(r["markdown_path"]).stem
            link = f"[{filename}]({rel})"

        lines.append(
            f"| {r['report_date']} | {r['report_type']} | {r['provider']} "
            f"| {r['biomarker_count']} | {oor} | {tags} | {link} |"
        )

    lines.append("")
    return "\n".join(lines)


def render_all(db_path: Path = DB_PATH) -> list[str]:
    """Generate all profile markdown files. Returns list of paths written."""
    con = duckdb.connect(str(db_path))

    try:
        PROFILE_DOCS_DIR.mkdir(parents=True, exist_ok=True)

        paths = []
        for filename, renderer in [
            ("current_snapshot.md", render_current_snapshot),
            ("timeline.md", render_timeline),
            ("medical_history.md", render_medical_history),
            ("report_index.md", render_report_index),
        ]:
            content = renderer(con)
            path = PROFILE_DOCS_DIR / filename
            path.write_text(content)
            paths.append(str(path))

        return paths
    finally:
        con.close()
