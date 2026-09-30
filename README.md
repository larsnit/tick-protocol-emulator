![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Tick — Protocol Emulator ASIC (Jane Street × Tiny Tapeout)

Programmable pin engine whose ISA is built around **ticks**: timed pin ops land on
a period grid while instructions run at full clock. Target/impersonation modes,
first-class miss policies, and an ISS-first verification story differentiate from
PIO and from close deadline-based competitors
([survey](docs/competitor-survey.md)).

- Competition: https://blog.janestreet.com/protocol-emulator-asic-competition/
- ISA (frozen v0.1): [docs/isa.md](docs/isa.md)
- Project brief: [PROJECT.md](PROJECT.md)
- Verification: [docs/verification-report.md](docs/verification-report.md)

## Status

| Item | State |
|---|---|
| Python ISS + assembler | done — UART/SPI/I2C programs assemble; property tests pass |
| `tick_core` RTL (1 context) | done — cocotb UART TX 8N1 pass |
| Yosys cell count | ~6.4k generic cells (headroom on 6x4) |
| Formal SVA / SymbiYosys | reset proof PASS (`sby -f formal/tick.sby`) |
| 2nd context, host SPI, LCU | next |

## Layout

```
model/       Golden ISS, assembler, opcode table, pytest
programs/    UART / SPI / I2C / WS2812 assembly
src/         SystemVerilog (tick_core + Tiny Tapeout top)
test/        cocotb
formal/      SymbiYosys + SVA
docs/        ISA, timelines, survey, verification report
scripts/     fuzzer + lockstep helper
```

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install pytest cocotb
.venv/bin/python -m pytest model/ -q
.venv/bin/python scripts/fuzz_iss.py
cd test && PATH=../.venv/bin:$PATH make -B
```

## What we did differently (vs PIO / competitors)

1. **Ticks, not dividers** — reaction stays at full `clk`; bit grid is separate.
2. **MISS policies** — flag / trap / default / stretch; idle wait ≠ mid-frame underflow.
3. **Target-first** — qualified-edge traps and stretch are first-class (see ISA draft).
4. **ISS before RTL** — protocols and timing properties live on the golden model first.

## License

Apache-2.0, see [LICENSE](LICENSE).
