"""Full-range, no-write validation for frozen retrospective candidates.

This module deliberately stops at local validation and in-memory analytical
outputs.  It never imports Firestore writers and never persists raw candles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from concurrent.futures import ThreadPoolExecutor
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Mapping, Sequence

from .breadth import MemberSignals, calculate_breadth
from .cohort import FrozenCohort
from .contracts import ContractBundle, load_contract_bundle
from .domain import PricePoint, ScannerState, scanner_state
from .ema import compute_standard_emas
from .providers.gate import (
    GATE_MAX_CANDLES,
    GateCandleEnvelope,
    GateClient,
    GateError,
    GateMapping,
    load_gate_mappings,
)
from .timeframes import Timeframe, duration, expected_latest_close, require_utc


UTC = timezone.utc
SURVIVORSHIP_LABEL = "RETROSPECTIVE_SURVIVORSHIP_BIASED"
EMA_WARMUP_OBSERVATIONS = 200


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    timeframe: Timeframe
    horizon_days: int
    excluded_symbols: tuple[str, ...] = ()


CANDIDATES = (
    CandidateSpec("BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1", Timeframe.DAILY, 365),
    CandidateSpec(
        "BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1",
        Timeframe.DAILY,
        730,
        ("HYPE",),
    ),
    CandidateSpec("BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1", Timeframe.FOUR_HOUR, 365),
)


@dataclass(frozen=True)
class CandidatePeriod:
    latest_boundary: datetime
    output_start: datetime
    output_end: datetime
    ema_warmup_start: datetime
    raw_close_start: datetime
    expected_raw_count: int
    expected_output_count: int

    @property
    def fetch_start(self) -> datetime:
        """Gate candle-open start for the first EMA warmup observation."""
        return self.ema_warmup_start

    @property
    def fetch_end(self) -> datetime:
        """Exclusive Gate candle-open end; includes the output-end candle."""
        return self.output_end


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


def freeze_period(spec: CandidateSpec, *, as_of: datetime) -> CandidatePeriod:
    """Freeze an inclusive canonical close-boundary interval.

    ``ema_warmup_start`` is the first candle *open* needed for the 200-point
    EMA seed.  Canonical close boundaries therefore begin one interval later.
    The output interval is inclusive and uses the latest completed boundary.
    """
    require_utc(as_of)
    latest = expected_latest_close(as_of, spec.timeframe)
    output_start = latest - timedelta(days=spec.horizon_days)
    output_boundaries = _sequence(output_start, latest, spec.timeframe)
    if not output_boundaries or output_boundaries[-1] != latest:
        raise ValueError(f"horizon is not aligned to {spec.timeframe.value}")
    ema_warmup_start = output_start - duration(spec.timeframe) * EMA_WARMUP_OBSERVATIONS
    raw_close_start = ema_warmup_start + duration(spec.timeframe)
    return CandidatePeriod(
        latest_boundary=latest,
        output_start=output_start,
        output_end=latest,
        ema_warmup_start=ema_warmup_start,
        raw_close_start=raw_close_start,
        # The first output candle is also the 200th observation used by the
        # EMA200 seed, so it is not counted twice in the raw interval.
        expected_raw_count=EMA_WARMUP_OBSERVATIONS + len(output_boundaries) - 1,
        expected_output_count=len(output_boundaries),
    )


@dataclass(frozen=True)
class FetchResult:
    envelopes: tuple[GateCandleEnvelope, ...]
    duplicate_count: int
    page_count: int
    error: str | None = None
    malformed_count: int = 0


def fetch_full_range(
    client: GateClient,
    symbol: str,
    mapping: GateMapping,
    *,
    timeframe: Timeframe,
    period: CandidatePeriod,
    as_of: datetime,
) -> FetchResult:
    """Fetch every Gate page and retain duplicate/conflict evidence."""
    step = duration(timeframe)
    page_span = step * (GATE_MAX_CANDLES - 1)
    cursor = period.fetch_start
    by_open: dict[datetime, GateCandleEnvelope] = {}
    duplicate_count = 0
    pages = 0
    try:
        while cursor < period.fetch_end:
            page_end = min(period.fetch_end, cursor + page_span)
            pages += 1
            rows = client.fetch_candles(
                symbol,
                timeframe=timeframe,
                as_of=as_of,
                from_time=cursor,
                to_time=page_end,
            )
            for envelope in rows:
                open_time = envelope.candle.open_time
                existing = by_open.get(open_time)
                if existing is not None:
                    duplicate_count += 1
                    if existing.source_payload_hash != envelope.source_payload_hash:
                        raise ValueError(
                            f"CONFLICTING_DUPLICATE:{open_time.isoformat()}"
                        )
                else:
                    by_open[open_time] = envelope
            cursor = page_end
    except Exception as exc:  # preserve the exact asset failure in the matrix
        return FetchResult(
            tuple(by_open.values()), duplicate_count, pages,
            f"{type(exc).__name__}: {exc}",
            1 if type(exc).__name__ in {"GateSchemaError", "GateCandleValidationError"} else 0,
        )
    return FetchResult(
        tuple(by_open[key] for key in sorted(by_open)), duplicate_count, pages
    )


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _decimal_text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _raw_hash(envelopes: Sequence[GateCandleEnvelope]) -> str:
    payload = [list(envelope.raw_payload) for envelope in envelopes]
    return sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _output_hash(rows: Sequence[Mapping[str, Any]]) -> str:
    return sha256(
        json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _regime(score: Decimal) -> str:
    if score < 20:
        return "PANIC"
    if score < 40:
        return "FEAR"
    if score < 60:
        return "NEUTRAL"
    if score < 80:
        return "EXPANSION"
    return "EUPHORIA"


def validate_asset(
    *,
    member: Mapping[str, Any],
    mapping: GateMapping,
    fetch: FetchResult,
    period: CandidatePeriod,
    timeframe: Timeframe,
) -> tuple[dict[str, Any], tuple[GateCandleEnvelope, ...]]:
    expected_closes = _sequence(period.raw_close_start, period.output_end, timeframe)
    expected_close_set = set(expected_closes)
    by_close: dict[datetime, GateCandleEnvelope] = {}
    identity_status = "PASS"
    for envelope in fetch.envelopes:
        candle = envelope.candle
        if envelope.mapping.canonical_id != member["id"] or envelope.mapping.instrument != mapping.instrument:
            identity_status = "FAIL"
        by_close[candle.close_time] = envelope
    observed = tuple(by_close[key] for key in sorted(by_close) if key in expected_close_set)
    observed_boundaries = {envelope.candle.close_time for envelope in observed}
    missing = [key for key in expected_closes if key not in observed_boundaries]
    reasons: list[str] = []
    if fetch.error:
        reasons.append(fetch.error)
    if fetch.duplicate_count:
        reasons.append(f"DUPLICATE_BOUNDARIES:{fetch.duplicate_count}")
    if missing:
        reasons.append(f"MISSING_BOUNDARIES:{len(missing)}")
    if identity_status != "PASS":
        reasons.append("IDENTITY_MAPPING_MISMATCH")
    result = {
        "asset_id": member["id"],
        "symbol": member["symbol"],
        "gate_pair": mapping.instrument,
        "requested_raw_start": _iso(period.ema_warmup_start),
        "requested_raw_end": _iso(period.output_end),
        "expected_observation_count": len(expected_closes),
        "observed_observation_count": len(observed),
        "first_observed_boundary": _iso(observed[0].candle.close_time) if observed else None,
        "last_observed_boundary": _iso(observed[-1].candle.close_time) if observed else None,
        "missing_boundary_count": len(missing),
        "duplicate_count": fetch.duplicate_count,
        "malformed_candle_count": fetch.malformed_count,
        "identity_status": identity_status,
        "pagination_pages": fetch.page_count,
        "synthetic_candle_count": 0,
        "result": "PASS" if not reasons else "FAIL",
        "failure_reason": ";".join(reasons) or None,
        "raw_series_sha256": _raw_hash(observed),
    }
    return result, observed


def _compute_candidate(
    *,
    spec: CandidateSpec,
    period: CandidatePeriod,
    members: Sequence[Mapping[str, Any]],
    validated: Mapping[str, Sequence[GateCandleEnvelope]],
    bundle: ContractBundle,
) -> tuple[bool, list[dict[str, Any]], dict[str, Any]]:
    output_boundaries = _sequence(period.output_start, period.output_end, spec.timeframe)
    ema_by_asset: dict[str, dict[int, dict[datetime, Decimal | None]]] = {}
    close_by_asset: dict[str, dict[datetime, Decimal]] = {}
    first_valid: dict[str, str | None] = {"20": None, "50": None, "200": None}
    for member in members:
        asset_id = member["id"]
        envelopes = tuple(validated[asset_id])
        points = tuple(PricePoint(row.candle.open_time, row.candle.close) for row in envelopes)
        emas = compute_standard_emas(points, timeframe=spec.timeframe)
        ema_by_asset[asset_id] = {
            period_number: {point.open_time: point.value for point in values}
            for period_number, values in emas.items()
        }
        close_by_asset[asset_id] = {row.candle.close_time: row.candle.close for row in envelopes}
        for period_number in (20, 50, 200):
            available = next((point.open_time for point in emas[period_number] if point.value is not None), None)
            if available is not None:
                close_boundary = available + duration(spec.timeframe)
                key = str(period_number)
                first_valid[key] = min(first_valid[key], _iso(close_boundary)) if first_valid[key] else _iso(close_boundary)

    cohort = FrozenCohort.create(
        universe_size=len(bundle.definition("universe")["members"]),
        asset_ids=tuple(member["id"] for member in members),
    )
    output_rows: list[dict[str, Any]] = []
    unavailable = 0
    for boundary in output_boundaries:
        target_open = boundary - duration(spec.timeframe)
        signals: dict[str, MemberSignals] = {}
        for member in members:
            aid = member["id"]
            close = close_by_asset[aid].get(boundary)
            states = tuple(
                scanner_state(close, ema_by_asset[aid][period_number].get(target_open))
                for period_number in (20, 50, 200)
            )
            signals[aid] = MemberSignals(*states)
        breadth = calculate_breadth(cohort, signals)
        if breadth.score is None:
            unavailable += 1
            continue
        btc_id = next(member["id"] for member in members if member["symbol"] == "BTC")
        eth_id = next(member["id"] for member in members if member["symbol"] == "ETH")
        row = {
            "boundary": _iso(boundary),
            "breadth_score": _decimal_text(breadth.score),
            "pct_above_ema20": _decimal_text(breadth.percentages[20]),
            "pct_above_ema50": _decimal_text(breadth.percentages[50]),
            "pct_above_ema200": _decimal_text(breadth.percentages[200]),
            "btc_close": _decimal_text(close_by_asset[btc_id].get(boundary)),
            "eth_close": _decimal_text(close_by_asset[eth_id].get(boundary)),
            "cohort_denominator": breadth.denominator,
            "regime": _regime(breadth.score),
        }
        output_rows.append(row)
    benchmark_aligned = all(row["btc_close"] is not None and row["eth_close"] is not None for row in output_rows)
    output_hash = _output_hash(output_rows)
    metadata = {
        "first_valid_ema_boundary": first_valid,
        "first_publishable_boundary": output_rows[0]["boundary"] if output_rows else None,
        "output_count": len(output_rows),
        "unavailable_output_count": unavailable,
        "benchmark_alignment": "PASS" if benchmark_aligned else "FAIL",
        "output_payload_sha256": output_hash,
        "methodology_version": bundle.definition("methodology")["version"],
        "formula_version": bundle.definition("formula")["version"],
        "source_policy_version": bundle.definition("source_policy")["version"],
        "normalizer_version": bundle.definition("normalizer")["version"],
    }
    return unavailable == 0 and benchmark_aligned and len(output_rows) == period.expected_output_count, output_rows, metadata


def compare_overlap(a_rows: Sequence[Mapping[str, Any]], b_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    a_by_boundary = {row["boundary"]: row for row in a_rows}
    b_by_boundary = {row["boundary"]: row for row in b_rows}
    common = sorted(set(a_by_boundary) & set(b_by_boundary))
    if not common:
        return {"common_observation_count": 0, "error": "NO_OVERLAP"}

    def abs_diff(field: str, boundary: str) -> Decimal:
        return abs(Decimal(a_by_boundary[boundary][field]) - Decimal(b_by_boundary[boundary][field]))

    def mean(values: Sequence[Decimal]) -> Decimal:
        return sum(values, Decimal("0")) / Decimal(len(values))

    def correlation(field: str) -> Decimal:
        av = [Decimal(a_by_boundary[key][field]) for key in common]
        bv = [Decimal(b_by_boundary[key][field]) for key in common]
        am, bm = mean(av), mean(bv)
        numerator = sum(((x - am) * (y - bm) for x, y in zip(av, bv)), Decimal("0"))
        den_a = sum(((x - am) ** 2 for x in av), Decimal("0"))
        den_b = sum(((y - bm) ** 2 for y in bv), Decimal("0"))
        if not den_a or not den_b:
            return Decimal("1") if av == bv else Decimal("0")
        with localcontext() as context:
            context.prec = 50
            return numerator / (den_a * den_b).sqrt()

    result = {
        "common_observation_count": len(common),
        "common_start": common[0],
        "common_end": common[-1],
        "mean_absolute_breadth_score_difference": str(mean([abs_diff("breadth_score", key) for key in common])),
        "maximum_absolute_breadth_score_difference": str(max(abs_diff("breadth_score", key) for key in common)),
        "breadth_score_correlation": str(correlation("breadth_score")),
    }
    for field in ("pct_above_ema20", "pct_above_ema50", "pct_above_ema200"):
        diffs = [abs_diff(field, key) for key in common]
        result[f"{field}_mean_absolute_difference"] = str(mean(diffs))
        result[f"{field}_maximum_absolute_difference"] = str(max(diffs))
    disagreements = sum(a_by_boundary[key]["regime"] != b_by_boundary[key]["regime"] for key in common)
    result["regime_disagreement_count"] = disagreements
    result["regime_disagreement_percentage"] = str(Decimal(disagreements) * Decimal("100") / Decimal(len(common)))
    return result


def run_validation(
    *,
    root: Path,
    output_dir: Path,
    as_of: datetime,
    client: GateClient | None = None,
    workers: int = 8,
) -> dict[str, Any]:
    """Run A/B/C full-range validation and write only compact outputs."""
    require_utc(as_of)
    bundle = load_contract_bundle(root / "config" / "v2", bundle="v2-40")
    universe = bundle.definition("universe")["members"]
    mappings = load_gate_mappings(bundle)
    gate = client or GateClient(mappings)
    output_dir.mkdir(parents=True, exist_ok=True)
    periods = {spec.name: freeze_period(spec, as_of=as_of) for spec in CANDIDATES}
    # Fetch each candidate interval independently.  A and B overlap daily
    # history, but B intentionally reaches farther back; sharing a failed
    # older request could incorrectly fail A (for example HYPE's shorter
    # provider history) or blur the exact requested-range evidence.
    fetched: dict[tuple[str, str], FetchResult] = {}
    jobs = [
        (spec, member)
        for spec in CANDIDATES
        for member in universe
        if member["symbol"] not in spec.excluded_symbols
    ]

    def fetch_job(job: tuple[CandidateSpec, Mapping[str, Any]]) -> FetchResult:
        spec, member = job
        return fetch_full_range(
            gate, member["symbol"], mappings[member["symbol"]],
            timeframe=spec.timeframe, period=periods[spec.name], as_of=as_of,
        )

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        for (spec, member), fetch in zip(jobs, executor.map(fetch_job, jobs)):
            fetched[(spec.name, member["symbol"])] = fetch

    manifests: dict[str, Any] = {}
    rows_by_candidate: dict[str, list[dict[str, Any]]] = {}
    for spec in CANDIDATES:
        period = periods[spec.name]
        candidate_members = [member for member in universe if member["symbol"] not in spec.excluded_symbols]
        matrix: list[dict[str, Any]] = []
        validated: dict[str, tuple[GateCandleEnvelope, ...]] = {}
        for member in candidate_members:
            fetch = fetched[(spec.name, member["symbol"])]
            result, observed = validate_asset(
                member=member, mapping=mappings[member["symbol"]], fetch=fetch,
                period=period, timeframe=spec.timeframe,
            )
            matrix.append(result)
            validated[member["id"]] = observed
        if spec.excluded_symbols:
            for member in universe:
                if member["symbol"] in spec.excluded_symbols:
                    matrix.append({
                        "asset_id": member["id"], "symbol": member["symbol"],
                        "gate_pair": mappings[member["symbol"]].instrument,
                        "result": "EXCLUDED", "identity_status": "INTENTIONAL_EXCLUSION",
                        "failure_reason": "FROZEN_COHORT_EXCLUSION",
                    })
        expected_cohort_size = len(universe) - len(spec.excluded_symbols)
        raw_pass = (
            len(candidate_members) == expected_cohort_size
            and all(item["result"] == "PASS" for item in matrix if item["result"] != "EXCLUDED")
        )
        output_pass = False
        output_rows: list[dict[str, Any]] = []
        compute_metadata: dict[str, Any] = {"output_count": 0, "unavailable_output_count": None}
        if raw_pass:
            output_pass, output_rows, compute_metadata = _compute_candidate(
                spec=spec, period=period, members=candidate_members,
                validated=validated, bundle=bundle,
            )
        rows_by_candidate[spec.name] = output_rows
        manifest = {
            "candidate": spec.name,
            "timeframe": spec.timeframe.value,
            "as_of": _iso(as_of),
            "latest_completed_boundary": _iso(period.latest_boundary),
            "output_start": _iso(period.output_start),
            "output_end": _iso(period.output_end),
            "ema200_warmup_start": _iso(period.ema_warmup_start),
            "raw_canonical_close_start": _iso(period.raw_close_start),
            "expected_raw_observation_count": period.expected_raw_count,
            "expected_output_snapshot_count": period.expected_output_count,
            "fixed_cohort_asset_ids": [member["id"] for member in candidate_members],
            "fixed_cohort_symbols": [member["symbol"] for member in candidate_members],
            "excluded_symbols": list(spec.excluded_symbols),
            "asset_results": matrix,
            "raw_validation": "PASS" if raw_pass else "FAIL",
            "output_validation": "PASS" if output_pass else "NOT_RUN" if not raw_pass else "FAIL",
            "estimated_firestore_compact_document_write_count": len(output_rows) if output_pass else 0,
            "manifest_label": SURVIVORSHIP_LABEL,
            "contract_hashes": dict(bundle.hashes),
            "contract_versions": {
                "universe_version": bundle.definition("universe")["version"],
                "source_policy_version": bundle.definition("source_policy")["version"],
                "methodology_version": bundle.definition("methodology")["version"],
                "formula_version": bundle.definition("formula")["version"],
                "normalizer_version": bundle.definition("normalizer")["version"],
            },
            "compute": compute_metadata,
            "gate_request_stats": gate.stats.snapshot(),
        }
        manifests[spec.name] = manifest
        (output_dir / f"{spec.name}.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if all(manifests[name]["output_validation"] == "PASS" for name in rows_by_candidate):
        manifests["BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1"]["robustness_vs_1d_2y"] = compare_overlap(
            rows_by_candidate[CANDIDATES[0].name], rows_by_candidate[CANDIDATES[1].name]
        )
        # Rewrite A after attaching the cross-cohort result so the on-disk
        # machine-readable manifest is complete, not just the returned object.
        a_name = CANDIDATES[0].name
        (output_dir / f"{a_name}.json").write_text(
            json.dumps(manifests[a_name], indent=2, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return {"as_of": _iso(as_of), "manifests": manifests, "gate_stats": gate.stats.snapshot()}


def write_report(result: Mapping[str, Any], path: Path) -> None:
    lines = [
        "# Retrospective full-range dry-run report",
        "",
        "This is read-only Gate validation. No Firestore writes, LIVE changes, or raw candle datasets are produced.",
        "",
        f"Run as-of: `{result['as_of']}`",
        "",
        "## Candidate summary",
        "",
        "| Candidate | Raw validation | Output validation | Cohort | Output count | Raw SHA / output SHA |",
    ]
    lines.append("|---|---|---|---:|---:|---|")
    for name, manifest in result["manifests"].items():
        cohort = len(manifest["fixed_cohort_asset_ids"])
        output = manifest["compute"].get("output_count", 0)
        output_sha = manifest["compute"].get("output_payload_sha256", "—")
        raw_shas = sorted({row.get("raw_series_sha256") for row in manifest["asset_results"] if row.get("raw_series_sha256")})
        raw_sha = sha256("".join(raw_shas).encode("utf-8")).hexdigest() if raw_shas else "—"
        lines.append(f"| `{name}` | **{manifest['raw_validation']}** | **{manifest['output_validation']}** | {cohort} | {output} | `{raw_sha[:16]}…` / `{output_sha[:16]}…` |")
        lines.extend([
            "",
            f"### `{name}`",
            "",
            f"- timeframe: `{manifest['timeframe']}`",
            f"- latest completed boundary: `{manifest['latest_completed_boundary']}`",
            f"- output interval: `{manifest['output_start']}` → `{manifest['output_end']}` (inclusive)",
            f"- EMA200 warmup start (candle open): `{manifest['ema200_warmup_start']}`",
            f"- canonical raw close interval starts: `{manifest['raw_canonical_close_start']}`",
            f"- expected raw observations: `{manifest['expected_raw_observation_count']}`",
            f"- expected output snapshots: `{manifest['expected_output_snapshot_count']}`",
            f"- fixed cohort: `{cohort}` assets",
            "",
            "| Asset | Gate pair | Expected | Observed | Missing | Duplicates | Identity | Result | Failure |",
            "|---|---|---:|---:|---:|---:|---|---|---|",
        ])
        for row in manifest["asset_results"]:
            if row.get("result") == "EXCLUDED":
                lines.append(f"| {row['symbol']} | {row['gate_pair']} | — | — | — | — | INTENTIONAL_EXCLUSION | EXCLUDED | {row['failure_reason']} |")
            else:
                lines.append(f"| {row['symbol']} | {row['gate_pair']} | {row['expected_observation_count']} | {row['observed_observation_count']} | {row['missing_boundary_count']} | {row['duplicate_count']} | {row['identity_status']} | {row['result']} | {row['failure_reason'] or '—'} |")
        lines.extend([
            "",
            f"- first valid EMA boundaries: `{manifest['compute'].get('first_valid_ema_boundary', {})}`",
            f"- first publishable boundary: `{manifest['compute'].get('first_publishable_boundary')}`",
            f"- output payload SHA-256: `{manifest['compute'].get('output_payload_sha256', '—')}`",
            "",
        ])
    a_name = CANDIDATES[0].name
    if "robustness_vs_1d_2y" in result["manifests"].get(a_name, {}):
        lines.extend(["## A vs B overlap robustness", "", "```json", json.dumps(result["manifests"][a_name]["robustness_vs_1d_2y"], indent=2), "```", ""])
    all_pass = all(manifest["output_validation"] == "PASS" for manifest in result["manifests"].values())
    gate_text = (
        "**GO (dry-run gate)**: A, B, and C passed complete raw and local output validation with fixed denominators and no missing boundaries. This report authorizes no Firestore write; a separate Founder authorization is still required for the first compact-document backfill."
        if all_pass
        else "**CHANGE**: at least one candidate failed complete raw/output validation. Do not start a research backfill until the failed asset/range is resolved without shrinking its frozen cohort."
    )
    lines.extend([
        "## Estimated Firestore writes (not executed)",
        "",
        "Each passing candidate would require one compact immutable document per output boundary. These are estimates only; this dry run performed zero Firestore writes.",
        "",
        "| Candidate | Estimated compact documents |",
        "|---|---:|",
    ])
    for name, manifest in result["manifests"].items():
        lines.append(f"| `{name}` | {manifest['estimated_firestore_compact_document_write_count']} |")
    lines.extend([
        "",
        "## Backfill gate",
        "",
        gate_text,
        "",
        "Weekly research remains deferred. Survivorship label: `RETROSPECTIVE_SURVIVORSHIP_BIASED`.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
