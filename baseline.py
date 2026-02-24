"""Baseline updater - proposes derived baseline updates via Claude."""

import difflib

import duckdb
import yaml

from config import ANTHROPIC_API_KEY, DB_PATH, EXTRACTION_MODEL, PROFILE_DIR


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

    con.close()

    if not rows:
        return "No biomarker data found."

    lines = ["Recent biomarker results:"]
    for r in rows:
        ref = "in range" if r["is_within_ref_range"] else "OUT OF RANGE" if r["is_within_ref_range"] is not None else "unknown"
        val = f"{r['value_si']:.2f}" if r["value_si"] is not None else r.get("value_raw", "N/A")
        unit = r["unit_si"] or ""
        lines.append(f"  {r['report_date']} | {r['biomarker_key']}: {val} {unit} ({r['provider']}) - {ref}")

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

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=EXTRACTION_MODEL,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": (
                    "Given these new lab results and the current baseline, should any "
                    "new permanent facts be added to the derived section? Only add things "
                    "that are permanently relevant to future medical decisions.\n\n"
                    f"Current baseline:\n```yaml\n{current_baseline}\n```\n\n"
                    f"{findings}\n\n"
                    "Return ONLY the updated YAML for the full baseline file. "
                    "If no changes are needed, return the current baseline unchanged."
                ),
            }
        ],
    )

    return response.content[0].text


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
