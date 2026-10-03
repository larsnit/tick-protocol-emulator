# Verification report — Tick Protocol Emulator

*As of 30 September 2026 (review brief W1–W12).*

## What was proved / checked

| Claim | Method | Status |
|---|---|---|
| Assembler matches encoding table | unit tests | pass |
| Tick spacing = integer PER | ISS `test_tick_spacing_integer_period` | pass |
| k-th timed op on k-th tick (padding + branching) | ISS W7 | pass |
| Late post → MISS | ISS W7 | pass |
| MISS ⟺ empty queue while timer runs | ISS | pass |
| Stopped timer + empty FIFO is idle | ISS | pass |
| Trap cancels engine | ISS | pass |
| UART TX 8N1 + back-to-back (ctx1 disabled) | ISS W1 + cocotb | pass |
| WAIT-with-tick is timed (no stop-bit MISS hole) | ISS W3 | pass |
| MFS RX → C := result[8] | ISS W4 | pass |
| Queue post-tick / order sweep | cocotb W2 | pass |
| ISS↔RTL cycle lockstep (UART TX) | cocotb W5 | pass |
| RTL-subset fuzzer | `scripts/fuzz_lockstep_subset.py` | 200/200 |
| Queue invariant (pending⇒active) | SymbiYosys W6 | **PASS** (k-induction) |
| I2C target address ACK | ISS W11 | pass |
| WS2812 MSB-first 2/1 timing | ISS W11 | pass |
| XFER out≤8; clk_en two ticks/bit | ISS W9/W8 | pass |

## RTL vs ISS

- RTL `tick_core` is still a **single-context** subset (no second SM, no full traps).
- Named lockstep Δ = 1 cycle after `run` (see `test/test_lockstep.py`).
- Engine clock (`clk_en` / CPHA) is ISS-first; RTL still single-tick/bit until ported.
- Do **not** claim full ISS↔RTL agreement beyond the UART lockstep + fuzzer subset.

## Formal note

Earlier reset-only PASS was vacuous (`run=0`). The rebuilt wrapper drives free inputs
and proves the queue invariant after the W2 post-tick fix. Timing/`MISS` spacing
claims are **ISS-tested**, not RTL-proven.

## Yosys cell count (generic techmap, not PDK)

**6466 cells** for `tt_um_larsnitschke_tick` including FF instruction memory
(re-run 2026-09-30: `yosys` techmap+abc `stat` on current RTL) — under the
~25k 6x4 budget with headroom for a second context and line coding.

## Still open before submission

- Second context + time-multiplex scheduler
- Port W8 two-tick clock engine to RTL; rewrite SPI/I2C controller programs
- Host SPI target shim on `ui`/`uo` (pin plan ready)
- Local LibreLane harden + slow-corner STA
- SymbiYosys in CI; stronger timer-accumulator induction
