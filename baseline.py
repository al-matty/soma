"""Baseline updater - proposes derived baseline updates via Claude."""

import duckdb
import yaml

from config import ANTHROPIC_API_KEY, DB_PATH, EXTRACTION_MODEL, PROFILE_DIR


def get_latest_findings(db_path=DB_PATH) -> str:
    """Get a summary of recent findings from the database."""
    con = duckdb.connect(str(db_path), read_only=True)

    rows = con.execute("""
        select
            biomarker_key,
            value_si,
            unit_si,
            report_date,
            provider,
            is_within_ref_range,
            is_within_optimal_range,
            category
        from main.fct_biomarkers
        order by report_date desc, biomarker_key
    """).fetchall()

    con.close()

    if not rows:
        return "No biomarker data found."

    lines = ["Recent biomarker results:"]
    for r in rows:
        ref = "in range" if r[5] else "OUT OF RANGE" if r[5] is not None else "unknown"
        lines.append(f"  {r[3]} | {r[0]}: {r[1]:.2f} {r[2]} ({r[4]}) - {ref}")

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
    import difflib

    for line in difflib.unified_diff(
        current_lines, proposed_lines,
        fromfile="current baseline.yml",
        tofile="proposed baseline.yml",
        lineterm="",
    ):
        diff_lines.append(line)

    return "\n".join(diff_lines) if diff_lines else "(no changes)"
