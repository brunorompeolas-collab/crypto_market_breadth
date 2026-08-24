# EMA reference validation

The accepted BR1 implementation was compared with pandas across BTC, ETH,
SOL, XRP and AAVE vectors for 4h, 1d and 1w, using EMA20, EMA50 and EMA200.
Each comparison used the same 260 ordered positive close values.

BR1 is intentionally SMA-seeded at observation `p`, followed by the exact
recursive update `EMA = EMA + 2*(close-EMA)/(p+1)`. Pandas' ordinary
`Series.ewm(span=p, adjust=False)` seeds from the first observation, so it is
not methodologically equivalent. Its maximum observed deviation was
`5.043144368420087` (ETH/1d/EMA200 at index 199).

For the independent pandas recurrence check, the approved SMA seed was
explicitly injected at `p-1` and pandas then applied the same alpha. The
maximum observed floating-point deviation was `2.2737367544323206e-13`.

The BR1 Decimal/SMA methodology is therefore preserved; no silent seed change
was made.
