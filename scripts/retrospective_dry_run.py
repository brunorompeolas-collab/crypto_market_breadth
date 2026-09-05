"""Run the Gate-only retrospective validation without any Firestore writes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse

from crypto_breadth_v2.research_validation import run_validation, write_report


UTC = timezone.utc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", help="UTC ISO timestamp; defaults to the current UTC clock")
    parser.add_argument(
        "--output-dir",
        default="research-validation/manifests",
        help="directory for compact machine-readable manifests",
    )
    parser.add_argument(
        "--report",
        default="RETROSPECTIVE_DRY_RUN_REPORT.md",
        help="Markdown report path",
    )
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00")) if args.as_of else datetime.now(UTC)
    if as_of.tzinfo is None or as_of.utcoffset() != UTC.utcoffset(None):
        raise SystemExit("--as-of must be timezone-aware UTC")
    root = Path(__file__).resolve().parents[1]
    result = run_validation(
        root=root,
        output_dir=root / args.output_dir,
        as_of=as_of.astimezone(UTC),
    )
    write_report(result, root / args.report)
    print(f"report={root / args.report}")
    for name, manifest in result["manifests"].items():
        print(name, manifest["raw_validation"], manifest["output_validation"], manifest["compute"].get("output_count", 0))
    print("gate_stats", result["gate_stats"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

