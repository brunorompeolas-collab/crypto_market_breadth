# Breadth v2 historical research readiness

Audit branch: `codex/breadth-v2-historical-readiness`  
Audit date: 2026-09-03 UTC  
Provider: Gate public spot candles, frozen `BR1-SOURCE-POLICY-v2-GATE-ONLY`

This document is a readiness result, not a backfill authorization. No
Firestore historical snapshots were written.

## Design decision

Retrospective output must use separate, immutable, fixed-cohort contracts. A
research series is never a pre-inception LIVE series and must carry the label
`RETROSPECTIVE_SURVIVORSHIP_BIASED`.

The revised dry-run candidates frozen for the next Founder decision are:

* `BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1`
* `BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1`
* `BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1`

The 1d/1y candidate uses the fixed 40-asset cohort. The 1d/2y candidate uses
the fixed 39-asset cohort with HYPE excluded after full-range validation. The
4h/1y candidate uses the fixed 40-asset cohort. Weekly research is deferred;
the observed weekly availability is not a sufficient basis for a frozen
weekly series in this gate.

Each contract records the exact output interval, raw warmup interval, fixed
asset IDs, Gate mappings, source policy, methodology/formula/normalizer
versions, and survivorship label. EMA20/50/200, chronological SMA seeding,
Decimal arithmetic, gap rejection, completed UTC candles, and formula weights
20/30/50 remain unchanged.

## Availability matrix

The output end is the latest completed UTC boundary observed during the audit:
`2026-09-03T16:00Z` for 4h, `2026-09-03T00:00Z` for 1d, and
`2026-08-31T00:00Z` for weekly. Horizon lengths use 180/365/730 days for 4h
and 365/730/1095 days for 1d; weekly uses 52/104/156 Monday observations.
Raw warmup is 200 observations. Weekly raw warmup is therefore 1,400 daily
observations before the first weekly output.

| timeframe / output horizon | output start (UTC) | raw warmup starts no later than | assets with boundary availability | excluded assets and reason | fixed cohort / coverage | Gate request estimate | output snapshots |
|---|---:|---:|---:|---|---:|---:|---:|
| 4h / 6m | 2026-03-07 | 2026-01-29 | 40 | none observed | 40 / 100% | 80 | ~1,080 |
| 4h / 1y | 2025-09-03 | 2025-08-01 | 40 | none observed | 40 / 100% | 120 | ~2,190 |
| 4h / 2y | 2024-09-03 | 2024-08-01 | 39 | HYPE: no Gate 4h rows at the raw-start probe | 39 / 97.5% | 200 | ~4,380 |
| 1d / 1y | 2025-09-03 | 2025-02-15 | 40 | none observed | 40 / 100% | 40 | ~365 |
| 1d / 2y | 2024-09-03 | 2024-02-15 | 39 | HYPE: no Gate daily rows at the raw-start probe | 39 / 97.5% | 40 | ~730 |
| 1d / 3y | 2023-09-03 | 2023-02-15 | 35 | GRAM, TAO, SUI, HYPE, ONDO: no Gate daily rows at the raw-start probe | 35 / 87.5% | 80 | ~1,095 |
| 1w / 1y | 2025-09-01 | 2021-11-01 | 32 | GRAM, APT, IMX, OP, TAO, SUI, HYPE, ONDO: no daily rows at weekly warmup probe | 32 / 80% | 80 | ~52 |
| 1w / 2y | 2024-09-02 | 2020-11-02 | 25 | GRAM, ICP, FET, APT, RENDER, INJ, IMX, OP, GRT, TAO, SUI, LDO, HYPE, ONDO, plus no contiguous proof yet | 25 / 62.5% | 120 | ~104 |
| 1w / 3y | 2023-09-04 | 2019-11-04 | 18 | SOL, GRAM, SHIB, AVAX, DOT, NEAR, ICP, FET, APT, UNI, RENDER, INJ, IMX, OP, GRT, TAO, SUI, AAVE, LDO, HYPE, HBAR, ONDO | 18 / 45% | 120 | ~156 |

The Gate probes sampled the raw-start boundary and confirmed the latest
completed page. They are a structural availability screen, not permission to
skip canonical full-range validation. Before any backfill, every proposed
cohort must pass a complete paginated fetch with zero missing expected UTC
boundaries, valid OHLC, provider-complete flags, and identity-clean history.
An asset failing that full check is excluded from that immutable series; the
denominator is never changed mid-series.

The 1w / 1y row is the first useful weekly screen at exactly 80% structural
coverage, but it is deferred from the frozen dry-run plan rather than silently
shrunk or exposed as a research series.

## Storage recommendation

Use COMPACT aggregate retrospective snapshots. A historical chart needs only
the boundary, three component percentages, Breadth Score, BTC/ETH close,
cohort denominator, quality, and complete provenance/version identity. Keep the
full scanner payload only on the latest LIVE snapshot, as the current UI does.

At the approximate output volumes above, compact documents are about 30–100x
smaller than repeating a 40-member scanner in every historical document. This
also lowers Firestore reads for chart windows and avoids storing redundant
per-asset state that is not used by the retrospective chart. A future audit
requiring member-level reconstruction should use canonical candle/indicator
lineage, not mutate compact snapshots.

## Bounded reads

`SnapshotStore.history()` accepts inclusive UTC `since`/`until` bounds and an
optional chronological `limit`. The in-memory implementation applies the
same semantics. The Firestore adapter streams only the boundary-bounded,
chronologically ordered range, then defensively filters `status == PUBLISHED`
and applies the public limit after that filter. It deliberately does not add a
`status` predicate or a server `.limit()` call, avoiding a status+boundary
composite-index requirement while preserving published-row limit semantics.
The query service forwards these arguments without client-side
full-collection filtering.

The exact bounded Firestore shape is:

```text
collection("breadth_series").document(series).collection(timeframe)
  .where("boundary", ">=", since_iso)       # when supplied
  .where("boundary", "<=", until_iso)       # when supplied
  .order_by("boundary")
  .stream()
```

Rows are status-filtered and limited after streaming. A single-field boundary
range/order is used, so this implementation introduces no composite index.

For UI filters, 1d/1w/1m/6m/1y are converted to a duration and the dashboard
query anchors that duration to the latest usable published snapshot boundary
(latest PUBLISHED snapshot, otherwise last-known-good). Both lower and upper
bounds are sent to Firestore. `Total` remains intentionally unbounded until a
research-series inception boundary is frozen; it does not fabricate a start
date. Freshness/CURRENT status continues to use the real page clock and the
expected completed boundary.

## Revised dry-run and robustness plan

The execution order is frozen as three independent dry-run candidates:

* **A — `BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1`**: fixed 40-asset cohort.
* **B — `BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1`**: fixed 39-asset cohort;
  HYPE is excluded and the denominator is immutable.
* **C — `BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1`**: fixed 40-asset cohort.

Weekly remains deferred pending a separate full-range identity/continuity
decision. No candidate is written by this readiness gate.

After separate approval, a robustness comparison will use the overlapping
one-year interval between A (40 assets) and B (39 assets), without computing it
now. The report will compare Breadth Score level/volatility/correlation,
EMA20/50/200 participation, regime classification, missingness/quality, and
denominator sensitivity, and will state whether HYPE's exclusion materially
changes interpretation.

## Exact next backfill execution plan

1. Freeze one research contract per approved timeframe/horizon, including the
   fixed cohort produced by full-range validation. Do not alter LIVE contracts.
2. Perform a dry-run Gate paginated fetch into local files only; validate all
   expected boundaries, OHLC, completion, Decimal parsing, and identity.
3. Recompute EMAs from the full chronological raw window with the existing
   methodology and formula. Abort the series if any member has a gap or fails
   warmup.
4. Write compact Firestore research snapshots under a separate series path in
   deterministic boundary order, with immutable create/replay/conflict rules.
5. Verify document counts, fixed denominator, provenance hashes, UTC alignment,
   and recompute-vs-incremental equality before exposing the series to any
   research UI.
6. Keep Streamlit pointed at LIVE candidate data until a separate product
   decision authorizes a research selector. Never promote research output to
   LIVE or backdate LIVE inception.
