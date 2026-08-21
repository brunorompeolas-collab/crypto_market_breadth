"""Small read-only Gate catalogue preflight for the frozen v2-40 mappings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import load_contract_bundle
from .providers.gate import GateClient, load_gate_mappings


def run_preflight(contract_root: Path) -> dict[str, object]:
    bundle = load_contract_bundle(contract_root, bundle="v2-40")
    mappings = load_gate_mappings(bundle)
    instruments = GateClient(mappings).verify_live_catalogue()
    return {
        "provider": "Gate",
        "universe_version": bundle.definition("universe")["version"],
        "source_policy_version": bundle.definition("source_policy")["version"],
        "expected": 40,
        "matched": len(instruments),
        "automatic_fallback": False,
        "secondary_provider": None,
        "instruments": list(instruments),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(run_preflight(args.contract_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
