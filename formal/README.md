# Formal properties for Tick core

## Run

```sh
sby -f formal/tick.sby
```

Engine: `smtbmc z3`. Depth **30** (`prove: depth 30` in `tick.sby`).

## Properties (in `tick_formal_top.sv`)

| # | Property | Status (post-W2) | Notes |
|---|---|---|---|
| 1 | Queue invariant: `p_kind != 0 → a_kind != 0` | **PASS** (k-induction, depth 30) | **FAIL** on pre-W2 RTL (BMC CE at step 12) |
| 2 | Reset hygiene: after `!rst_n`, miss clear and queue empty | **PASS** | checked one cycle after reset via `$past` |

Timing / MISS spacing remain **ISS-tested** (`model/test_isa.py`), not formally proven on RTL.

## Pre-W2 counterexample

With `formal/pre_w2/` (tick_core at `69c7e27^` + `dbg_p_kind` probe):

```
Assert failed … tick_formal_top.sv:69 … step 12
queue invariant: pending occupied while active empty
```

That is the W2 race formalized.
