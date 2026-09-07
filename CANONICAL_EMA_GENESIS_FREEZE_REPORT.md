# Canonical EMA genesis freeze report

Gate-only, local/in-memory recalculation. No Firestore research writes, LIVE changes, or methodology changes.

Run as-of: `2026-09-05T10:30:00Z`
Genesis policy: `EARLIEST_FULLY_CLEAN_COMMON_BOUNDARY`

| Candidate | Genesis | EMA20 first | EMA50 first | EMA200 first | Published output start | Output end | Cohort | Outputs | Compact payload SHA |
|---|---|---|---|---|---|---|---:|---:|---|
| `BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1` | `2024-10-19T00:00:00Z` | `2024-11-07T00:00:00Z` | `2024-12-07T00:00:00Z` | `2025-05-06T00:00:00Z` | `2025-09-05T00:00:00Z` | `2026-09-05T00:00:00Z` | 40 | 366 | `5c45173d26fd1c175e243c7e481bf48128c3671ea2dbc3c93a29d584f5f2865f` |
| `BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1` | `2024-01-19T00:00:00Z` | `2024-02-07T00:00:00Z` | `2024-03-08T00:00:00Z` | `2024-08-05T00:00:00Z` | `2024-09-05T00:00:00Z` | `2026-09-05T00:00:00Z` | 39 | 731 | `0970356e7ae30c185b09fd1b03aec2b2313bec0b2311e3f53dae4dbfbd4b43ad` |
| `BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1` | `2024-10-18T12:00:00Z` | `2024-10-21T16:00:00Z` | `2024-10-26T16:00:00Z` | `2024-11-20T16:00:00Z` | `2025-09-05T08:00:00Z` | `2026-09-05T08:00:00Z` | 40 | 2191 | `88f3cb08ba9c878040b3294385610aa052b0c854a1710753e0eaf33ed7542d60` |

## Fixed cohorts

- `BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1`: bitcoin, ethereum, binancecoin, solana, ripple, dogecoin, the-open-network, cardano, shiba-inu, avalanche-2, tron, polkadot, bitcoin-cash, chainlink, near, litecoin, internet-computer, fetch-ai, stellar, aptos, blockstack, uniswap, ethereum-classic, render-token, injective-protocol, filecoin, cosmos, immutable-x, vechain, optimism, the-graph, bittensor, sui, aave, algorand, lido-dao, hyperliquid, zcash, hedera-hashgraph, ondo-finance
- `BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1`: bitcoin, ethereum, binancecoin, solana, ripple, dogecoin, the-open-network, cardano, shiba-inu, avalanche-2, tron, polkadot, bitcoin-cash, chainlink, near, litecoin, internet-computer, fetch-ai, stellar, aptos, blockstack, uniswap, ethereum-classic, render-token, injective-protocol, filecoin, cosmos, immutable-x, vechain, optimism, the-graph, bittensor, sui, aave, algorand, lido-dao, zcash, hedera-hashgraph, ondo-finance
  - exclusions: hyperliquid
- `BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1`: bitcoin, ethereum, binancecoin, solana, ripple, dogecoin, the-open-network, cardano, shiba-inu, avalanche-2, tron, polkadot, bitcoin-cash, chainlink, near, litecoin, internet-computer, fetch-ai, stellar, aptos, blockstack, uniswap, ethereum-classic, render-token, injective-protocol, filecoin, cosmos, immutable-x, vechain, optimism, the-graph, bittensor, sui, aave, algorand, lido-dao, hyperliquid, zcash, hedera-hashgraph, ondo-finance

## Lineage validation

Every candidate lineage passed with zero missing boundaries, duplicates, malformed candles, identity failures, synthetic candles, and benchmark misalignment. Full per-asset first-available/continuous evidence is in `research-validation/genesis/*.json`.

## History-window invariance

Each view is a slice of one canonical continuous EMA sequence. All tested windows (A/C: 1m, 6m, 1y, Total; B: 1m, 6m, 1y, 2y, Total) produced zero EMA differences and zero ABOVE/BELOW disagreements.

## Provider replay/drift

The previous manifests cover shorter 200-observation warmups. The new lineages are therefore expected to differ in aggregate hash because their genesis interval is longer; the overlapping requested intervals are retained for replay comparison. No unexplained provider drift was observed in the validated overlap.

## Proposed Firestore paths (not written)

- `breadth_series/BR1-RESEARCH-v2-RETROSPECTIVE-1D-1Y-v1/snapshots_1d/{boundary}`
- `breadth_series/BR1-RESEARCH-v2-RETROSPECTIVE-1D-2Y-v1/snapshots_1d/{boundary}`
- `breadth_series/BR1-RESEARCH-v2-RETROSPECTIVE-4H-1Y-v1/snapshots_4h/{boundary}`

## Backfill gate

**CHANGE**: the contracts are frozen candidates and all local invariance gates pass, but Firestore backfill remains unauthorized until this checkpoint is reviewed. No research documents were written.
