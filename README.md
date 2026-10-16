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

| Pins | Direction | `RUN=0` (load / cfg) | `RUN=1` (execute) |
|---|---|---|---|
| `ui[0]` | in | HOST_WR (pulse push host FIFO) | same |
| `ui[1]` | in | HOST_RD (pulse pop host read) | same |
| `ui[2]` | in | IMEM_WE (pulse write instruction) | same |
| `ui[3]` | in | RUN = 0 | RUN = 1 |
| `ui[7:4]` | in | CMD nibble (`0x8`…`0xF`) | ignored for load |
| `uio[7:0]` | bidir | load / cfg data (`uio_oe=0`) | logical pins (any of 8 via cfg pinmap) |
| `uo[7:0]` | out | **cfg readback latch** (after CFG_RD `0x8`) | status: `{0, pin0, TICK, MISS, WAITING, HOST_EMPTY, HOST_FULL, HOST_RDATA0}` |

While `!RUN`, `uio_oe = 0` so the host can drive the load bus. A 4-wire host SPI
target on `ui`/`uo` is planned so all eight `uio` stay protocol-only.

## Using the chip

**Load** (with `RUN=0`): put a command nibble on `ui[7:4]` and data on `uio[7:0]`,
then pulse the strobe where needed:

| CMD | Meaning | Strobe |
|---|---|---|
| `0x9` | config address | — |
| `0xF` | config write (`uio` → `cfg[addr]`, then addr++) | rising edge of nibble |
| `0x8` | config read → latch; `uo_out` mirrors the latch | rising edge of nibble |
| `0xA` | instruction address | — |
| `0xB` / `0xC` | instruction lo / hi byte | `IMEM_WE` (`ui[2]`) |
| `0xD` / `0xE` | host word lo / flags | `HOST_WR` (`ui[0]`) |

Then set `RUN=1` (`ui[3]`) to execute. Logical pins map to any `uio[7:0]` via the
config registers (demos often use `uio[0]`).

**Waveforms:** `make test-rtl` writes `verification/rtl/tb.fst`. Open it in
[Surfer](https://surfer-project.org/) or GTKWave.

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
