![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Tick — Protocol Emulator ASIC (Jane Street × Tiny Tapeout)

A **protocol emulator** is a small programmable pin engine: you load a short
program and it drives or samples wires on exact bit timing (UART, SPI, I2C, …)
without a general-purpose CPU in the loop. The [Jane Street × Tiny Tapeout
competition](https://blog.janestreet.com/protocol-emulator-asic-competition/)
asks for such an ASIC on a Tiny Tapeout tile — something you can program to
speak real protocols.

**Tick** does the timing differently from RP2040 PIO. PIO gets bit timing by
counting instructions and padding paths; change the code path and the waveform
moves. Here, timed pin ops (`SET.T`, `XFER`, tick-`WAIT`) are queued onto a
**tick grid** (timer period `PER`, or an external edge). The pin edge lands on
its tick even if the program took a longer or shorter path in between.

```
 clock:   |--|---|--|---|--|---|--|---|--|---
 ticks:        T0          T1          T2
 path A:  SET.T …………… (idle) ………          pin↓ on T0
 path B:  SET.T  NOP NOP NOP ………          pin↓ on T0   ← same edge time
 queue:   [SET.T] posted → waits for next free tick
```

ISA (draft): [docs/isa.md](docs/isa.md). Datasheet blurb: [docs/info.md](docs/info.md).

## Status

| Item | State |
|---|---|
| Python ISS + assembler (`tick` package) | done — UART/SPI/I2C/WS2812 property tests + ISS fuzzer |
| `tick_core` RTL (1 context) | done — cocotb UART TX, queue sweep, UART lockstep |
| Tiny Tapeout harden (IHP) | GDS builds on **6×4**; precheck **9/9**; **8237** cells after P&R; **14%** utilisation; STA not yet reviewed |
| Formal (SymbiYosys) | queue invariant **PASS** (k-induction) |
| Engine CLK / 2nd context / host SPI shim | next (ISS has `clk_en`; RTL still single-tick/bit) |

### Known bugs

- GitHub Pages viewer deploy is unfinished.

## Quick start

```bash
git clone <this-repo> && cd tick-protocol-emulator
python3 -m venv .venv && . .venv/bin/activate
pip install -e .

make test-model          # pytest suite
make test-rtl            # cocotb suite (needs iverilog)
# or: make test
```

Optional: `make formal` (SymbiYosys + z3), `make synth` (yosys, generic cell count).

## Repo map

```
src/                    SystemVerilog: host_fifo, tick_imem, tick_timer,
                        tick_queue, tick_issue, tick_core, TT top
sw/tick/                Installable package `tick` (isa, assembler, ISS)
sw/programs/            UART / SPI / I2C / WS2812 assembly
verification/model/     pytest (ISA, protocols, ISS fuzzer)
verification/rtl/       cocotb suite
verification/formal/    SymbiYosys wrapper + tick.sby
docs/                   info.md (TT datasheet) + isa.md (full ISA draft)
test/requirements.txt   stub for Tiny Tapeout gl_test (hardcoded path);
                        all tests live in verification/
```

## How it works

Each context has one tick stream: a timer (`PER` 20.4 fixed-point, `PHASE`) or
an external edge. Timed ops take ticks in program order into a two-slot queue
(active + pending). Posts land in the **post-tick** state so a same-cycle
completion never strands a pending op.

While the timer runs, an empty active slot on a tick raises **MISS** and applies
a per-context policy (flag / trap / default / stretch). A stopped timer may idle
on an empty host FIFO without corrupting a frame.

Encoding and semantics: [docs/isa.md](docs/isa.md) (draft). Golden model:
`from tick import assemble, Machine`. RTL `tick_core` is a **single-context**
subset for bring-up.

## ISA at a glance

11 opcodes in 16 bits: `SET`, `IN`, `WAIT`, `JMP`, `LDI`, `ALU`, `XFER`, `PULL`,
`PUSH`, `MFS`, `MTS`. Headline property: the k-th timed op executes on the k-th
tick (plus fixed output latency L), regardless of intervening instructions.
Read-back latency is architecturally **3 cycles**.

## Walkthrough: `sw/programs/uart_tx.asm`

8N1 UART TX on LP0. Timer stopped while waiting for host data; start bit re-arms
it; stop bit is a queued `SET.T`; a final tick-`WAIT` drains the last stop so
there is no MISS hole before returning to idle.

```
idle:  WAIT   ev0              ; host data available (timer stopped)
       PULL   r0
frame: SET.T  tx=0             ; start bit → starts timer
       XFER   r0, 8, out       ; 8 data bits
       SET.T  tx=1             ; stop bit (queued)
       JMP    HE, done
       PULL   r0
       JMP    AL, frame        ; back-to-back if more data
done:  WAIT   tick, stop       ; consume end-of-stop tick
       JMP    AL, idle
```

## Pinout (Tiny Tapeout)

| Pins | Direction | Signal |
|---|---|---|
| `ui[0]` | in | SCLK |
| `ui[1]` | in | MOSI |
| `ui[2]` | in | CS_n (active low) |
| `ui[3..7]` | in | reserved (tie low) |
| `uo[0]` | out | MISO |
| `uo[1]` | out | IRQ |
| `uo[2]` | out | RUN (mirrors `CTRL.RUN`) |
| `uo[3]` | out | ERR (sticky core error) |
| `uo[4]` | out | MISS |
| `uo[5]` | out | TICK |
| `uo[6..7]` | out | reserved (0) |
| `uio[7:0]` | bidir | protocol pins only (logical pins via cfg pinmap) |

Host link is SPI mode 0, max SCLK = f_clk/8. See `docs/isa.md` § Host link.

## Using the chip

Use `tick.host_link.HostLink` (cocotb or scripts): `load_program`, `cfg_write` /
`cfg_read`, `run`/`stop` (`CTRL.RUN`), `push`/`pull`, `status`. Set `CTRL.RUN=1`
after loading IMEM and config. Logical pins map to any `uio[7:0]` via the config
registers (demos often use `uio[0]`).

**Waveforms:** `make test-rtl` writes `verification/rtl/tb.fst`. Open it in
[Surfer](https://surfer-project.org/) or GTKWave.

## Max SCLK (RTL, 50 MHz clk)

SPI **target** max SCLK is measured host-style: the testbench drives SCLK with
Timer (sub-cycle phase), and samples **MISO on the SCLK rising edge**
(`verification/rtl/test_spi_i2c_milestones.py`, `test_spi_target_miso_timing.py`).
Alternating MISO (`0xAA`/`0x55`) catches stale bits.

**Guaranteed target SCLK with MISO: `f_clk/8` (6.25 MHz @ 50 MHz clk).**
Reasoning (mode 0): a 2-flop synchroniser adds up to ~2 clk of edge jitter;
MISO is registered out (~1 clk) after the launch (falling) tick; the host needs
setup before the sample rise. That budget is ~3 clk after fall, so the
half-period must be ≥4 clk → period ≥8. Use this figure for real hosts / silicon.

**Simulation (zero-delay) limit** is tighter and **not** a timing guarantee: NBA
can make MISO appear on the same clk edge the testbench samples, so period 4
(12.5 MHz) can still pack correct bits in RTL sim. Treat that as a functional
checker pass only.

| Role | Mode | Path | Min period (clk) | Max SCLK | Note |
|---|---|---|---|---|---|
| SPI controller (`PER`, engine clock) | 0 | — | PER=2 → period 4 | **12.5 MHz** | |
| SPI target | 0/3 | MOSI-only | 2.0 | 25.0 MHz | sim / receive path |
| SPI target | 0/3 | MOSI+MISO | **8** | **6.25 MHz** | **guaranteed** |
| SPI target | 0/3 | MOSI+MISO | 4.0 | 12.5 MHz | sim zero-delay only |

Pin timing (mode 0, Timer SCLK, 8 sub-cycle phases within one 20 ns clk,
half-period 85 ns): MISO changes after the **falling** launch edge;
fall→MISO **43–61 ns**; margin to the host sample rise **24–42 ns**
(`MISO_TIMING_NS` in the cocotb log). At period 4 the half is only 40 ns, so
43–61 ns of pad delay overruns the sample edge — sim can still pass via
zero-delay NBA on a shared clk edge.

## Verification

| Level | How to run | Current result |
|---|---|---|
| ISS / protocols | `make test-model` | pytest suite (includes ISS random-program fuzzer) |
| cocotb RTL | `make test-rtl` | cocotb suite (UART TX, queue sweep, UART lockstep, tick-WAIT guard, ISS↔RTL fuzzer) |
| Formal | `make formal` | queue invariant **PASS** (k-induction) |
| Gate-level | `make test-gl` (needs `PDK_ROOT` + netlist) | CI via Tiny Tapeout `gl_test` |

Before the queue-ordering fix (commit `69c7e27^`) the formal queue invariant
failed at step 12; it proves on the current core.

**Module split (STEP 1):** the hierarchical core (`host_fifo`, `tick_imem`,
`tick_timer`, `tick_queue`, `tick_issue`, `tick_core`) was verified by
**cycle-exact agreement with the ISS** on 500 random programs (seed
`0xA11CE2E2`), not by formal equivalence against the pre-split monolith.
Old-vs-new equiv / BMC miters are not a gate for this split.

What is checked today: ISS property tests and protocol checkers; RTL UART TX
framing; queue-order sweep; UART ISS↔RTL lockstep; tick-WAIT timer-guard
path-independence; ISS↔RTL random comparison over the RTL-supported subset;
the formal queue invariant. What is not: formal proofs of tick spacing / MISS,
second context, or engine-clock RTL.

## Building the chip

Tiny Tapeout IHP flow: push triggers `.github/workflows/gds.yaml` (`tt-gds-action`,
`ihp-sg13cmos5l`). Local generic synth:

```bash
make synth    # prints Yosys techmap cell count (not the P&R number above)
```

Tiles: **6×4** (`info.yaml`). Top: `tt_um_larsnitschke_tick`.

## Roadmap

Second context + scheduler; port engine-clock (two ticks/bit) to RTL; host SPI
shim; STA review; SymbiYosys in CI.

## AI assistance

Large parts of the ISS, assembler, RTL, tests, and docs were drafted with AI
coding assistants. An independent review then found real bugs: a timed-queue
race (pending stranded while active empty), ISS/RTL model mismatches, a vacuous
formal proof that never left reset, and wrong example programs. Those were fixed
with regression tests (queue-order sweep, lockstep, property tests); treat the
test and formal results above as ground truth, not chat history.

## License

Apache-2.0 — see [LICENSE](LICENSE).
