from copy import deepcopy
from pathlib import Path

import pytest

from crypto_breadth_v2.contracts import ContractError, load_contract_bundle, validate_contracts


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "config" / "v2"
UNCHANGED_HASHES = {
    "formula": "d0f22b3614294b6c71bed3bd29e94e2170a524dc98783298e1ea85cc6f696509",
    "methodology": "45a85fa7ca2ca5b9f90a157f577756be6fdc8b592453a5bef436f3d39ff7cacc",
    "normalizer": "e48e16431d6c7785e7ddcd30718ab2fc7d9388b3c1c2ef3259d8a308ea08b6db",
}


def test_v1_contract_bundle_remains_immutable_and_loadable():
    bundle = load_contract_bundle(CONTRACT_ROOT, bundle="v1")
    assert bundle.definition("universe")["version"] == "BR1-BREADTH-UNIVERSE-v1"
    assert len(bundle.definition("universe")["members"]) == 50


def test_v2_40_bundle_matches_manifest_and_has_exact_unique_membership():
    bundle = load_contract_bundle(CONTRACT_ROOT, bundle="v2-40")
    members = bundle.definition("universe")["members"]
    assert len(members) == 40
    assert len({member["id"] for member in members}) == 40
    assert len({member["symbol"] for member in members}) == 40


def test_v2_40_has_exact_gate_only_mapping_coverage_without_fallback():
    bundle = load_contract_bundle(CONTRACT_ROOT, bundle="v2-40")
    symbols = {member["symbol"] for member in bundle.definition("universe")["members"]}
    source_policy = bundle.definition("source_policy")
    assert set(source_policy["sources"]) == {"gate_spot"}
    assert set(source_policy["mappings"]) == symbols
    assert len(source_policy["mappings"]) == 40
    assert all(row["source"] == "gate_spot" for row in source_policy["mappings"].values())
    assert source_policy["automatic_fallback"] is False
    assert "kraken" not in str(source_policy).lower()


def test_v2_40_gram_metadata_and_zec_xmr_decision_are_frozen():
    bundle = load_contract_bundle(CONTRACT_ROOT, bundle="v2-40")
    members = bundle.definition("universe")["members"]
    symbols = {member["symbol"] for member in members}
    assert "ZEC" in symbols
    assert "XMR" not in symbols
    gram = next(member for member in members if member["symbol"] == "GRAM")
    assert gram == {
        "id": "the-open-network",
        "symbol": "GRAM",
        "display_name": "GRAM (formerly TON)",
        "legacy_identities": [
            {
                "id": "the-open-network",
                "symbol": "TON",
                "relationship": "OFFICIAL_RENAME",
            }
        ],
        "blockchain_name": "TON",
    }
    assert bundle.definition("source_policy")["mappings"]["GRAM"] == {
        "source": "gate_spot",
        "instrument": "GRAM_USDT",
        "quote": "USDT",
        "legacy_symbol": "TON",
        "identity_relationship": "OFFICIAL_RENAME",
        "predecessor_history_stitching": False,
    }


def test_v2_40_candidate_is_unactivated_and_references_unchanged_core_contracts():
    bundle = load_contract_bundle(CONTRACT_ROOT, bundle="v2-40")
    series = bundle.definition("series")
    assert series["inception"] is None
    assert series["status"] == "CANDIDATE_NOT_ACTIVATED"
    assert series["history_policy"] == "NO_V1_50_HISTORY_SPLICE"
    assert {name: bundle.hashes[name] for name in UNCHANGED_HASHES} == UNCHANGED_HASHES


def test_v2_40_validation_rejects_kraken_or_xmr_reintroduction():
    bundle = load_contract_bundle(CONTRACT_ROOT, bundle="v2-40")
    changed = deepcopy(bundle.definitions)
    changed["source_policy"] = deepcopy(changed["source_policy"])
    changed["source_policy"]["mappings"]["ZEC"]["source"] = "kraken_spot"
    with pytest.raises(ContractError, match="Gate"):
        validate_contracts(changed)
