# Formal properties for Tick core

## Run

```sh
sby -f formal/tick.sby
```

Engine: `smtbmc z3`. Depth 30.

## Properties

1. **Queue invariant** (`p_kind != 0 → a_kind != 0`) — catches the W2 race; must PASS after the post-tick queue fix.
2. **Reset hygiene** — while `!rst_n`, miss clear and queue empty.

Timing/`MISS` spacing properties remain proven on the ISS (`model/test_isa.py`). Strengthening RTL induction for the timer accumulator is future work.

## Note on vacuous proofs

The previous formal task asserted only under `!rst_n` with `run=0` and was vacuous. This wrapper drives free `run` / host / imem / pin inputs.
