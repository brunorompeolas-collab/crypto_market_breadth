# Retrospective full-range dry-run report

This is read-only Gate validation. No Firestore writes, LIVE changes, or raw candle datasets are produced.

Run as-of: `2026-09-05T10:30:00Z`

## Candidate summary

| Candidate | Raw validation | Output validation | Cohort | Output count | Raw SHA / output SHA |
|---|---|---|---:|---:|---|
| `BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1` | **PASS** | **PASS** | 40 | 366 | `0e349357d1296e8c…` / `6aedf60c3f2ef11c…` |

### `BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1`

- timeframe: `1d`
- latest completed boundary: `2026-09-05T00:00:00Z`
- output interval: `2025-09-05T00:00:00Z` → `2026-09-05T00:00:00Z` (inclusive)
- EMA200 warmup start (candle open): `2025-02-17T00:00:00Z`
- canonical raw close interval starts: `2025-02-18T00:00:00Z`
- expected raw observations: `565`
- expected output snapshots: `366`
- fixed cohort: `40` assets

| Asset | Gate pair | Expected | Observed | Missing | Duplicates | Identity | Result | Failure |
|---|---|---:|---:|---:|---:|---|---|---|
| BTC | BTC_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| ETH | ETH_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| BNB | BNB_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| SOL | SOL_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| XRP | XRP_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| DOGE | DOGE_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| GRAM | GRAM_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| ADA | ADA_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| SHIB | SHIB_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| AVAX | AVAX_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| TRX | TRX_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| DOT | DOT_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| BCH | BCH_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| LINK | LINK_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| NEAR | NEAR_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| LTC | LTC_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| ICP | ICP_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| FET | FET_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| XLM | XLM_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| APT | APT_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| STX | STX_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| UNI | UNI_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| ETC | ETC_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| RENDER | RENDER_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| INJ | INJ_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| FIL | FIL_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| ATOM | ATOM_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| IMX | IMX_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| VET | VET_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| OP | OP_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| GRT | GRT_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| TAO | TAO_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| SUI | SUI_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| AAVE | AAVE_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| ALGO | ALGO_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| LDO | LDO_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| HYPE | HYPE_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| ZEC | ZEC_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| HBAR | HBAR_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |
| ONDO | ONDO_USDT | 565 | 565 | 0 | 0 | PASS | PASS | — |

- first valid EMA boundaries: `{'20': '2025-03-09T00:00:00Z', '200': '2025-09-05T00:00:00Z', '50': '2025-04-08T00:00:00Z'}`
- first publishable boundary: `2025-09-05T00:00:00Z`
- output payload SHA-256: `6aedf60c3f2ef11c565271e3b0f244f1a683e4ab523cce94159f5c024faec66b`

| `BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1` | **PASS** | **PASS** | 39 | 731 | `e1aa768ab0b01446…` / `44741499c1ccf28d…` |

### `BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1`

- timeframe: `1d`
- latest completed boundary: `2026-09-05T00:00:00Z`
- output interval: `2024-09-05T00:00:00Z` → `2026-09-05T00:00:00Z` (inclusive)
- EMA200 warmup start (candle open): `2024-02-18T00:00:00Z`
- canonical raw close interval starts: `2024-02-19T00:00:00Z`
- expected raw observations: `930`
- expected output snapshots: `731`
- fixed cohort: `39` assets

| Asset | Gate pair | Expected | Observed | Missing | Duplicates | Identity | Result | Failure |
|---|---|---:|---:|---:|---:|---|---|---|
| BTC | BTC_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| ETH | ETH_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| BNB | BNB_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| SOL | SOL_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| XRP | XRP_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| DOGE | DOGE_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| GRAM | GRAM_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| ADA | ADA_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| SHIB | SHIB_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| AVAX | AVAX_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| TRX | TRX_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| DOT | DOT_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| BCH | BCH_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| LINK | LINK_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| NEAR | NEAR_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| LTC | LTC_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| ICP | ICP_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| FET | FET_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| XLM | XLM_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| APT | APT_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| STX | STX_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| UNI | UNI_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| ETC | ETC_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| RENDER | RENDER_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| INJ | INJ_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| FIL | FIL_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| ATOM | ATOM_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| IMX | IMX_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| VET | VET_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| OP | OP_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| GRT | GRT_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| TAO | TAO_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| SUI | SUI_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| AAVE | AAVE_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| ALGO | ALGO_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| LDO | LDO_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| ZEC | ZEC_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| HBAR | HBAR_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| ONDO | ONDO_USDT | 930 | 930 | 0 | 0 | PASS | PASS | — |
| HYPE | HYPE_USDT | — | — | — | — | INTENTIONAL_EXCLUSION | EXCLUDED | FROZEN_COHORT_EXCLUSION |

- first valid EMA boundaries: `{'20': '2024-03-09T00:00:00Z', '200': '2024-09-05T00:00:00Z', '50': '2024-04-08T00:00:00Z'}`
- first publishable boundary: `2024-09-05T00:00:00Z`
- output payload SHA-256: `44741499c1ccf28d35c3512243b184bd120c5fb8fd6311258958d5f3e126feda`

| `BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1` | **PASS** | **PASS** | 40 | 2191 | `5ba301872e1d67a7…` / `98dd095b225535ef…` |

### `BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1`

- timeframe: `4h`
- latest completed boundary: `2026-09-05T08:00:00Z`
- output interval: `2025-09-05T08:00:00Z` → `2026-09-05T08:00:00Z` (inclusive)
- EMA200 warmup start (candle open): `2025-08-03T00:00:00Z`
- canonical raw close interval starts: `2025-08-03T04:00:00Z`
- expected raw observations: `2390`
- expected output snapshots: `2191`
- fixed cohort: `40` assets

| Asset | Gate pair | Expected | Observed | Missing | Duplicates | Identity | Result | Failure |
|---|---|---:|---:|---:|---:|---|---|---|
| BTC | BTC_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| ETH | ETH_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| BNB | BNB_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| SOL | SOL_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| XRP | XRP_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| DOGE | DOGE_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| GRAM | GRAM_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| ADA | ADA_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| SHIB | SHIB_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| AVAX | AVAX_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| TRX | TRX_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| DOT | DOT_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| BCH | BCH_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| LINK | LINK_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| NEAR | NEAR_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| LTC | LTC_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| ICP | ICP_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| FET | FET_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| XLM | XLM_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| APT | APT_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| STX | STX_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| UNI | UNI_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| ETC | ETC_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| RENDER | RENDER_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| INJ | INJ_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| FIL | FIL_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| ATOM | ATOM_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| IMX | IMX_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| VET | VET_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| OP | OP_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| GRT | GRT_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| TAO | TAO_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| SUI | SUI_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| AAVE | AAVE_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| ALGO | ALGO_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| LDO | LDO_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| HYPE | HYPE_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| ZEC | ZEC_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| HBAR | HBAR_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |
| ONDO | ONDO_USDT | 2390 | 2390 | 0 | 0 | PASS | PASS | — |

- first valid EMA boundaries: `{'20': '2025-08-06T08:00:00Z', '200': '2025-09-05T08:00:00Z', '50': '2025-08-11T08:00:00Z'}`
- first publishable boundary: `2025-09-05T08:00:00Z`
- output payload SHA-256: `98dd095b225535ef03a3b119c963a0b724083b5f6277a386578c965cca64192c`

## Estimated Firestore writes (not executed)

Each passing candidate would require one compact immutable document per output boundary. These are estimates only; this dry run performed zero Firestore writes.

| Candidate | Estimated compact documents |
|---|---:|
| `BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1` | 366 |
| `BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1` | 731 |
| `BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1` | 2191 |

## Backfill gate

**GO (dry-run gate)**: A, B, and C passed complete raw and local output validation with fixed denominators and no missing boundaries. This report authorizes no Firestore write; a separate Founder authorization is still required for the first compact-document backfill.

Weekly research remains deferred. Survivorship label: `RETROSPECTIVE_SURVIVORSHIP_BIASED`.
