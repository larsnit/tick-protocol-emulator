# Formal properties for Tick ISA (SymbiYosys)

Requires SymbiYosys + a SystemVerilog-capable solver setup. Bounded proofs
target the claims in docs/isa.md § Headlined properties.

## Files

- `tick_props.sv` — SVA properties bound to `tick_core`
- `tick.sby` — SymbiYosys project (prove mode, depth 40)

## Headline properties (encoded)

1. While `timer_run`, ticks are ⌊PER⌋ or ⌈PER⌉ apart (integer PER proven exactly).
2. Timed SET edges are `PER` cycles apart when two SET.T ops are posted before the first tick.
3. `miss` rises only when `timer_run && tick && a_kind==0` at tick time.
4. After cancel/trap (future), engine kinds are empty — stub until trap RTL lands.

## How to run

```sh
sby -f formal/tick.sby
```

Uses `smtbmc z3` (boolector is not required). Current proof: reset hygiene
(k-induction PASS). Timing/`MISS` claims are proven on the ISS; stronger RTL
asserts will be added as the second context lands.

If SymbiYosys is not installed, the ISS tests in `model/test_isa.py` remain the
authoritative check of the timing claims on the golden model.
