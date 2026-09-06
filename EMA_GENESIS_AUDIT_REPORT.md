# EMA genesis and robustness decomposition audit

Gate-only, local/in-memory analysis. No Firestore research writes, LIVE changes, formula changes, or UI changes.

Run as-of: `2026-09-05T10:30:00Z`

Integration note: remote `origin/main` was `73e449e` and did not contain
approved checkpoint `39c422a` as an ancestor. The checkpoint was incorporated
on this audit branch only; `main` was not modified.

## Reproduced periods and genesis

| Candidate | Output interval | EMA warmup start (open) | Raw observations | Output observations |
|---|---|---|---:|---:|
| A | `2025-09-05T00:00:00Z` → `2026-09-05T00:00:00Z` | `2025-02-17T00:00:00Z` | 565 | 366 |
| B | `2024-09-05T00:00:00Z` → `2026-09-05T00:00:00Z` | `2024-02-18T00:00:00Z` | 930 | 731 |

A uses a 200-observation EMA genesis immediately before its 1-year output. B uses a separate 200-observation warmup before its 2-year output, so its EMA path has approximately one additional year of recursive history on the common dates. The 39 shared assets therefore can have different EMA states even when their output dates match.

## Original confounded A40 vs B39

| Metric | Value |
|---|---:|
| `common_observation_count` | `366` |
| `common_start` | `2025-09-05T00:00:00Z` |
| `common_end` | `2026-09-05T00:00:00Z` |
| `mean_absolute_breadth_score_difference` | `2.159520807061790668348045397` |
| `maximum_absolute_breadth_score_difference` | `13.07051282051282051282051282` |
| `breadth_score_correlation` | `0.99547983278534477043823281736581526146619951486058` |
| `pct_above_ema20_mean_absolute_difference` | `0.9617136051562281070477791792` |
| `pct_above_ema20_maximum_absolute_difference` | `2.5` |
| `pct_above_ema50_mean_absolute_difference` | `1.133879781420765027322404369` |
| `pct_above_ema50_maximum_absolute_difference` | `2.5` |
| `pct_above_ema200_mean_absolute_difference` | `3.578184110970996216897856230` |
| `pct_above_ema200_maximum_absolute_difference` | `26.02564102564102564102564103` |
| `regime_disagreement_count` | `33` |
| `regime_disagreement_percentage` | `9.016393442622950819672131148` |

## Isolated cohort effect A40 vs A39

| Metric | Value |
|---|---:|
| `common_observation_count` | `366` |
| `common_start` | `2025-09-05T00:00:00Z` |
| `common_end` | `2026-09-05T00:00:00Z` |
| `mean_absolute_breadth_score_difference` | `1.153495866610620708981364718` |
| `maximum_absolute_breadth_score_difference` | `2.500` |
| `breadth_score_correlation` | `0.99900916390834748079090057820249493577847634403409` |
| `pct_above_ema20_mean_absolute_difference` | `0.9617136051562281070477791792` |
| `pct_above_ema20_maximum_absolute_difference` | `2.5` |
| `pct_above_ema50_mean_absolute_difference` | `1.133879781420765027322404369` |
| `pct_above_ema50_maximum_absolute_difference` | `2.5` |
| `pct_above_ema200_mean_absolute_difference` | `1.499579655317360235393022281` |
| `pct_above_ema200_maximum_absolute_difference` | `2.5` |
| `regime_disagreement_count` | `15` |
| `regime_disagreement_percentage` | `4.098360655737704918032786885` |

## Isolated EMA-genesis effect A39-short vs B39-long

| Metric | Value |
|---|---:|
| `common_observation_count` | `366` |
| `common_start` | `2025-09-05T00:00:00Z` |
| `common_end` | `2026-09-05T00:00:00Z` |
| `mean_absolute_breadth_score_difference` | `1.057867451310074260893933029` |
| `maximum_absolute_breadth_score_difference` | `12.82051282051282051282051282` |
| `breadth_score_correlation` | `0.99586484846449893159950252448962667198424638780079` |
| `pct_above_ema20_mean_absolute_difference` | `0E-49` |
| `pct_above_ema20_maximum_absolute_difference` | `0E-48` |
| `pct_above_ema50_mean_absolute_difference` | `0E-49` |
| `pct_above_ema50_maximum_absolute_difference` | `0E-48` |
| `pct_above_ema200_mean_absolute_difference` | `2.115734902620148521787866056` |
| `pct_above_ema200_maximum_absolute_difference` | `25.64102564102564102564102564` |
| `regime_disagreement_count` | `18` |
| `regime_disagreement_percentage` | `4.918032786885245901639344262` |

## Genesis discrepancy decay

| Window | Observations | Mean score diff | Max score diff | EMA20 mean/max | EMA50 mean/max | EMA200 mean/max | Regime disagreements |
|---|---:|---:|---:|---|---|---|---:|
| `first_30_days` | 30 | 6.62393162393162393162393162 | 12.82051282051282051282051282 | 0E-49 / 0E-48 | 0E-48 / 0E-48 | 13.24786324786324786324786326 / 25.64102564102564102564102564 | 10 |
| `days_31_90` | 60 | 1.965811965811965811965811967 | 7.692307692307692307692307692 | 0E-49 / 0E-48 | 0E-49 / 0E-48 | 3.931623931623931623931623933 / 15.38461538461538461538461538 | 5 |
| `days_91_180` | 90 | 0.3418803418803418803418803416 | 2.564102564102564102564102564 | 0E-49 / 0E-48 | 0E-49 / 0E-49 | 0.6837606837606837606837606831 / 5.128205128205128205128205128 | 0 |
| `days_181_365_including_terminal_boundary` | 186 | 0.2136752136752136752136752134 | 2.564102564102564102564102564 | 0E-49 / 0E-48 | 0E-49 / 0E-49 | 0.4273504273504273504273504268 / 5.128205128205128205128205128 | 3 |

The last window includes the terminal boundary (elapsed days 180–365) because the frozen inclusive output interval contains 366 daily boundaries.

## Per-asset EMA genesis sensitivity

| Asset ID | EMA20 mean abs | EMA50 mean abs | EMA200 mean abs | EMA20/50/200 state changes | Weighted contribution |
|---|---:|---:|---:|---|---:|
| `injective-protocol` | 1.281869685233482496475969808E-10 | 0.00001440238026886574279184080831 | 0.5375803221825051464146850828 | 0 / 0 / 31 | 39.74358974358974358974358970 |
| `near` | 7.415601419202444553662833246E-12 | 0.00001618248620027077210526668578 | 0.08523619816676322749838684598 | 0 / 0 / 18 | 23.07692307692307692307692306 |
| `bittensor` | 8.717483841224633096943077380E-9 | 0.001348061911062457156376165775 | 6.841715302496735772118018661 | 0 / 0 / 18 | 23.07692307692307692307692306 |
| `ethereum` | 1.959783577273167940103347420E-8 | 0.0001726998994663271180853755332 | 120.5450603071742072997139797 | 0 / 0 / 17 | 21.79487179487179487179487178 |
| `optimism` | 5.649498129142851978527046872E-12 | 0.000001698779899212415218036299229 | 0.03276563728695697536483509590 | 0 / 0 / 16 | 20.51282051282051282051282050 |
| `bitcoin-cash` | 6.592255898070477187205743426E-9 | 0.0007772507545029264178846430082 | 11.48054637428991072563449546 | 0 / 0 / 15 | 19.23076923076923076923076922 |
| `uniswap` | 4.953322359634618650556576191E-11 | 0.00002673785133068216808027333986 | 0.3032400547916425944615228197 | 0 / 0 / 14 | 17.94871794871794871794871794 |
| `tron` | 1.640801987165267109291335017E-13 | 5.159199193647386377999615566E-8 | 0.002508640233356138563923791548 | 0 / 0 / 13 | 16.66666666666666666666666666 |
| `render-token` | 1.600017738822546171460787087E-11 | 0.00003640394736057177663706124773 | 0.09941483046041661067753508577 | 0 / 0 / 13 | 16.66666666666666666666666666 |
| `algorand` | 1.736855380631003846736092554E-12 | 7.057801737175478370482619719E-7 | 0.004051387788176224991776558189 | 0 / 0 / 13 | 16.66666666666666666666666666 |

The complete 39-asset per-asset table, relative differences, maxima, and state-change counts are in the machine-readable manifest.

## Canonical EMA policy decision

- Option 1: compatible with the current minimal-warmup implementation but not invariant across requested horizons; reject as the canonical research policy.
- Option 2: fixed, versioned genesis per research cohort; reproducible and compatible with SMA-seeded EMA, with additional storage/fetch cost.
- Option 3: choose the earliest fully clean common Gate boundary for each fixed cohort, then expose later horizons as views. Recommended for canonical research because it removes arbitrary genesis selection; package it as Option 2 contracts.

**Historical EMA invariance: FAIL for the current retrospective candidate design.** A history-window selection must be a view concern; future research contracts must persist one canonical continuous EMA lineage and never recalculate from the selected chart window.

## Revised A/B/C contract proposal

- A: `BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1`, fixed 40 assets, `genesis_policy=EARLIEST_FULLY_CLEAN_COMMON_BOUNDARY`, explicit genesis hash/boundary.
- B: `BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1`, fixed 39 assets excluding HYPE, its own explicit earliest-clean genesis boundary/hash.
- C: `BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1`, fixed 40 assets, explicit earliest-clean 4h genesis boundary/hash.
- Any A-vs-B robustness view must disclose both cohort and genesis lineage; an A39 view should use A's 40-cohort genesis when isolating cohort sensitivity.

## Backfill gate

**CHANGE**: do not start Firestore research backfill until the Founder selects/version-freezes the canonical EMA genesis policy and adds the explicit genesis boundary/hash to each research contract. This audit itself performed zero Firestore writes.
