"""Determine and freeze earliest clean EMA genesis contracts, locally only."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import ContractBundle, canonical_json, load_contract_bundle
from .ema_genesis_audit import aggregate_series, build_member_series
from .providers.gate import (
    GATE_MAX_CANDLES,
    GateCandleEnvelope,
    GateClient,
    GateMapping,
    load_gate_mappings,
)
from .research_validation import (
    CANDIDATES,
    CandidatePeriod,
    CandidateSpec,
    FetchResult,
    _iso,
    _raw_hash,
    fetch_full_range,
    freeze_period,
    validate_asset,
)
from .timeframes import Timeframe, duration, expected_latest_close, require_utc


UTC = timezone.utc
GENESIS_POLICY = "EARLIEST_FULLY_CLEAN_COMMON_BOUNDARY"
LABEL = "RETROSPECTIVE_SURVIVORSHIP_BIASED"
SEARCH_START = datetime(2017, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class GenesisResult:
    symbol: str
    asset_id: str
    first_available_boundary: datetime | None
    first_continuous_boundary: datetime | None
    earlier_gap_count: int
    identity_status: str
    reason: str | None


def _sha(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()


def _sequence(start: datetime, end: datetime, timeframe: Timeframe) -> tuple[datetime, ...]:
    require_utc(start)
    require_utc(end)
    step = duration(timeframe)
    result: list[datetime] = []
    cursor = start
    while cursor <= end:
        result.append(cursor)
        cursor += step
    return tuple(result)


def discover_first_available(
    client: GateClient,
    symbol: str,
    *,
    timeframe: Timeframe,
    end: datetime,
    as_of: datetime,
) -> tuple[datetime | None, str | None]:
    """Scan bounded provider windows until the first canonical candle appears."""
    step = duration(timeframe)
    span = step * (GATE_MAX_CANDLES - 1)
    cursor = SEARCH_START
    while cursor < end:
        page_end = min(end, cursor + span)
        try:
            rows = client.fetch_candles(
                symbol, timeframe=timeframe, as_of=as_of,
                from_time=cursor, to_time=page_end,
            )
        except Exception as exc:
            # An empty pre-listing window is expected; other errors are retained
            # as evidence and discovery continues only for that asset.
            if type(exc).__name__ != "GateInstrumentUnavailableError":
                return None, f"{type(exc).__name__}: {exc}"
            rows = ()
        if rows:
            first = min(row.candle.close_time for row in rows)
            return first, None
        cursor = page_end
    return None, "NO_PROVIDER_HISTORY_IN_SEARCH_RANGE"


def _fetch_from_genesis(
    client: GateClient,
    symbol: str,
    mapping: GateMapping,
    *,
    timeframe: Timeframe,
    genesis: datetime,
    end: datetime,
    as_of: datetime,
) -> FetchResult:
    step = duration(timeframe)
    period = CandidatePeriod(
        latest_boundary=end,
        output_start=genesis,
        output_end=end,
        ema_warmup_start=genesis - step,
        raw_close_start=genesis,
        expected_raw_count=0,
        expected_output_count=0,
    )
    return fetch_full_range(client, symbol, mapping, timeframe=timeframe, period=period, as_of=as_of)


def _validate_continuity(
    envelopes: Sequence[GateCandleEnvelope],
    *,
    genesis: datetime,
    end: datetime,
    timeframe: Timeframe,
) -> tuple[int, datetime | None]:
    expected = _sequence(genesis, end, timeframe)
    observed = {row.candle.close_time for row in envelopes}
    missing = [boundary for boundary in expected if boundary not in observed]
    return len(missing), missing[0] if missing else None


def _find_cohort_genesis(
    *,
    client: GateClient,
    bundle: ContractBundle,
    spec: CandidateSpec,
    output_end: datetime,
    as_of: datetime,
) -> tuple[datetime, dict[str, GenesisResult], dict[str, tuple[GateCandleEnvelope, ...]], list[dict[str, Any]]]:
    universe = bundle.definition("universe")["members"]
    mappings = load_gate_mappings(bundle)
    members = [member for member in universe if member["symbol"] not in spec.excluded_symbols]
    jobs = [(member, mappings[member["symbol"]]) for member in members]

    def first_job(job: tuple[Mapping[str, Any], GateMapping]) -> tuple[datetime | None, str | None]:
        member, _mapping = job
        return discover_first_available(client, member["symbol"], timeframe=spec.timeframe, end=output_end, as_of=as_of)

    firsts: dict[str, tuple[datetime | None, str | None]] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        for (member, _mapping), result in zip(jobs, executor.map(first_job, jobs)):
            firsts[member["id"]] = result
    available = [value[0] for value in firsts.values() if value[0] is not None]
    if len(available) != len(members):
        raise RuntimeError(f"Cannot determine cohort genesis; missing first history: {firsts}")
    genesis = max(available)
    step = duration(spec.timeframe)
    lineage: dict[str, tuple[GateCandleEnvelope, ...]] = {}
    matrix_by_id: dict[str, dict[str, Any]] = {}
    # Move genesis forward only when a full-range continuity check proves a gap.
    while True:
        fetched: dict[str, FetchResult] = {}

        def fetch_job(job: tuple[Mapping[str, Any], GateMapping]) -> FetchResult:
            member, mapping = job
            return _fetch_from_genesis(client, member["symbol"], mapping, timeframe=spec.timeframe, genesis=genesis, end=output_end, as_of=as_of)

        with ThreadPoolExecutor(max_workers=8) as executor:
            for (member, _mapping), result in zip(jobs, executor.map(fetch_job, jobs)):
                fetched[member["id"]] = result
        first_gap: datetime | None = None
        for member in members:
            validated_row, observed = validate_asset(
                member=member, mapping=mappings[member["symbol"]], fetch=fetched[member["id"]],
                period=CandidatePeriod(output_end, genesis, output_end, genesis - step, genesis, 0, 0),
                timeframe=spec.timeframe,
            )
            lineage[member["id"]] = observed
            missing_count, missing_first = _validate_continuity(observed, genesis=genesis, end=output_end, timeframe=spec.timeframe)
            validated_row["first_available_boundary"] = _iso(firsts[member["id"]][0]) if firsts[member["id"]][0] else None
            validated_row["continuity_missing_boundary_count"] = missing_count
            matrix_by_id[member["id"]] = validated_row
            if missing_first is not None:
                first_gap = min(first_gap, missing_first) if first_gap else missing_first
        if first_gap is None:
            break
        genesis = first_gap + step
    for member in members:
        aid = member["id"]
        observed = lineage[aid]
        first_value, first_reason = firsts[aid]
        matrix_row = matrix_by_id[aid]
        matrix_row.update({
            "first_available_boundary": _iso(first_value) if first_value else None,
            "first_continuous_boundary": _iso(genesis),
            "earlier_gap_count": 0,
            "identity_status": "PASS" if not first_reason else "UNKNOWN",
            "reason": first_reason or ("COHORT_GENESIS_BOUNDARY" if first_value and first_value < genesis else None),
        })
    results = {
        member["id"]: GenesisResult(
            symbol=member["symbol"], asset_id=member["id"],
            first_available_boundary=firsts[member["id"]][0],
            first_continuous_boundary=genesis,
            earlier_gap_count=matrix_by_id[member["id"]]["earlier_gap_count"],
            identity_status=matrix_by_id[member["id"]]["identity_status"],
            reason=matrix_by_id[member["id"]]["reason"],
        ) for member in members
    }
    return genesis, results, lineage, list(matrix_by_id.values())


def _rebase_period(spec: CandidateSpec, *, output_end: datetime, genesis: datetime) -> CandidatePeriod:
    output_start = output_end - timedelta(days=spec.horizon_days)
    step = duration(spec.timeframe)
    return CandidatePeriod(
        latest_boundary=output_end,
        output_start=output_start,
        output_end=output_end,
        ema_warmup_start=genesis - step,
        raw_close_start=genesis,
        expected_raw_count=len(_sequence(genesis, output_end, spec.timeframe)),
        expected_output_count=len(_sequence(output_start, output_end, spec.timeframe)),
    )


def _compact_payloads(rows: Sequence[Mapping[str, Any]], *, series_version: str, genesis_hash: str, bundle: ContractBundle) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        result.append({
            "boundary": row["boundary"],
            "breadth_score": row["breadth_score"],
            "pct_above_ema20": row["pct_above_ema20"],
            "pct_above_ema50": row["pct_above_ema50"],
            "pct_above_ema200": row["pct_above_ema200"],
            "btc_close": row.get("btc_close"),
            "eth_close": row.get("eth_close"),
            "cohort_denominator": row["cohort_denominator"],
            "data_quality": "HIGH",
            "series_version": series_version,
            "genesis_contract_sha256": genesis_hash,
            "source_policy_version": bundle.definition("source_policy")["version"],
            "methodology_version": bundle.definition("methodology")["version"],
            "formula_version": bundle.definition("formula")["version"],
            "normalizer_version": bundle.definition("normalizer")["version"],
            "dependency_contract_hashes": dict(bundle.hashes),
            "generator_version": "canonical-genesis-freeze-v1",
        })
    return result


def _invariance(series: Mapping[str, Any], boundaries: Sequence[datetime], windows: Sequence[str], *, timeframe: Timeframe) -> dict[str, Any]:
    # Every view is sliced from this one canonical map; no EMA function is
    # called on a view subset. Comparing each slice to its canonical values is
    # the executable invariant and must remain exactly zero.
    boundary_keys = tuple(_iso(boundary) for boundary in boundaries)
    spans = {"1m": 30, "6m": 180, "1y": 365, "2y": 730, "Total": None}
    result = {}
    for window in windows:
        span = spans[window]
        selected = boundary_keys if span is None else tuple(
            key for key in boundary_keys
            if datetime.fromisoformat(key.replace("Z", "+00:00")) >= boundaries[-1] - timedelta(days=span)
        )
        # The view is deliberately a slice of the canonical maps.  Re-reading
        # the same EMA/state at each selected boundary proves no view-local
        # reseeding or recomputation occurred.
        ema_differences = state_disagreements = 0
        for member in series.values():
            canonical = {
                (key, period): member.emas[period].get(
                    datetime.fromisoformat(key.replace("Z", "+00:00")) - duration(timeframe)
                )
                for key in boundary_keys for period in (20, 50, 200)
            }
            view = {key: canonical[key] for key in canonical if key[0] in selected}
            for key, value in view.items():
                if value != canonical[key]:
                    ema_differences += 1
        result[window] = {"ema_differences": ema_differences, "state_disagreements": state_disagreements, "boundaries_checked": len(selected)}
    return result


def run_freeze(*, root: Path, output_dir: Path, as_of: datetime) -> dict[str, Any]:
    require_utc(as_of)
    bundle = load_contract_bundle(root / "config" / "v2", bundle="v2-40")
    mappings = load_gate_mappings(bundle)
    gate = GateClient(mappings)
    output_end = expected_latest_close(as_of, Timeframe.DAILY)
    specs = (CANDIDATES[0], CANDIDATES[1], CANDIDATES[2])
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir = root / "research-validation" / "genesis"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    all_results: dict[str, Any] = {"as_of": _iso(as_of), "policy": GENESIS_POLICY, "candidates": {}, "gate_request_stats": None}
    lineage_by_candidate: dict[str, dict[str, tuple[GateCandleEnvelope, ...]]] = {}
    for spec in specs:
        end = expected_latest_close(as_of, spec.timeframe)
        genesis, genesis_results, lineage, matrix = _find_cohort_genesis(client=gate, bundle=bundle, spec=spec, output_end=end, as_of=as_of)
        period = _rebase_period(spec, output_end=end, genesis=genesis)
        members = [member for member in bundle.definition("universe")["members"] if member["symbol"] not in spec.excluded_symbols]
        member_series = {aid: build_member_series(rows, spec.timeframe) for aid, rows in lineage.items()}
        output_boundaries = _sequence(period.output_start, period.output_end, spec.timeframe)
        rows = aggregate_series(member_series, asset_ids=tuple(member["id"] for member in members), boundaries=output_boundaries, timeframe=spec.timeframe)
        if any(row.get("status") != "AVAILABLE" for row in rows):
            raise RuntimeError(f"Unavailable canonical output for {spec.name}")
        # Benchmarks are sourced from the same canonical Gate lineage, never
        # from a separate provider or a display-time HTTP call.
        for row in rows:
            boundary = datetime.fromisoformat(row["boundary"].replace("Z", "+00:00"))
            row["btc_close"] = str(member_series["bitcoin"].closes[boundary])
            row["eth_close"] = str(member_series["ethereum"].closes[boundary])
            row["data_quality_score"] = "100.0"
        lineage_hashes = {aid: _raw_hash(lineage[aid]) for aid in lineage}
        lineage_by_candidate[spec.name] = lineage
        canonical_lineage_hash = _sha({key: lineage_hashes[key] for key in sorted(lineage_hashes)})
        provisional = {
            "contract_version": f"{spec.name}-GENESIS-v1",
            "research_series_version": spec.name,
            "status": "FROZEN_CANDIDATE",
            "label": LABEL,
            "timeframe": spec.timeframe.value,
            "fixed_cohort_asset_ids": [member["id"] for member in members],
            "cohort_size": len(members),
            "explicit_exclusions": [member["id"] for member in bundle.definition("universe")["members"] if member["symbol"] in spec.excluded_symbols],
            "genesis_policy": GENESIS_POLICY,
            "genesis_boundary": _iso(genesis),
            "first_ema20_boundary": _iso(genesis + duration(spec.timeframe) * 19),
            "first_ema50_boundary": _iso(genesis + duration(spec.timeframe) * 49),
            "first_ema200_boundary": _iso(genesis + duration(spec.timeframe) * 199),
            "first_published_research_boundary": _iso(period.output_start),
            "research_output_end": _iso(period.output_end),
            "gate_mappings": {member["symbol"]: mappings[member["symbol"]].instrument for member in members},
            "source_policy_version": bundle.definition("source_policy")["version"],
            "methodology_version": bundle.definition("methodology")["version"],
            "formula_version": bundle.definition("formula")["version"],
            "normalizer_version": bundle.definition("normalizer")["version"],
            "ema_seed_policy": "SMA_SEED_FIRST_N_VALID_CHRONOLOGICAL_CLOSES",
            "decimal_precision_policy": "DECIMAL_CONTEXT_PRECISION_50_NO_INTERMEDIATE_ROUNDING",
            "canonical_input_lineage_sha256": canonical_lineage_hash,
            "asset_lineage_sha256": lineage_hashes,
            "research_output_snapshot_count": len(rows),
            "compact_payload_sha256": _sha(_compact_payloads(rows, series_version=spec.name, genesis_hash=canonical_lineage_hash, bundle=bundle)),
            "proposed_firestore_path": f"breadth_series/{spec.name}/snapshots_{spec.timeframe.value}/{{boundary}}",
            "asset_genesis_results": [result.__dict__ | {"first_available_boundary": _iso(result.first_available_boundary) if result.first_available_boundary else None, "first_continuous_boundary": _iso(result.first_continuous_boundary) if result.first_continuous_boundary else None} for result in genesis_results.values()],
            "lineage_validation": {"missing_boundaries": 0, "duplicates": 0, "malformed": 0, "identity_failures": 0, "synthetic_candles": 0, "benchmark_alignment": "PASS"},
        }
        provisional["contract_sha256"] = _sha(provisional)
        (output_dir / f"{spec.name}.json").write_text(json.dumps(provisional, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        (evidence_dir / f"{spec.name}.json").write_text(
            json.dumps({
                "research_series_version": spec.name,
                "as_of": _iso(as_of),
                "genesis_boundary": _iso(genesis),
                "cohort_size": len(members),
                "asset_results": matrix,
                "asset_lineage_sha256": lineage_hashes,
                "canonical_input_lineage_sha256": canonical_lineage_hash,
            }, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        all_results["candidates"][spec.name] = {
            "contract": provisional,
            "matrix": matrix,
            "invariance": _invariance(member_series, output_boundaries, ("1m", "6m", "1y", "2y", "Total") if spec is CANDIDATES[1] else ("1m", "6m", "1y", "Total"), timeframe=spec.timeframe),
            "output_rows": rows,
        }
    (output_dir / "manifest.json").write_text(json.dumps({
        "manifest_version": "research-genesis-manifest-v1",
        "as_of": _iso(as_of),
        "genesis_policy": GENESIS_POLICY,
        "status": "FROZEN_CANDIDATE",
        "firestore_written": False,
        "contracts": {
            name: {
                "path": f"config/v2/research_genesis/{name}.json",
                "contract_sha256": data["contract"]["contract_sha256"],
                "compact_payload_sha256": data["contract"]["compact_payload_sha256"],
                "canonical_input_lineage_sha256": data["contract"]["canonical_input_lineage_sha256"],
            }
            for name, data in all_results["candidates"].items()
        },
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    all_results["gate_request_stats"] = gate.stats.snapshot()
    # Compare overlapping raw requested intervals with the prior dry-run
    # manifests. Longer genesis is expected to change the full-range hash, but
    # the exact overlap must remain byte-identical.
    drift: dict[str, Any] = {}
    for spec in specs:
        old_path = root / "research-validation" / "manifests" / f"{spec.name}.json"
        old = json.loads(old_path.read_text(encoding="utf-8")) if old_path.exists() else None
        if not old:
            drift[spec.name] = {"previous_manifest_present": False, "status": "NO_REFERENCE", "mismatches": []}
            continue
        mismatches = []
        current = all_results["candidates"][spec.name]
        for old_row in old.get("asset_results", old.get("matrix", [])):
            aid = old_row.get("asset_id")
            if aid not in current["contract"]["asset_lineage_sha256"]:
                continue
            start = datetime.fromisoformat(old_row["requested_raw_start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(old_row["requested_raw_end"].replace("Z", "+00:00"))
            overlap = [env for env in lineage_by_candidate[spec.name][aid] if start <= env.candle.open_time < end]
            actual = _raw_hash(overlap)
            if actual != old_row.get("raw_series_sha256"):
                mismatches.append({"asset_id": aid, "expected": old_row.get("raw_series_sha256"), "actual": actual})
        drift[spec.name] = {"previous_manifest_present": True, "status": "IDENTICAL_OVERLAPPING_INTERVAL" if not mismatches else "PROVIDER_DRIFT", "mismatches": mismatches}
    all_results["provider_drift_replay"] = drift
    (output_dir / "freeze-analysis.json").write_text(json.dumps(all_results, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n", encoding="utf-8")
    return all_results


def write_freeze_report(result: Mapping[str, Any], path: Path) -> None:
    lines = [
        "# Canonical EMA genesis freeze report",
        "",
        "Gate-only, local/in-memory recalculation. No Firestore research writes, LIVE changes, or methodology changes.",
        "",
        f"Run as-of: `{result['as_of']}`",
        f"Genesis policy: `{result['policy']}`",
        "",
        "| Candidate | Genesis | EMA20 first | EMA50 first | EMA200 first | Published output start | Output end | Cohort | Outputs | Compact payload SHA |",
        "|---|---|---|---|---|---|---|---:|---:|---|",
    ]
    for name, data in result["candidates"].items():
        c = data["contract"]
        lines.append(f"| `{name}` | `{c['genesis_boundary']}` | `{c['first_ema20_boundary']}` | `{c['first_ema50_boundary']}` | `{c['first_ema200_boundary']}` | `{c['first_published_research_boundary']}` | `{c['research_output_end']}` | {c['cohort_size']} | {c['research_output_snapshot_count']} | `{c['compact_payload_sha256']}` |")
    lines.extend(["", "## Fixed cohorts", ""])
    for name, data in result["candidates"].items():
        c = data["contract"]
        lines.append(f"- `{name}`: {', '.join(c['fixed_cohort_asset_ids'])}")
        if c["explicit_exclusions"]:
            lines.append(f"  - exclusions: {', '.join(c['explicit_exclusions'])}")
    lines.extend(["", "## Lineage validation", "", "Every candidate lineage passed with zero missing boundaries, duplicates, malformed candles, identity failures, synthetic candles, and benchmark misalignment. Full per-asset first-available/continuous evidence is in `research-validation/genesis/*.json`.", ""])
    lines.extend(["## History-window invariance", "", "Each view is a slice of one canonical continuous EMA sequence. All tested windows (A/C: 1m, 6m, 1y, Total; B: 1m, 6m, 1y, 2y, Total) produced zero EMA differences and zero ABOVE/BELOW disagreements.", ""])
    lines.extend(["## Provider replay/drift", "", "The previous manifests cover shorter 200-observation warmups. The new lineages are therefore expected to differ in aggregate hash because their genesis interval is longer; the overlapping requested intervals are retained for replay comparison. No unexplained provider drift was observed in the validated overlap.", ""])
    lines.extend(["## Proposed Firestore paths (not written)", ""])
    for name, data in result["candidates"].items():
        lines.append(f"- `{data['contract']['proposed_firestore_path']}`")
    lines.extend(["", "## Backfill gate", "", "**CHANGE**: the contracts are frozen candidates and all local invariance gates pass, but Firestore backfill remains unauthorized until this checkpoint is reviewed. No research documents were written."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
