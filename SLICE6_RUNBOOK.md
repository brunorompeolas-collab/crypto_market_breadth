# Slice 6 candidate shadow runbook

The candidate series is `BR1-LIVE-v2-40-CANDIDATE`. It is not LIVE, has no
inception timestamp, and has no provider fallback.

## Cadence

- 4h: run 10 minutes after each UTC close.
- 1d: run 15 minutes after the UTC daily close.
- 1w: run 25 minutes after Monday 00:00 UTC.
- Recovery: hourly only while an expected boundary is missing.

The runner is an explicit CLI/job entrypoint. Installing a production scheduler
is an operator decision and is not performed by this slice.

## Response matrix

| Condition | Automatic action | Publication | Operator / Founder action |
|---|---|---|---|
| timeout, connection error, 429, 5xx | bounded exponential/full-jitter retry; honor Retry-After | retain last-known-good | inspect if retries exhaust |
| provider schema change | no retry after schema validation | UNAVAILABLE; retain last-known-good | operator investigation; Founder decision if mapping/API contract changes |
| missing candle | hourly recovery request; no synthetic candle | REJECTED/UNAVAILABLE | repair or provider investigation |
| payload conflict | quarantine; never overwrite | REJECTED/UNAVAILABLE | explicit historical repair only |
| rejected candidate snapshot | keep all scanner/member evidence | retain last-known-good | inspect coverage, alignment, and EMA status |
| stale candidate | continue serving last-known-good with age | STALE | operator escalation after agreed SLA |
| PostgreSQL unavailable | bounded connection retry only | no new publication | restore database; no provider fallback |
| scheduled job failure | record failed ingestion run | retain last-known-good | rerun after cause is understood |
| historical repair | explicit `RECOMPUTE` run only | rebuild affected lineage | operator authorization; audit review |
| mapping/delisting change | stop affected asset | no substitution | operator evidence and Founder/product decision |

## Recompute procedure

1. Stop normal writes for the affected boundary.
2. Confirm the quarantined candle and replacement payload.
3. Invoke the explicit historical recompute action.
4. Verify repair audit row, affected EMA chain, snapshots, scanner state, and
   equality with a clean full recomputation.
5. Resume shadow only after PostgreSQL and timestamp checks pass.

Normal incremental ingestion cannot perform step 3 and cannot overwrite a
canonical key.
## Gate E.1 operational activation

The candidate scheduler is activated in the WSL2 systemd user manager using
the checked-in `breadth-v2-shadow-*.timer` units. Each `OnCalendar` expression
contains an explicit `UTC` suffix, the PostgreSQL target, and the immutable
code SHA is stamped into every evidence row. It invokes
`python -m crypto_breadth_v2.schedule`, which owns the approved 4h (+10m),
daily (+15m), weekly (+25m), and hourly missing-candle recovery decisions.
The unit is candidate-only: it loads `BR1-LIVE-v2-40-CANDIDATE`, never sets an
inception timestamp, and has no LIVE/Gemini/fallback path. Cumulative evidence
is written atomically to `reports/shadow_status.json`; activation and preflight
records are kept in `reports/shadow_activation_real.json` and
`reports/shadow_preflight_real.json`.

The prior Vixie/Debian cron configuration is retained only as historical
evidence in `breadth-v2-shadow.crontab` and
`reports/scheduler_hotfix_previous_crontab.txt`; it is no longer installed.
