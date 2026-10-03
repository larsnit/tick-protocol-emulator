![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/fpga/badge.svg)

# Tick — Protocol Emulator ASIC (Jane Street × Tiny Tapeout)

Programmable pin engine for the [Jane Street protocol-emulator competition](https://blog.janestreet.com/protocol-emulator-asic-competition/).
Timed pin ops land on a **tick** grid while instructions run at full clock — so
bit timing and reaction speed are not welded together the way they are in PIO.

```
          ┌──────────── program (full clk) ────────────┐
 tick ──► │  SET.T / XFER / WAIT.tick  → pin change @L │ ──► uio
          └────────────────────────────────────────────┘
 timer / edge ──► tick stream (PER, PHASE)
```

ISA: [docs/isa.md](docs/isa.md) (v0.2). Datasheet blurb: [docs/info.md](docs/info.md).

## Status

| Item | State |
|---|---|
| Python ISS + assembler (`tick` package) | done — UART/SPI/I2C/WS2812; path-independence and protocol property tests |
| `tick_core` RTL (1 context) | done — cocotb UART TX, queue sweep, UART lockstep |
| Yosys cell count (generic) | **6466** cells for `tt_um_larsnitschke_tick` (headroom on 6×4 ≈25k) |
| Formal (SymbiYosys) | queue invariant **PASS** (k-induction) |
| Engine CLK / 2nd context / host SPI shim | next (ISS has `clk_en`; RTL still single-tick/bit) |
| Known bugs (not fixed yet) | timer-guard on tick-WAIT; no real ISS↔RTL fuzzer yet; GL `udp` line; lockstep skip under `GATES=yes`; Pages deploy |

## Quick start

```bash
git clone <this-repo> && cd janestreet_isa
python3 -m venv .venv && . .venv/bin/activate
pip install -e .

make test-model          # 22 pytest tests
make test-rtl            # needs iverilog + cocotb (3 cocotb tests)
# or: make test          # both
```

Optional: `make formal` (needs SymbiYosys + z3), `make synth` (needs yosys).

## Repo map

```
src/                    SystemVerilog: tick_core + Tiny Tapeout top
sw/tick/                Installable package `tick` (isa, assembler, ISS)
sw/programs/            UART / SPI / I2C / WS2812 assembly
verification/model/     pytest (ISA, protocols, ISS fuzzer); all tests live in verification/
verification/rtl/       cocotb (test_uart_tx, queue_order, lockstep)
verification/formal/    SymbiYosys wrapper + tick.sby
docs/                   info.md (TT datasheet) + isa.md (full ISA)
test/requirements.txt   stub for Tiny Tapeout gl_test (hardcoded path)
```

## How it works

Each context has one tick stream: a timer (`PER` 20.4 fixed-point, `PHASE`) or
an external edge. Timed ops (`SET.T`, `IN.T`, each `XFER` bit, tick-`WAIT`) take
ticks in program order into a two-slot queue (active + pending). Posts land in
the **post-tick** state so a same-cycle completion never strands a pending op.

While the timer runs, an empty active slot on a tick raises **MISS** and applies
a per-context policy (flag / trap / default / stretch). A stopped timer may idle
on an empty host FIFO without corrupting a frame.

The frozen encoding and semantics are in [docs/isa.md](docs/isa.md). The golden
model is `from tick import assemble, Machine`. RTL `tick_core` implements a
**single-context** subset used for bring-up.

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

| Bus | Role |
|---|---|
| `ui[0]` HOST_WR | `ui[1]` HOST_RD | `ui[2]` IMEM_WE | `ui[3]` RUN |
| `ui[7:4]` | load command nibble (`0xA` addr … `0xE` host flags) |
| `uio[7:0]` | protocol + load data while `!RUN` (`uio[0]` = LP0 / TX) |
| `uo[0..5]` | HOST_RDATA0, FULL, EMPTY, WAITING, MISS, TICK; `uo[6]` PIN0_MIRROR |

While `!RUN`, `uio_oe = 0` so the host can drive the load bus. A 4-wire host SPI
target on `ui`/`uo` is planned so all eight `uio` stay protocol-only.

## Verification

| Level | How to run | Current result |
|---|---|---|
| ISS / protocols | `make test-model` | pytest (includes ISS random-program fuzzer) |
| cocotb RTL | `make test-rtl` | **3/3 PASS** (UART TX, queue sweep k=0..20, UART lockstep) |
| Formal | `make formal` | queue invariant **PASS** (k-induction) |
| Gate-level | `make test-gl` (needs `PDK_ROOT` + netlist) | CI via Tiny Tapeout `gl_test` |

Before the queue-ordering fix (commit `69c7e27^`) the formal queue invariant
failed at step 12; it proves on the current core.

Do **not** claim full ISS↔RTL agreement beyond UART lockstep and the queue sweep.
Timing / MISS spacing claims are ISS-tested; only the queue invariant is formally
proved on RTL.

## Building the chip

Tiny Tapeout IHP flow: push triggers `.github/workflows/gds.yaml` (`tt-gds-action`,
`ihp-sg13cmos5l`). Local synth estimate:

```bash
make synth    # prints generic Yosys cell count (~6466 today)
```

Tiles: **6×4** (`info.yaml`). Top: `tt_um_larsnitschke_tick`.

## Limitations / roadmap

**Known bugs (deferred — next change set):** tick-WAIT timer guard; real
ISS↔RTL constrained fuzzer; GL `udp` include line; lockstep currently skipped
under gate-level; GitHub Pages viewer deploy.

**Next features:** second context + scheduler; port engine-clock (two ticks/bit) to
RTL; host SPI shim; LibreLane harden + STA; SymbiYosys in CI.

## AI assistance

Parts of this design and verification were developed with AI coding assistants.
Treat the ISS, cocotb results, and formal runs above as the ground truth — not
chat history.

## License

Apache-2.0 — see [LICENSE](LICENSE).
