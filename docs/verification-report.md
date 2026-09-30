# Verification report — Tick Protocol Emulator

*As of 29 September 2026.*

## What was proved / checked

| Claim | Method | Status |
|---|---|---|
| Assembler matches encoding table | unit tests | pass |
| Tick spacing = integer PER | ISS `test_tick_spacing_integer_period` | pass |
| k-th timed op on k-th tick (path padding) | ISS headline test | pass |
| MISS ⟺ empty queue while timer runs | ISS | pass |
| Stopped timer + empty FIFO is idle | ISS | pass |
| Trap cancels engine | ISS | pass |
| UART TX 8N1 framing (0x55 / 0xA5) | ISS + cocotb RTL | pass |
| SPI target default / under flag | ISS smoke | pass |
| SVA tick/miss properties | SymbiYosys project in `formal/` | reset hygiene **PASS** (k-induction); MISS/tick spacing proven on ISS; deeper RTL asserts deferred |
| Random legal programs do not crash ISS | `scripts/fuzz_iss.py` (50 trials) | pass |

## RTL vs ISS

- RTL `tick_core` is a **single-context** subset (no second SM, no trap/IRQ yet).
- cocotb UART TX uses the same assembled image as the ISS and checks mid-bit samples.
- Full cycle-by-cycle PC lockstep is deferred until the second context and host SPI
  shim land; pin-level agreement on UART TX is the current gate.

## Yosys cell count (generic techmap, not PDK)

~6.4k cells for `tt_um_larsnitschke_tick` including FF instruction memory — under
the ~25k 6x4 budget with headroom for a second context and line coding.

## AI assistance note

The ISS, assembler, RTL, and tests were developed with AI assistance. Wrong outputs
caught in review included: WAIT consuming ticks that belonged to `XFER` (fixed to
match the draft), and a headline-property test that posted the second `SET.T` too
late (test fixed; hardware semantics unchanged). RP2040 errata (findings §5) motivate
keeping timing claims as properties rather than eyeballing waveforms.

## Still open before submission

- Second context + time-multiplex scheduler
- Host SPI target on `ui`/`uo`
- Local LibreLane harden (Docker) + slow-corner STA
- SymbiYosys run in CI
- I2C target stretch policy in RTL
