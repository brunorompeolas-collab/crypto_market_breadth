# Breadth v2 deployment reframe

Production runtime is now intentionally stateless:

`Gate -> GitHub Actions hourly reconciliation -> deterministic v2 compute -> Firestore -> read-only Streamlit`

The local WSL/systemd/PostgreSQL candidate runtime is historical/experimental
evidence. Its four timers are disabled, but the service files, PostgreSQL
databases, reports and commits remain intact for auditability.

## Reconciliation semantics

`.github/workflows/breadth-reconcile.yml` runs at minute 37 of every UTC hour
and can also be dispatched manually. The job discovers the latest successful
Firestore boundary separately for 4h, 1d and 1w, computes all missing completed
boundaries in chronological order, and stops at the first failure. The next
hourly invocation retries that boundary. It does not require the former
`+10/+15/+25` execution offsets; completed-candle UTC boundaries remain frozen.

GitHub scheduled workflows are best-effort and can be delayed or dropped.
Because the reconciler catches up from Firestore rather than trusting one
trigger, this is non-fatal for a macro breadth instrument.

## Firestore result model

Documents use deterministic IDs and immutable replay semantics:

`breadth_series/{series_version}/snapshots_4h/{boundary}`

with equivalent `snapshots_1d` and `snapshots_1w` subcollections. Each document
contains exact decimal strings for quantitative outputs, version identities,
quality/alignment fields, BTC/ETH closes, source/job provenance, and all 40
scanner/member rows. A conflicting write for an existing boundary fails; an
identical replay is a no-op.

## Credentials

The repository currently contains no Firebase project or service-account
configuration. Before the first GitHub run, add only these repository secrets:

`FIREBASE_PROJECT_ID`

`FIREBASE_WRITER_SERVICE_ACCOUNT_JSON`

The Streamlit host must receive the same project ID plus a separate
`FIREBASE_READER_SERVICE_ACCOUNT_JSON` value. The writer account is never used
by Streamlit, and the reader account is never used by GitHub Actions.

No Gate private credential is required for the public spot endpoints.
