"""Run the local EMA-genesis decomposition against Gate history."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse

from crypto_breadth_v2.ema_genesis_audit import run_genesis_audit, write_genesis_report


UTC = timezone.utc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="fixed UTC ISO timestamp used by the dry run")
    parser.add_argument("--output-dir", default="research-validation/genesis")
    parser.add_argument("--report", default="EMA_GENESIS_AUDIT_REPORT.md")
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    if as_of.tzinfo is None or as_of.utcoffset() != UTC.utcoffset(None):
        raise SystemExit("--as-of must be timezone-aware UTC")
    root = Path(__file__).resolve().parents[1]
    result = run_genesis_audit(root=root, output_dir=root / args.output_dir, as_of=as_of.astimezone(UTC))
    write_genesis_report(result, root / args.report)
    print(f"report={root / args.report}")
    print("gate_stats", result["gate_request_stats"])
    print("original_confounded", result["original_confounded_a40_vs_b39"])
    print("cohort_effect", result["cohort_effect_a40_vs_a39"])
    print("genesis_effect", result["genesis_effect_a39_short_vs_b39_long"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

