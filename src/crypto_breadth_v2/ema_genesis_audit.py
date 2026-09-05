"""Local-only decomposition of cohort and EMA-genesis sensitivity.

All calculations use the frozen Decimal EMA/Breadth core.  This module fetches
Gate candles for validation, but has no Firestore dependency and performs no
research or LIVE writes.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .breadth import MemberSignals, calculate_breadth
from .cohort import FrozenCohort
from .contracts import ContractBundle, load_contract_bundle
from .domain import PricePoint, scanner_state
from .ema import compute_standard_emas
from .providers.gate import GateCandleEnvelope, GateClient, GateMapping, load_gate_mappings
from .research_validation import (
    CANDIDATES,
    CandidatePeriod,
    CandidateSpec,
    FetchResult,
    _iso,
    _output_hash,
    compare_overlap,
    fetch_full_range,
    freeze_period,
    validate_asset,
)
from .timeframes import Timeframe, duration, require_utc


UTC = timezone.utc
WEIGHTS = {20: Decimal("0.20"), 50: Decimal("0.30"), 200: Decimal("0.50")}


@dataclass(frozen=True)
class MemberSeries:
    closes: Mapping[datetime, Decimal]
    emas: Mapping[int, Mapping[datetime, Decimal | None]]


def build_member_series(envelopes: Sequence[GateCandleEnvelope], timeframe: Timeframe) -> MemberSeries:
    ordered = tuple(sorted(envelopes, key=lambda item: item.candle.open_time))
    points = tuple(PricePoint(item.candle.open_time, item.candle.close) for item in ordered)
    emas = compute_standard_emas(points, timeframe=timeframe)
    return MemberSeries(
        closes={item.candle.close_time: item.candle.close for item in ordered},
        emas={period: {point.open_time: point.value for point in values} for period, values in emas.items()},
    )


def aggregate_series(
    members: Mapping[str, MemberSeries],
    *,
    asset_ids: Sequence[str],
    boundaries: Sequence[datetime],
    timeframe: Timeframe,
    universe_size: int = 40,
) -> list[dict[str, Any]]:
    cohort = FrozenCohort.create(universe_size=universe_size, asset_ids=asset_ids)
    output: list[dict[str, Any]] = []
    step = duration(timeframe)
    for boundary in boundaries:
        target_open = boundary - step
        signals: dict[str, MemberSignals] = {}
        for asset_id in asset_ids:
            series = members[asset_id]
            close = series.closes.get(boundary)
            states = tuple(scanner_state(close, series.emas[period].get(target_open)) for period in (20, 50, 200))
            signals[asset_id] = MemberSignals(*states)
        result = calculate_breadth(cohort, signals)
        if result.score is None:
            output.append({"boundary": _iso(boundary), "status": "UNAVAILABLE"})
            continue
        output.append({
            "boundary": _iso(boundary),
            "status": "AVAILABLE",
            "breadth_score": str(result.score),
            "pct_above_ema20": str(result.percentages[20]),
            "pct_above_ema50": str(result.percentages[50]),
            "pct_above_ema200": str(result.percentages[200]),
            "cohort_denominator": result.denominator,
            "regime": _regime(result.score),
        })
    return output


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


def _mean(values: Sequence[Decimal]) -> Decimal:
    return sum(values, Decimal("0")) / Decimal(len(values)) if values else Decimal("0")


def per_asset_genesis_sensitivity(
    short: Mapping[str, MemberSeries],
    long: Mapping[str, MemberSeries],
    *,
    asset_ids: Sequence[str],
    boundaries: Sequence[datetime],
    timeframe: Timeframe,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    step = duration(timeframe)
    summaries: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        short_series, long_series = short[asset_id], long[asset_id]
        row: dict[str, Any] = {"asset_id": asset_id, "state_changes": {}, "periods": {}}
        weighted_state_delta = Decimal("0")
        for period in (20, 50, 200):
            absolute: list[Decimal] = []
            relative: list[Decimal] = []
            state_changes = 0
            for boundary in boundaries:
                target_open = boundary - step
                short_ema = short_series.emas[period].get(target_open)
                long_ema = long_series.emas[period].get(target_open)
                if short_ema is None or long_ema is None:
                    continue
                difference = abs(short_ema - long_ema)
                absolute.append(difference)
                if long_ema:
                    relative.append(difference / abs(long_ema))
                close = short_series.closes.get(boundary)
                if scanner_state(close, short_ema) is not scanner_state(close, long_ema):
                    state_changes += 1
                    weighted_state_delta += WEIGHTS[period] * Decimal("100") / Decimal(len(asset_ids))
            row["periods"][str(period)] = {
                "mean_absolute_difference": str(_mean(absolute)),
                "maximum_absolute_difference": str(max(absolute) if absolute else Decimal("0")),
                "mean_relative_difference": str(_mean(relative)),
                "maximum_relative_difference": str(max(relative) if relative else Decimal("0")),
            }
            row["state_changes"][str(period)] = state_changes
        row["weighted_state_contribution_sum"] = str(weighted_state_delta)
        row["total_state_changes"] = sum(row["state_changes"].values())
        summaries.append(row)
    ranked = sorted(
        summaries,
        key=lambda row: (Decimal(row["weighted_state_contribution_sum"]), row["total_state_changes"]),
        reverse=True,
    )
    return summaries, ranked


def decay_table(
    short_rows: Sequence[Mapping[str, Any]],
    long_rows: Sequence[Mapping[str, Any]],
    *,
    output_start: datetime,
) -> list[dict[str, Any]]:
    windows = (
        ("first_30_days", 0, 30),
        ("days_31_90", 30, 90),
        ("days_91_180", 90, 180),
        ("days_181_365_including_terminal_boundary", 180, 366),
    )
    short_by_boundary = {row["boundary"]: row for row in short_rows}
    long_by_boundary = {row["boundary"]: row for row in long_rows}
    result: list[dict[str, Any]] = []
    for label, lower, upper in windows:
        selected = []
        for boundary in sorted(set(short_by_boundary) & set(long_by_boundary)):
            dt = datetime.fromisoformat(boundary.replace("Z", "+00:00"))
            elapsed = (dt - output_start).days
            if lower <= elapsed < upper:
                selected.append(boundary)
        if not selected:
            result.append({"window": label, "observations": 0})
            continue
        subset_short = [short_by_boundary[key] for key in selected]
        subset_long = [long_by_boundary[key] for key in selected]
        metrics = compare_overlap(subset_short, subset_long)
        result.append({"window": label, "observations": len(selected), **metrics})
    return result


def _fetch_inputs(
    *,
    gate: GateClient,
    bundle: ContractBundle,
    spec: CandidateSpec,
    period: CandidatePeriod,
    as_of: datetime,
) -> tuple[dict[str, tuple[GateCandleEnvelope, ...]], list[dict[str, Any]]]:
    universe = bundle.definition("universe")["members"]
    mappings = load_gate_mappings(bundle)
    members = [member for member in universe if member["symbol"] not in spec.excluded_symbols]
    jobs = [(member, mappings[member["symbol"]]) for member in members]

    def fetch_job(job: tuple[Mapping[str, Any], GateMapping]) -> FetchResult:
        member, mapping = job
        return fetch_full_range(gate, member["symbol"], mapping, timeframe=spec.timeframe, period=period, as_of=as_of)

    fetched: dict[str, FetchResult] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        for (member, _mapping), result in zip(jobs, executor.map(fetch_job, jobs)):
            fetched[member["id"]] = result
    validated: dict[str, tuple[GateCandleEnvelope, ...]] = {}
    matrix: list[dict[str, Any]] = []
    for member in members:
        result, envelopes = validate_asset(
            member=member, mapping=mappings[member["symbol"]], fetch=fetched[member["id"]],
            period=period, timeframe=spec.timeframe,
        )
        matrix.append(result)
        validated[member["id"]] = envelopes
    failures = [row for row in matrix if row["result"] != "PASS"]
    if failures:
        raise RuntimeError(f"Genesis audit input validation failed: {failures}")
    return validated, matrix


def run_genesis_audit(*, root: Path, output_dir: Path, as_of: datetime) -> dict[str, Any]:
    require_utc(as_of)
    bundle = load_contract_bundle(root / "config" / "v2", bundle="v2-40")
    mappings = load_gate_mappings(bundle)
    gate = GateClient(mappings)
    spec_a, spec_b = CANDIDATES[0], CANDIDATES[1]
    period_a = freeze_period(spec_a, as_of=as_of)
    period_b = freeze_period(spec_b, as_of=as_of)
    raw_a, matrix_a = _fetch_inputs(gate=gate, bundle=bundle, spec=spec_a, period=period_a, as_of=as_of)
    raw_b, matrix_b = _fetch_inputs(gate=gate, bundle=bundle, spec=spec_b, period=period_b, as_of=as_of)
    members = bundle.definition("universe")["members"]
    by_id = {member["id"]: member for member in members}
    all_ids = tuple(member["id"] for member in members)
    shared_ids = tuple(member["id"] for member in members if member["symbol"] != "HYPE")
    series_a = {aid: build_member_series(raw_a[aid], Timeframe.DAILY) for aid in all_ids}
    series_b = {aid: build_member_series(raw_b[aid], Timeframe.DAILY) for aid in shared_ids}
    boundaries_a = _sequence(period_a.output_start, period_a.output_end, Timeframe.DAILY)
    boundaries_b = _sequence(period_b.output_start, period_b.output_end, Timeframe.DAILY)
    a40_rows = aggregate_series(series_a, asset_ids=all_ids, boundaries=boundaries_a, timeframe=Timeframe.DAILY)
    a39_rows = aggregate_series(series_a, asset_ids=shared_ids, boundaries=boundaries_a, timeframe=Timeframe.DAILY)
    b39_rows = aggregate_series(series_b, asset_ids=shared_ids, boundaries=boundaries_b, timeframe=Timeframe.DAILY)
    b39_overlap = [row for row in b39_rows if row["boundary"] in {item["boundary"] for item in a39_rows}]
    original_confounded = compare_overlap(a40_rows, b39_overlap)
    cohort_effect = compare_overlap(a40_rows, a39_rows)
    genesis_effect = compare_overlap(a39_rows, b39_overlap)
    per_asset, ranked_assets = per_asset_genesis_sensitivity(
        series_a, series_b, asset_ids=shared_ids, boundaries=boundaries_a, timeframe=Timeframe.DAILY,
    )
    decay = decay_table(a39_rows, b39_overlap, output_start=period_a.output_start)
    reference_path = root / "research-validation" / "robustness-1d-1y-a-vs-2y-b.json"
    reference = json.loads(reference_path.read_text(encoding="utf-8")) if reference_path.exists() else None
    result = {
        "as_of": _iso(as_of),
        "periods": {
            "A": period_a.__dict__ | {"latest_boundary": _iso(period_a.latest_boundary), "output_start": _iso(period_a.output_start), "output_end": _iso(period_a.output_end), "ema_warmup_start": _iso(period_a.ema_warmup_start), "raw_close_start": _iso(period_a.raw_close_start)},
            "B": period_b.__dict__ | {"latest_boundary": _iso(period_b.latest_boundary), "output_start": _iso(period_b.output_start), "output_end": _iso(period_b.output_end), "ema_warmup_start": _iso(period_b.ema_warmup_start), "raw_close_start": _iso(period_b.raw_close_start)},
        },
        "cohorts": {"A40": list(all_ids), "A39": list(shared_ids), "B39": list(shared_ids), "B_excluded": ["hyperliquid"]},
        "raw_validation": {"A": matrix_a, "B": matrix_b},
        "original_confounded_a40_vs_b39": original_confounded,
        "cohort_effect_a40_vs_a39": cohort_effect,
        "genesis_effect_a39_short_vs_b39_long": genesis_effect,
        "decay_by_elapsed_time": decay,
        "per_asset_genesis_sensitivity": per_asset,
        "top_assets_by_breadth_discrepancy": ranked_assets[:10],
        "output_hashes": {"A40": _output_hash(a40_rows), "A39": _output_hash(a39_rows), "B39": _output_hash(b39_rows)},
        "reference_comparison": {
            "reference_present": reference is not None,
            "reference_breadth_mean_abs": reference.get("mean_absolute_breadth_score_difference") if reference else None,
            "recomputed_breadth_mean_abs": original_confounded.get("mean_absolute_breadth_score_difference"),
            "reference_max_abs": reference.get("maximum_absolute_breadth_score_difference") if reference else None,
            "recomputed_max_abs": original_confounded.get("maximum_absolute_breadth_score_difference"),
        },
        "gate_request_stats": gate.stats.snapshot(),
        "policy_evaluation": {
            "option_1": "Current minimal warmup is reproducible per requested range but fails cross-window EMA invariance.",
            "option_2": "Fixed genesis per research cohort preserves compatibility and comparability once the genesis boundary is versioned.",
            "option_3": "Earliest fully clean common Gate boundary is the most defensible deterministic choice; it costs more data and may shorten eligible horizons.",
            "recommendation": "OPTION_3_WITH_OPTION_2_PACKAGING",
            "invariance_current_design": "FAIL",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ema-genesis-audit.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    return result


def _sequence(start: datetime, end: datetime, timeframe: Timeframe) -> tuple[datetime, ...]:
    result: list[datetime] = []
    cursor = start
    step = duration(timeframe)
    while cursor <= end:
        result.append(cursor)
        cursor += step
    return tuple(result)


def write_genesis_report(result: Mapping[str, Any], path: Path) -> None:
    def metric_table(title: str, metrics: Mapping[str, Any]) -> list[str]:
        lines = [f"## {title}", "", "| Metric | Value |", "|---|---:|"]
        for key, value in metrics.items():
            lines.append(f"| `{key}` | `{value}` |")
        return lines + [""]

    lines = [
        "# EMA genesis and robustness decomposition audit",
        "",
        "Gate-only, local/in-memory analysis. No Firestore research writes, LIVE changes, formula changes, or UI changes.",
        "",
        f"Run as-of: `{result['as_of']}`",
        "",
        "## Reproduced periods and genesis",
        "",
        "| Candidate | Output interval | EMA warmup start (open) | Raw observations | Output observations |",
        "|---|---|---|---:|---:|",
    ]
    for label in ("A", "B"):
        p = result["periods"][label]
        lines.append(f"| {label} | `{p['output_start']}` → `{p['output_end']}` | `{p['ema_warmup_start']}` | {p['expected_raw_count']} | {p['expected_output_count']} |" )
    lines.extend([
        "",
        "A uses a 200-observation EMA genesis immediately before its 1-year output. B uses a separate 200-observation warmup before its 2-year output, so its EMA path has approximately one additional year of recursive history on the common dates. The 39 shared assets therefore can have different EMA states even when their output dates match.",
        "",
    ])
    lines += metric_table("Original confounded A40 vs B39", result["original_confounded_a40_vs_b39"])
    lines += metric_table("Isolated cohort effect A40 vs A39", result["cohort_effect_a40_vs_a39"])
    lines += metric_table("Isolated EMA-genesis effect A39-short vs B39-long", result["genesis_effect_a39_short_vs_b39_long"])
    lines.extend(["## Genesis discrepancy decay", "", "| Window | Observations | Mean score diff | Max score diff | EMA20 mean/max | EMA50 mean/max | EMA200 mean/max | Regime disagreements |", "|---|---:|---:|---:|---|---|---|---:|"])
    for row in result["decay_by_elapsed_time"]:
        lines.append(f"| `{row['window']}` | {row.get('observations', 0)} | {row.get('mean_absolute_breadth_score_difference', '—')} | {row.get('maximum_absolute_breadth_score_difference', '—')} | {row.get('pct_above_ema20_mean_absolute_difference', '—')} / {row.get('pct_above_ema20_maximum_absolute_difference', '—')} | {row.get('pct_above_ema50_mean_absolute_difference', '—')} / {row.get('pct_above_ema50_maximum_absolute_difference', '—')} | {row.get('pct_above_ema200_mean_absolute_difference', '—')} / {row.get('pct_above_ema200_maximum_absolute_difference', '—')} | {row.get('regime_disagreement_count', '—')} |")
    lines.extend(["", "The last window includes the terminal boundary (elapsed days 180–365) because the frozen inclusive output interval contains 366 daily boundaries.", "", "## Per-asset EMA genesis sensitivity", "", "| Asset ID | EMA20 mean abs | EMA50 mean abs | EMA200 mean abs | EMA20/50/200 state changes | Weighted contribution |", "|---|---:|---:|---:|---|---:|"])
    for row in result["top_assets_by_breadth_discrepancy"]:
        p = row["periods"]
        lines.append(f"| `{row['asset_id']}` | {p['20']['mean_absolute_difference']} | {p['50']['mean_absolute_difference']} | {p['200']['mean_absolute_difference']} | {row['state_changes']['20']} / {row['state_changes']['50']} / {row['state_changes']['200']} | {row['weighted_state_contribution_sum']} |")
    lines.extend([
        "",
        "The complete 39-asset per-asset table, relative differences, maxima, and state-change counts are in the machine-readable manifest.",
        "",
        "## Canonical EMA policy decision",
        "",
        "- Option 1: compatible with the current minimal-warmup implementation but not invariant across requested horizons; reject as the canonical research policy.",
        "- Option 2: fixed, versioned genesis per research cohort; reproducible and compatible with SMA-seeded EMA, with additional storage/fetch cost.",
        "- Option 3: choose the earliest fully clean common Gate boundary for each fixed cohort, then expose later horizons as views. Recommended for canonical research because it removes arbitrary genesis selection; package it as Option 2 contracts.",
        "",
        "**Historical EMA invariance: FAIL for the current retrospective candidate design.** A history-window selection must be a view concern; future research contracts must persist one canonical continuous EMA lineage and never recalculate from the selected chart window.",
        "",
        "## Revised A/B/C contract proposal",
        "",
        "- A: `BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1`, fixed 40 assets, `genesis_policy=EARLIEST_FULLY_CLEAN_COMMON_BOUNDARY`, explicit genesis hash/boundary.",
        "- B: `BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1`, fixed 39 assets excluding HYPE, its own explicit earliest-clean genesis boundary/hash.",
        "- C: `BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1`, fixed 40 assets, explicit earliest-clean 4h genesis boundary/hash.",
        "- Any A-vs-B robustness view must disclose both cohort and genesis lineage; an A39 view should use A's 40-cohort genesis when isolating cohort sensitivity.",
        "",
        "## Backfill gate",
        "",
        "**CHANGE**: do not start Firestore research backfill until the Founder selects/version-freezes the canonical EMA genesis policy and adds the explicit genesis boundary/hash to each research contract. This audit itself performed zero Firestore writes.",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

