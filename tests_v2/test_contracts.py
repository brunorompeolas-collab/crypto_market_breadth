from copy import deepcopy
import json
from pathlib import Path

import pytest

from crypto_breadth_v2.contracts import (
    CONTRACT_PATHS,
    ContractError,
    canonical_json,
    contract_hash,
    load_contract_bundle,
    validate_contracts,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "config" / "v2"


def test_frozen_contract_bundle_validates_and_matches_manifest():
    bundle = load_contract_bundle(CONTRACT_ROOT)
    assert set(bundle.definitions) == set(CONTRACT_PATHS)
    assert len(bundle.definition("universe")["members"]) == 50
    assert len(bundle.hashes) == 6


def test_canonical_hash_is_key_order_and_whitespace_independent():
    left = {"b": [2, 1], "a": {"x": "é"}}
    right = json.loads('{ "a": { "x": "é" }, "b": [2, 1] }')
    assert canonical_json(left) == canonical_json(right)
    assert contract_hash(left) == contract_hash(right)


def test_universe_has_exactly_50_unique_ids_and_symbols():
    bundle = load_contract_bundle(CONTRACT_ROOT)
    members = bundle.definition("universe")["members"]
    assert len({member["id"] for member in members}) == 50
    assert len({member["symbol"] for member in members}) == 50


def test_sky_preserves_mkr_predecessor_without_history_stitching():
    bundle = load_contract_bundle(CONTRACT_ROOT)
    sky = next(
        member for member in bundle.definition("universe")["members"]
        if member["symbol"] == "SKY"
    )
    assert sky["display_name"] == "SKY (formerly MKR)"
    assert sky["legacy_identities"] == [
        {"id": "maker", "symbol": "MKR", "relationship": "PREDECESSOR"}
    ]
    assert bundle.definition("source_policy")["mappings"]["SKY"]["predecessor_history_stitching"] is False


def test_every_member_has_one_deterministic_source_mapping():
    bundle = load_contract_bundle(CONTRACT_ROOT)
    symbols = {member["symbol"] for member in bundle.definition("universe")["members"]}
    mappings = bundle.definition("source_policy")["mappings"]
    assert set(mappings) == symbols
    assert {symbol for symbol, row in mappings.items() if row["source"] == "kraken_spot"} == {"TON", "XMR"}
    assert all(row["source"] in {"gate_spot", "kraken_spot"} for row in mappings.values())


def test_contract_validation_rejects_dynamic_fallback():
    bundle = load_contract_bundle(CONTRACT_ROOT)
    changed = deepcopy(bundle.definitions)
    changed["source_policy"] = deepcopy(changed["source_policy"])
    changed["source_policy"]["automatic_fallback"] = True
    with pytest.raises(ContractError, match="fallback"):
        validate_contracts(changed)


def test_contract_validation_rejects_gap_rewarm():
    bundle = load_contract_bundle(CONTRACT_ROOT)
    changed = deepcopy(bundle.definitions)
    changed["methodology"] = deepcopy(changed["methodology"])
    changed["methodology"]["missing_candle"]["reset_and_rewarm_after_gap"] = True
    with pytest.raises(ContractError, match="rewarm"):
        validate_contracts(changed)
