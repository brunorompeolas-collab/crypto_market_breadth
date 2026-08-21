"""Run one real candidate shadow cycle after Slice 4 bootstrap history."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os

from crypto_breadth_v2.contracts import load_contract_bundle
from crypto_breadth_v2.incremental import CandidateShadowService
from crypto_breadth_v2.providers.gate import GateClient, load_gate_mappings
from crypto_breadth_v2.storage.database import create_postgres_engine
from crypto_breadth_v2.timeframes import Timeframe


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    database_url = os.environ["BREADTH_V2_DATABASE_URL"]
    as_of = datetime.now(timezone.utc)
    bundle = load_contract_bundle(root / "config" / "v2", bundle="v2-40")
    engine = create_postgres_engine(database_url)
    reports = []
    for timeframe in (Timeframe.FOUR_HOUR, Timeframe.DAILY, Timeframe.WEEKLY):
        client = GateClient(load_gate_mappings(bundle))
        reports.append(CandidateShadowService(engine, client, bundle, as_of=as_of).run(timeframe).as_dict())
    output = root / "reports" / "slice6_shadow_cycle_real.json"
    output.write_text(json.dumps({"as_of": as_of.isoformat(), "reports": reports}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()

