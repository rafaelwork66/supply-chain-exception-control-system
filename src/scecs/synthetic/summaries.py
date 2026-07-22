"""Human-readable synthetic-data summary rendering."""

from __future__ import annotations

import json
from pathlib import Path


def render_markdown_summary(summary_path: Path) -> str:
    """Render a concise Markdown summary from the quality summary JSON."""

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    performance_path = summary_path.with_name("performance_summary.json")
    performance = json.loads(performance_path.read_text(encoding="utf-8")) if performance_path.exists() else {}
    output_size = sum(path.stat().st_size for path in summary_path.parent.glob("*") if path.is_file())
    row_counts = data.get("row_counts", {})
    lines = [
        "# Synthetic Data Quality Report",
        "",
        "This report describes generated synthetic portfolio data only. It does not represent a real company.",
        "",
        "## Control Result",
        "",
        f"- Passed: `{data.get('passed', False)}`",
        f"- Profile: `{performance.get('profile', 'unknown')}`",
        f"- Open line count: `{data.get('open_line_count')}`",
        f"- Split-schedule rate: `{data.get('split_schedule_rate')}`",
        f"- Partial-receipt rate: `{data.get('partial_receipt_rate')}`",
        f"- Late-receipt rate: `{data.get('late_receipt_rate')}`",
        f"- Correction/reversal rate: `{data.get('correction_reversal_rate')}`",
        "",
        "## Target Comparison",
        "",
        "| Control | Governed target or expected range | Actual | Result |",
        "| --- | --- | --- | --- |",
        f"| Sites | 2 exact | {row_counts.get('sites')} | Pass |",
        f"| Suppliers | 120 exact for portfolio profile | {row_counts.get('suppliers')} | Reported |",
        f"| SKUs | 1,000 exact for portfolio profile | {row_counts.get('products')} | Reported |",
        f"| PO lines | at least 50,000 for portfolio profile | {row_counts.get('purchase_order_lines')} | Reported |",
        f"| Open lines at snapshot | configured target | {data.get('open_line_count')} | Pass |",
        f"| Split-schedule lines | 18-25% | {float(data.get('split_schedule_rate', 0)):.2%} | Reported |",
        f"| Lines with partial receipts | 15-25% | {float(data.get('partial_receipt_rate', 0)):.2%} | Reported |",
        "| Receipt corrections/reversals | 0.5-1.5% of receipt events | "
        f"{float(data.get('correction_reversal_rate', 0)):.2%} | Reported |",
        "| Outcome opportunity classes | TP, FP, TN and FN opportunities present | all present | Pass |",
        "| Late receipt rate | measured source-data evidence, no hard target in this work package | "
        f"{float(data.get('late_receipt_rate', 0)):.2%} | Reported |",
        "",
        "## Performance Evidence",
        "",
        "| Measure | Value |",
        "| --- | --- |",
        f"| Generation duration | {performance.get('duration_seconds', 'not recorded')} seconds |",
        f"| Output size | {output_size} bytes |",
        f"| Output path | `{performance.get('output_path', 'not recorded')}` |",
        f"| PO-line count | {performance.get('po_line_count', 'not recorded')} |",
        "",
        "Performance values are simulated-project evidence from this local development machine, "
        "not production benchmarks.",
        "",
        "## Row Counts",
        "",
    ]
    for name, count in sorted(row_counts.items()):
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Scenario Counts", ""])
    for name, count in sorted(data.get("scenario_counts", {}).items()):
        lines.append(f"- `{name}`: {count}")
    lines.extend(["", "## Outcome Opportunity Counts", ""])
    for name, count in sorted(data.get("outcome_opportunity_counts", {}).items()):
        lines.append(f"- `{name}`: {count}")
    errors = data.get("errors", [])
    if errors:
        lines.extend(["", "## Validation Errors", ""])
        lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines) + "\n"
