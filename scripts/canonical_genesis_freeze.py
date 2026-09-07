from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from crypto_breadth_v2.canonical_genesis_freeze import run_freeze, write_freeze_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze canonical EMA genesis contracts locally")
    parser.add_argument("--as-of", required=True, help="UTC ISO-8601 as-of timestamp")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    if as_of.tzinfo is None:
        raise SystemExit("--as-of must include a UTC offset")
    output_dir = args.output_dir or args.root / "config" / "v2" / "research_genesis"
    report = args.report or args.root / "CANONICAL_EMA_GENESIS_FREEZE_REPORT.md"
    result = run_freeze(root=args.root, output_dir=output_dir, as_of=as_of.astimezone(timezone.utc))
    write_freeze_report(result, report)
    for name, data in result["candidates"].items():
        contract = data["contract"]
        print(f"{name}: genesis={contract['genesis_boundary']} outputs={contract['research_output_snapshot_count']} cohort={contract['cohort_size']}")


if __name__ == "__main__":
    main()
