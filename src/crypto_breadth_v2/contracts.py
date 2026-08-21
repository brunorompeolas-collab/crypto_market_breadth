"""Versioned Slice 0 contract loading, hashing, and cross-contract validation."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping


class ContractError(ValueError):
    """Raised when a frozen v2 contract is malformed or inconsistent."""


CONTRACT_BUNDLES = {
    "v1": {
        "manifest": "contracts-manifest.yaml",
        "paths": {
            "universe": "universe/br1-breadth-universe-v1.yaml",
            "source_policy": "sources/br1-source-policy-v1.yaml",
            "methodology": "methodology/br1-methodology-v2.yaml",
            "formula": "formula/br1-breadth-formula-v1.yaml",
            "normalizer": "normalizer/br1-candle-normalizer-v2.yaml",
            "series": "series/br1-live-v2-candidate.yaml",
        },
    },
    "v2-40": {
        "manifest": "contracts-manifest-v2-40.yaml",
        "paths": {
            "universe": "universe/br1-breadth-universe-v2-40.yaml",
            "source_policy": "sources/br1-source-policy-v2-gate-only.yaml",
            "methodology": "methodology/br1-methodology-v2.yaml",
            "formula": "formula/br1-breadth-formula-v1.yaml",
            "normalizer": "normalizer/br1-candle-normalizer-v2.yaml",
            "series": "series/br1-live-v2-40-candidate.yaml",
        },
    },
}

# Backward-compatible alias for the accepted v1 audit/reference bundle.
CONTRACT_PATHS = CONTRACT_BUNDLES["v1"]["paths"]


def canonical_json(document: Any) -> bytes:
    """Serialize a contract deterministically for content-addressed freezing."""
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def contract_hash(document: Any) -> str:
    return sha256(canonical_json(document)).hexdigest()


def _load_json_yaml(path: Path) -> dict[str, Any]:
    # JSON is a strict subset of YAML 1.2. Keeping the frozen files in that
    # subset provides portable YAML contracts without a runtime YAML dependency.
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"Cannot load contract {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise ContractError(f"Contract {path} must contain an object")
    return document


@dataclass(frozen=True)
class ContractBundle:
    bundle_name: str
    root: Path
    definitions: Mapping[str, Mapping[str, Any]]
    hashes: Mapping[str, str]

    def definition(self, name: str) -> Mapping[str, Any]:
        return self.definitions[name]


def validate_contracts(definitions: Mapping[str, Mapping[str, Any]]) -> None:
    universe = definitions["universe"]
    members = universe.get("members", [])
    expected_size = universe.get("expected_size")
    if expected_size not in {40, 50} or len(members) != expected_size:
        raise ContractError("BR1 universe size does not match its frozen contract")

    ids = [member.get("id") for member in members]
    symbols = [member.get("symbol") for member in members]
    if None in ids or len(set(ids)) != expected_size:
        raise ContractError("Universe member IDs must be present and unique")
    if None in symbols or len(set(symbols)) != expected_size:
        raise ContractError("Universe symbols must be present and unique")

    source_policy = definitions["source_policy"]
    mappings = source_policy.get("mappings", {})
    if set(mappings) != set(symbols):
        raise ContractError("Source policy must map every universe symbol exactly once")
    if source_policy.get("automatic_fallback") is not False:
        raise ContractError("Automatic provider fallback must remain disabled")
    if universe.get("version") == "BR1-BREADTH-UNIVERSE-v1":
        sky = next((member for member in members if member.get("symbol") == "SKY"), None)
        if not sky or sky.get("display_name") != "SKY (formerly MKR)":
            raise ContractError("SKY must preserve the Founder-approved MKR display identity")
        legacy = sky.get("legacy_identities", [])
        if not any(item.get("symbol") == "MKR" for item in legacy):
            raise ContractError("SKY must retain MKR predecessor metadata")
        kraken_symbols = {
            symbol for symbol, mapping in mappings.items()
            if mapping.get("source") == "kraken_spot"
        }
        if kraken_symbols != {"TON", "XMR"}:
            raise ContractError("Only TON and XMR may use the v1 Kraken mapping")
        if mappings["SKY"].get("predecessor_history_stitching") is not False:
            raise ContractError("MKR history stitching into canonical SKY is forbidden")
    elif universe.get("version") == "BR1-BREADTH-UNIVERSE-v2-40":
        if expected_size != 40:
            raise ContractError("BR1 v2-40 universe must contain exactly 40 members")
        if "ZEC" not in symbols or "XMR" in symbols:
            raise ContractError("BR1 v2-40 requires ZEC and excludes XMR")
        gram = next((member for member in members if member.get("symbol") == "GRAM"), None)
        if not gram or gram.get("id") != "the-open-network":
            raise ContractError("GRAM must use the-open-network canonical identity")
        if gram.get("display_name") != "GRAM (formerly TON)":
            raise ContractError("GRAM display identity is not frozen")
        legacy = gram.get("legacy_identities", [])
        if not any(
            item.get("symbol") == "TON" and item.get("relationship") == "OFFICIAL_RENAME"
            for item in legacy
        ):
            raise ContractError("GRAM must retain TON official-rename metadata")
        if set(source_policy.get("sources", {})) != {"gate_spot"}:
            raise ContractError("BR1 v2-40 must define Gate as its only source")
        if any(mapping.get("source") != "gate_spot" for mapping in mappings.values()):
            raise ContractError("Every BR1 v2-40 mapping must use Gate")
        if mappings["GRAM"].get("instrument") != "GRAM_USDT":
            raise ContractError("GRAM must map explicitly to GRAM_USDT")
    else:
        raise ContractError("Unknown BR1 universe version")

    formula = definitions["formula"]
    weights = [
        item.get("weight")
        for item in formula.get("components", {}).values()
    ]
    from decimal import Decimal, InvalidOperation
    try:
        weight_sum = sum((Decimal(weight) for weight in weights), Decimal("0"))
    except (InvalidOperation, TypeError) as exc:
        raise ContractError("Formula weights must be decimal strings") from exc
    if weight_sum != Decimal("1.00"):
        raise ContractError("Formula weights must sum exactly to 1.00")

    methodology = definitions["methodology"]
    gap = methodology.get("missing_candle", {})
    if gap.get("calculate_across_gap") is not False:
        raise ContractError("The methodology must not calculate across a gap")
    if gap.get("reset_and_rewarm_after_gap") is not False:
        raise ContractError("A missing candle must not trigger an N-candle rewarm")
    if methodology.get("universe", {}).get("weekly_eligibility_observations") != 200:
        raise ContractError("Weekly structural eligibility must use 200 observations")
    if methodology.get("data_quality", {}).get("formula") != (
        "ROUND_HALF_UP(100*STRUCTURAL*COMPONENT*FRESHNESS*ALIGNMENT,1)"
    ):
        raise ContractError("Data Quality formula is not frozen to the approved definition")
    if methodology.get("scanner", {}).get("states") != [
        "ABOVE", "BELOW", "UNAVAILABLE"
    ]:
        raise ContractError("Scanner tri-state contract is invalid")

    normalizer = definitions["normalizer"]
    if set(normalizer.get("timeframes", {})) != {"4h", "1d", "1w"}:
        raise ContractError("Normalizer must define exactly 4h, 1d, and 1w")

    series = definitions["series"]
    expected_versions = {
        "universe_version": universe.get("version"),
        "source_policy_version": source_policy.get("version"),
        "methodology_version": methodology.get("version"),
        "formula_version": formula.get("version"),
        "normalizer_version": normalizer.get("version"),
    }
    for field, expected in expected_versions.items():
        if series.get(field) != expected:
            raise ContractError(f"Series {field} does not match referenced contract")
    if series.get("inception") is not None:
        raise ContractError("Candidate LIVE inception must remain unset until cutover")


def load_contract_bundle(
    root: Path, *, bundle: str = "v1", verify_manifest: bool = True
) -> ContractBundle:
    root = Path(root)
    try:
        bundle_config = CONTRACT_BUNDLES[bundle]
    except KeyError as exc:
        raise ContractError(f"Unknown contract bundle: {bundle}") from exc
    paths = bundle_config["paths"]
    definitions = {
        name: _load_json_yaml(root / relative_path)
        for name, relative_path in paths.items()
    }
    validate_contracts(definitions)
    hashes = {name: contract_hash(document) for name, document in definitions.items()}

    if verify_manifest:
        manifest = _load_json_yaml(root / bundle_config["manifest"])
        if manifest.get("hash_algorithm") != "SHA-256":
            raise ContractError("Manifest hash algorithm must be SHA-256")
        if manifest.get("definitions") != hashes:
            raise ContractError("Frozen contract hash manifest does not match definitions")

    return ContractBundle(
        bundle_name=bundle, root=root, definitions=definitions, hashes=hashes
    )
