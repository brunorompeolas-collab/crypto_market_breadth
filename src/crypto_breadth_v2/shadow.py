"""Operational candidate-shadow entrypoint; never activates LIVE."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
import argparse
import json

from .contracts import load_contract_bundle
from .incremental import CandidateShadowService
from .providers.gate import GateClient, load_gate_mappings
from .storage.database import create_postgres_engine
from .timeframes import Timeframe


UTC = timezone.utc


def run_shadow(
    database_url: str,
    *,
    timeframe: Timeframe | str,
    as_of: datetime,
    contracts_root: Path,
):
    bundle = load_contract_bundle(contracts_root, bundle="v2-40")
    engine = create_postgres_engine(database_url)
    mappings = load_gate_mappings(bundle)
    return CandidateShadowService(
        engine,
        GateClient(mappings),
        bundle,
        as_of=as_of,
    ).run(timeframe)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one candidate shadow cycle")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--timeframe", choices=[item.value for item in Timeframe], required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--contracts-root", default="config/v2")
    args = parser.parse_args(argv)
    as_of = datetime.fromisoformat(args.as_of.replace("Z", "+00:00"))
    report = run_shadow(
        args.database_url,
        timeframe=Timeframe(args.timeframe),
        as_of=as_of,
        contracts_root=Path(args.contracts_root),
    )
    print(json.dumps(report.as_dict(), sort_keys=True))
    return 0 if report.status == "SUCCEEDED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

