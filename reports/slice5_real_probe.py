"""One-shot Gate candidate shadow probe used for Slice 5 evidence."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from crypto_breadth_v2.bootstrap import GateBootstrapService
from crypto_breadth_v2.contracts import load_contract_bundle
from crypto_breadth_v2.incremental import CandidateShadowService
from crypto_breadth_v2.providers.gate import GateClient, load_gate_mappings
from crypto_breadth_v2.storage.database import create_postgres_engine
from crypto_breadth_v2.storage.models import TimeframeCohort
from crypto_breadth_v2.timeframes import Timeframe


def main() -> None:
    database_url = os.environ["BREADTH_V2_TEST_DATABASE_URL"]
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(cfg, "head")
    engine = create_postgres_engine(database_url)
    with engine.begin() as connection:
        tables = connection.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='breadth_v2' AND tablename <> 'alembic_version'" )).scalars().all()
        if tables:
            connection.exec_driver_sql("TRUNCATE " + ", ".join(f'breadth_v2."{table}"' for table in tables) + " RESTART IDENTITY CASCADE")
    bundle = load_contract_bundle(root / "config" / "v2", bundle="v2-40")
    as_of = datetime.now(timezone.utc)
    mappings = load_gate_mappings(bundle)
    metadata = GateBootstrapService(engine, GateClient(mappings), bundle, as_of=as_of)
    metadata.ensure_metadata()
    with engine.begin() as connection:
        assets = {row["id"]: metadata.asset_uuid_by_id[row["id"]] for row in bundle.definition("universe")["members"]}
        for timeframe, excluded in (("4h", set()), ("1d", set()), ("1w", {"GRAM", "TAO", "SUI", "HYPE", "ONDO"})):
            for member in bundle.definition("universe")["members"]:
                connection.execute(TimeframeCohort.__table__.insert().values(
                    series_version=metadata.series_version, timeframe=timeframe,
                    asset_id=assets[member["id"]], included_in_denominator=member["symbol"] not in excluded,
                    history_count_at_inception=0, eligibility_reason="SLICE5_REAL_PROBE", frozen_at=as_of,
                ))
    report = CandidateShadowService(engine, GateClient(mappings), bundle, as_of=as_of).run(Timeframe.FOUR_HOUR)
    output = root / "reports" / "slice5_gate_shadow_real.json"
    output.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report.as_dict(), sort_keys=True))


if __name__ == "__main__":
    main()

