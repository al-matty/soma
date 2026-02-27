"""Baseline updater - proposes derived baseline updates via Claude."""

import difflib
import json
import sys

import duckdb
import yaml

from config import ANTHROPIC_API_KEY, DB_PATH, EXTRACTION_MODEL, PROFILE_DIR, PROMPTS_DIR


def _query(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    """Run a query and return results as list of dicts."""
    result = con.execute(sql)
    columns = [desc[0] for desc in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def get_latest_findings(db_path=DB_PATH) -> str:
    """Get a summary of recent findings from the database."""
    con = duckdb.connect(str(db_path), read_only=True)

    rows = _query(con, """
        select
            biomarker_key,
            value_raw,
            value_si,
            unit_si,
            report_date,
            provider,
            is_within_ref_range,
            is_within_optimal_range,
            category
        from main.fct_biomarkers
        order by report_date desc, biomarker_key
    """)

    lines = []
    if rows:
        lines.append("Recent biomarker results:")
        for r in rows:
            ref = "in range" if r["is_within_ref_range"] else "OUT OF RANGE" if r["is_within_ref_range"] is not None else "unknown"
            val = f"{r['value_si']:.2f}" if r["value_si"] is not None else r.get("value_raw", "N/A")
            unit = r["unit_si"] or ""
            lines.append(f"  {r['report_date']} | {r['biomarker_key']}: {val} {unit} ({r['provider']}) - {ref}")

    # Document context: summaries and baseline candidates
    # Gracefully handle databases where dim_documents hasn't been re-materialized yet
    try:
        docs = _query(con, """
            select
                report_date, provider, report_type, source_file,
                document_summary, baseline_candidates
            from main.dim_documents
            where document_summary is not null
               or baseline_candidates is not null
            order by report_date desc
        """)
    except duckdb.BinderException:
        docs = []

    con.close()

    if docs:
        lines.append("")
        lines.append("Document summaries and baseline candidates:")
        for d in docs:
            lines.append(f"\n--- {d['report_date']} | {d['report_type']} ({d['provider']}) ---")
            if d.get("document_summary"):
                lines.append(d["document_summary"])
            if d.get("baseline_candidates"):
                try:
                    candidates = json.loads(d["baseline_candidates"])
                except (ValueError, TypeError):
                    candidates = []
                if candidates:
                    lines.append("Baseline candidates:")
                    for c in candidates:
                        lines.append(f"  - {c}")

    if not lines:
        return "No findings data found."

    return "\n".join(lines)


def propose_updates() -> str | None:
    """Call Claude to propose baseline updates. Returns proposed YAML or None."""
    import anthropic

    if not ANTHROPIC_API_KEY:
        return None

    baseline_path = PROFILE_DIR / "baseline.yml"
    if not baseline_path.exists():
        current_baseline = "No baseline file exists yet. Start with an empty derived section."
    else:
        current_baseline = baseline_path.read_text()

    findings = get_latest_findings()

    prompt_template = (PROMPTS_DIR / "baseline_prompt.txt").read_text()
    prompt = prompt_template.format(current_baseline=current_baseline, findings=findings)

    from redact import redact_pii, restore_pii

    prompt, pii_mapping = redact_pii(prompt)

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    full_text = ""
    fence_marker = "```yaml"
    in_yaml = False

    with client.messages.stream(
        model=EXTRACTION_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        for chunk in stream.text_stream:
            full_text += chunk
            if not in_yaml:
                if fence_marker in full_text:
                    # Print any reasoning text before the fence
                    before_fence = full_text.split(fence_marker, 1)[0]
                    # We may have already printed some; just flush the remainder
                    in_yaml = True
                else:
                    sys.stdout.write(chunk)
                    sys.stdout.flush()

    # Visual separation between reasoning and diff
    sys.stdout.write("\n")
    sys.stdout.flush()

    # Extract YAML from fenced block
    if fence_marker in full_text:
        yaml_part = full_text.split(fence_marker, 1)[1]
        # Strip closing fence
        if "```" in yaml_part:
            yaml_part = yaml_part.split("```", 1)[0]
        return restore_pii(yaml_part.strip(), pii_mapping)

    # Fallback: no fence found, treat entire response as YAML
    return restore_pii(full_text.strip(), pii_mapping)


def show_diff(current: str, proposed: str) -> str:
    """Show a simple diff between current and proposed baseline."""
    current_lines = current.splitlines()
    proposed_lines = proposed.splitlines()

    diff_lines = []
    for line in difflib.unified_diff(
        current_lines, proposed_lines,
        fromfile="current baseline.yml",
        tofile="proposed baseline.yml",
        lineterm="",
    ):
        diff_lines.append(line)

    return "\n".join(diff_lines) if diff_lines else "(no changes)"
