# Protocol Emulator ASIC — Jane Street × Tiny Tapeout

*Project brief. Last updated 29 September 2026.*

## Mission

Design an open-source, programmable **protocol emulator ASIC** for Jane Street's
design competition: a tiny processor whose instruction set is built for driving
pins, reading pins and hitting exact timing, so that UART, SPI, I2C and protocols
nobody anticipated run as **firmware loaded after fabrication**.

Winners are fabricated on a Tiny Tapeout shuttle and receive chips on dev boards.

- Competition post: <https://blog.janestreet.com/protocol-emulator-asic-competition/>
- Sign-up for updates: <https://docs.google.com/forms/d/e/1FAIpQLSeF7fq756MegxZRQxotBwUJYZx-cL9MrGjxV0z4uD_J0sADxQ/viewform>
- Questions: asic-competition@janestreet.com

---

## Key facts

| Item | Value |
|---|---|
| Deadline | **18 January 2027** (own target: 11 January) |
| Process | IHP 130 nm SG13CMOS5L ("CMOS5L") via Tiny Tapeout |
| Template | `TinyTapeout/ttihp-verilog-template`, branch `cmos5l` |
| Tile size | **6x4** in `info.yaml` (24 tiles). 8x4 (~30% more) under consideration — page still says 6x4 as of 29 Sep |
| Nominal area | ~200 × 150 µm per tile → ~0.7 mm² |
| Cell budget | Official guide: ~1k cells/tile. Observed on a comparable design: 22.8k cells at 74% utilisation on 5x4. **Plan for ~25k cells on 6x4** |
| Clock | From the Tiny Tapeout harness; assume ~50 MHz until confirmed |
| Shuttle | March 2027 CMOS5L, subject to foundry schedule |
| Licence | Must be open source; building in public is allowed |
| Teams | Strongly recommended by the organisers |

---

## The challenge

### What they ask for

A small CPU with an instruction set designed for pin I/O and cycle-exact timing,
reprogrammable enough to support **new protocols after fabrication**, within its
timing and I/O limits.

- Start with **UART, SPI, I2C**.
- Stretch goals: **low-speed USB, 10 Mbit Ethernet**.
- Also worth considering: JTAG, SWD, PS/2, CAN.
- "Show us anything else your architecture makes possible."

### What is explicitly *not* the answer

Three fixed protocol blocks on one die. The value is in the protocols not yet
thought of — the half-documented serial link on the board being reverse
engineered at 2 a.m.

### How it will be judged

- **"Most novel"** designs get taped out — not the most complete.
- Explicit interest in **verification**: formal methods, constrained-random tests,
  AI-assisted verification. The post closes on the claim that verification will
  matter more as AI-assisted chip design spreads.
- Implication: two protocols done well + one genuinely new idea + a rigorous proof
  story beats six protocols tested by hand.

### Named inspirations

- **RP2040 PIO** — the baseline to beat (details below).
- **TI PRU** (Sitara) — a full 32-bit deterministic RISC core with direct pin
  registers. Far more capable and far too large for 24 tiles.

The post asks directly: *consider what you'd do differently.* The submission must
answer that question.

---

## The core problem

**Programmability and timing determinism pull in opposite directions.**

A CPU earns its keep by branching, and branches make execution time depend on the
path taken. A protocol needs edges at exact instants regardless of what the logic
was doing. The design has to **decouple when the program thinks from when the
wire moves**, along two axes:

- **In time:** a pin edge should fire when the clock says so, not when an
  instruction happens to retire. Then control flow stops perturbing the waveform.
- **In rate:** at ~50 MHz you cannot execute one instruction per bit at 20 Mbaud
  (10BASE-T Manchester). Bits must leave faster than instructions execute, so
  serialisation and line coding belong in hardware; the program supplies framing.

The brute-force decoupling — a deep FIFO of timestamped pin events — does not fit
and cannot react to input. The interesting design space is the cheap
approximations of it.

The verification story is the same problem seen twice: "the bit period is constant
across every control path" is exactly the kind of claim that is proved, not
observed.

---

## Protocols and what they demand

### Roles

The emulator should be able to play **either side** of a protocol, or neither:

- **Controller** (formerly master): drives the clock, starts transactions.
- **Target** (formerly slave): follows someone else's clock — impersonating a
  sensor, EEPROM or flash chip.
- **Monitor:** drives nothing, records traffic between two other devices.

Impersonation and sniffing are core to the debugging / reverse-engineering use
case the organisers named.

### Demands by protocol

| Protocol | What it forces into the design |
|---|---|
| UART | Arbitrary bit periods (fractional timing). RX: timing anchored to an external edge, mid-bit sampling, glitch rejection |
| SPI | Controller: little — you own the clock. Target: reaction latency to an external clock, byte-boundary turnaround within half an SCLK period, abort on CS |
| I2C | Open-drain via output-enable. Read a pin while driving it (ACK, stretching, arbitration). Wait on a pin with timeout. START/STOP deliberately break the data-timing rule. Target: START/STOP can arrive at any moment |
| JTAG / SWD | Branching on sampled input; SWD bus turnaround mid-transaction |
| CAN | Bit stuffing after 5 identical bits; arbitration by read-back, timing-critical |
| Low-speed USB | 1.5 Mbps, NRZI, bit stuffing after 6 ones, CRC-5/CRC-16, differential pair plus single-ended EOP |
| 10BASE-T | Manchester at 10 Mbit/s (20 MHz half-bit rate), CRC-32, preamble detection |

### Difficulty of the baseline roles

| Role | Difficulty | Why |
|---|---|---|
| SPI controller | easy | you own the clock |
| UART transmitter | easy | precise timing only |
| UART receiver | medium | timing from an external edge |
| I2C controller | medium–hard | open-drain, read-back, stretching, ACK turnaround |
| SPI target | hard | reaction latency to someone else's clock |
| I2C target | hardest | START/STOP at any moment |

### Required capabilities (distilled)

- Shift bits out and in, MSB- or LSB-first
- Hit arbitrary bit periods accurately
- Wait for a pin level — with a timeout, and on more than one condition
- Branch on a pin's value
- Switch a pin between driving and released, per cycle (open-drain)
- Read a pin while driving it
- Exchange data **and flags/commands** with the host
- Load new programs after fabrication

Stretch additions: bit stuffing, NRZI/Manchester, CRC — at rates above the
instruction rate.

---

## Physical constraints

### Pins

Tiny Tapeout gives every design the same interface:

| Bank | Template name | Direction |
|---|---|---|
| 8 | `ui_in[7:0]` | input only |
| 8 | `uo_out[7:0]` | output only |
| 8 | `uio_in/out/oe[7:0]` | bidirectional, per-pin output enable |

Plus `clk`, `rst_n`, `ena`.

- The **host link consumes pins** (e.g. an SPI target link: 3 in, 1 out).
- **Only the 8 `uio` pins can turn around.** I2C, SWD, PS/2, USB and any target
  mode driving a shared line must live there. Scarcest resource on the chip.
- Plausible budget after the host link: ~5 in, ~7 out, 8 bidirectional.

### Other constraints

- **No on-chip host.** No CPU, no DMA. Programs and data arrive over pins from an
  external device. Host bandwidth, buffering and underflow behaviour are this
  design's problem, not an afterthought.
- **Storage is expensive.** Flip-flops cost area; SRAM or latch arrays are
  denser for instruction memory (Tiny Tapeout has CMOS5L SRAM examples).
- **No analog.** 10BASE-T into magnetics is an off-chip resistor approximation.
- Synthesise early and often; routing and slow-corner timing bite after
  synthesis looks fine.

---

## Baseline: RP2040 PIO

### What it is

- 2 PIO blocks × 4 state machines (the RP2350 adds a third block).
- **32 instruction slots per block, shared by its 4 state machines.** Host has
  write-only access.
- 9 instructions: `JMP WAIT IN OUT PUSH PULL MOV IRQ SET`, 16 bits each.
- Every instruction takes exactly one cycle, plus an optional delay (up to 31
  cycles) sharing a 5-bit field with **side-set** (drive extra pins in the same
  cycle).
- Per state machine: 32-bit OSR and ISR (shift registers), 32-bit scratch X and Y,
  4-deep TX and RX FIFOs (joinable to 8 one way), 16.8 fractional clock divider,
  IRQ flags.
- Pin mapping: five groups (out, in, set, side-set, jmp pin), each **base + count**.
- Hardware bookkeeping: autopull/autopush, program wrap (free loop jump).
- Instructions can also come from the host (forced), a register (`MOV EXEC`) or
  the data stream (`OUT EXEC`) — the I2C example streams STOP/RESTART this way.
- Roughly the silicon area of one fixed SPI or I2C controller per state machine.

### Weaknesses found so far

| # | Observation | Status |
|---|---|---|
| 1 | Time is expressed by slowing the whole state machine (divider). Bit timing and reaction speed are welded together; small divisors jitter visibly (a 2.5 divider gives 40/60 duty on a 2-cycle wave) | confirmed (3.2.2) |
| 2 | Timing means counting instructions and hand-scheduling overhead into gaps; branches must be padded to equal length | confirmed (3.2.1, 3.2.3) |
| 3 | The program cannot read the time — no way to measure an input pulse except counting loops | open — check 3.4.8 |
| 4 | Nothing protocol-aware: no stuffing, no CRC. Supported list omits USB, CAN, Ethernet | open — check 3.6.5–3.6.6 |
| 5 | Complex protocols consume several state machines and much of the 32 shared slots | evidence (3.2.2) |
| 6 | Pin mapping is consecutive windows, not a crossbar | confirmed (3.2.2) |
| 7 | FIFO underflow silently stalls and stretches timing — fatal for packet protocols | confirmed (3.2.3) |

### Traps if copied

- Everything is 32 bits wide. Most protocols move bytes; 32-bit state is a large
  share of 25k cells.
- 4-deep FIFOs assume on-chip DMA and a fast CPU. An off-chip host needs a
  different answer.
- Window pin mapping fits badly with Tiny Tapeout's fixed three-bank split.

---

## Possible approaches

The design space, as independent axes. The candidate architecture below is one
point in it — not frozen.

### 1. Execution model

| Option | Pros | Cons |
|---|---|---|
| **PIO-style minimal state machine** (few opcodes, one cycle each) | Small, deterministic, proven | Timing burden on the programmer; weak at control-heavy protocols |
| **Small deterministic RISC** (PRU-like) | Expressive, familiar | Large; cycle-exact timing harder to guarantee |
| **General CPU + pin engines** (e.g. RISC-V for control, small engines for timing) | Best of both | Two designs to build and verify; area. One public entry takes this route |
| **Timestamped event scheduler** (program emits "at time t, set pins") | Perfect output timing | Deep queue is expensive; reacting to input is awkward |
| **Barrel / time-multiplexed core** (N contexts, one datapath) | Many state machines for the area of one | Each context runs at clk/N |

### 2. Timing model

- **Delay field per instruction** (PIO) — cheap, but timing = instruction counting.
- **Clock divider** (PIO) — fractional rates, but slows execution and jitters.
- **Deadline register** — free-running cycle counter, `PERIOD` register,
  auto-advancing `DEADLINE`. `WAITD` blocks until the deadline, then adds
  `PERIOD`. Edges become independent of control-flow path length. Fixed-point
  `PERIOD` gives fractional baud rates with ±1-cycle jitter at full clock.
- **Timed pin writes** — the pin change itself is scheduled for the deadline,
  not issued when the instruction runs.
- Rule found while writing timelines: **a wait on a pin or the host must re-arm
  the timing reference at the moment it ends** (UART RX anchors on the start
  edge; UART TX re-arms after waiting for the host).

### 3. Rate decoupling

- One instruction per bit (PIO default) — simplest, limits speed.
- Wide `OUT` to many pins per cycle (PIO's parallel-bus trick).
- **Line-coding unit** between core and pins: NRZI, Manchester, bit stuffing
  (insert after N identical bits), programmable-polynomial LFSR for CRC.
  Serialises at full clock rate while the core handles framing. Needed for USB,
  CAN, 10BASE-T.

### 4. Parallelism and program memory

- Number of state machines (1, 2, 4).
- Shared instruction memory with per-SM base/bound vs fixed partitions.
  (PIO already shares — sharing alone is not novel.)
- Storage: flip-flops (simple, big) vs latch array / DFFRAM vs SRAM macro
  (dense, integration effort — one entry needed a custom power-strap step).
- Instruction width (16 bits a sensible start) and depth.

### 5. Host interface

- Link: SPI target on `ui`/`uo` (likely), UART, or a parallel port.
- FIFO depth and width; behaviour on empty/full: **stall, flag, or abort**.
- Host words carry **flags** (last byte, ACK/NACK decision), not just data.
- Host **commands** with cheap dispatch in the program (PIO's `OUT EXEC`
  equivalent, a jump table, or command bits).
- Non-blocking reads with a default (SPI target sends 0xFF if the host is late).

### 6. Pin mapping

- Windows (base + count) vs per-pin selection vs small crossbar.
- Must respect the fixed bank split; bidirectional work confined to `uio`.
- Open-drain as a first-class mode (drive = OE on with 0; release = OE off).

### 7. Hardware assists

- Input synchronisers (2 flops) and edge detectors on every input.
- **Multi-condition wait with timeout** ("SCLK rises or CS goes high, else
  timeout").
- **Condition detector** watching for patterns in the background — e.g. SDA
  changing while SCL is high (I2C START/STOP), which a sequential program cannot
  watch "at any line".
- Glitch filter / 3-sample majority vote on inputs.
- Clock stretching used deliberately in target modes to hide program latency.

### 8. Capture / monitor mode

State machine records `(pin state, timestamp delta)` into the FIFO. The chip
becomes a logic analyser and protocol decoder as well as an emulator — directly
serving the reverse-engineering use case.

### Candidate architecture v0 (proposed, not frozen)

1. **Deadline-based timing** — decouples in time.
2. **Line-coding unit** — decouples in rate.
3. **2 state machines, time-multiplexed** over one shared instruction memory.
4. **Capture mode** for monitoring.

### Novelty caveat

At least two public entries already pursue close variants:

- `Abagel-coder/protocol-emulator` — describes a time-triggered CPU with proven
  timing and line-coding pin engines (≈ deadlines + LCU + formal timing).
- `kdp1965/ihp-um-janestreet-prism` — PRISM programmable state-machine engine
  driven by a TinyQV RISC-V SoC, already hardening.

The decoupling idea is validated by independent convergence, but it will not be
"most novel" on its own. **The competitor survey (week 0) decides the
differentiator.** Directions worth evaluating against it:

- Target/impersonation modes as the headline (I2C/SPI target, event detectors,
  deliberate clock stretching).
- Monitor mode with timestamped capture and on-chip decode.
- First-class missed-deadline semantics (detect, flag, abort frame) instead of
  PIO's silent stall.
- Verification depth as the differentiator (below).

---

## ISA design method

Protocols first, instructions last.

1. Write each protocol as a plain-English timeline, one action per line, tagged
   by kind (`pin read wait time host shift count jump branch`). **Done in draft**
   for UART TX/RX, SPI controller/target, I2C controller/target.
2. Extract every distinct operation into one list; group it.
3. Find operations that always occur together → fusion candidates (PIO's
   side-set + delay exists for this reason).
4. Decide machine state: registers, widths (8/16/32).
5. Draft 8–12 instructions; specify effect, cycles, stall behaviour for each.
6. Encode into a fixed width (start with 16 bits) — where the trade-offs appear.
7. Hand-assemble all protocols; count instructions and cycles; note awkwardness.
8. Test generality with protocols not designed for: PS/2, JTAG, WS2812.
9. Iterate 5–8, then freeze and write the ISS.

Timeline conventions: `wait T` is measured from the previous timing point (lines
in between are free); `wait until …` restarts the timing reference when it ends;
"pull / release" is open-drain.

### Open ISA questions

1. How is time expressed: delay field, deadline, both?
2. What happens when a deadline is missed?
3. Register width: 8, 16 or 32?
4. Pin addressing: windows or individual?
5. How many state machines; how is memory shared?
6. FIFO empty: stall or error?
7. Two-condition waits; timeouts on waits.
8. Flag bits on host words; command dispatch.
9. Background condition detection in hardware?
10. Subroutines (call/return) or inline everything?

---

## Verification strategy

| Level | Question | Method |
|---|---|---|
| Programs | Does the UART program produce valid UART? | Python ISS vs Python protocol models |
| RTL | Does the hardware match the ISS, cycle for cycle? | cocotb lockstep; formal equivalence RTL ≡ ISS (bounded, SymbiYosys) |
| Properties | Do the timing guarantees hold on every path? | SVA in SymbiYosys |
| Robustness | Does it hold for programs nobody wrote by hand? | Constrained-random program generation, ISS vs RTL |
| Physical | Does the hardened netlist behave and meet timing? | Gate-level sim, STA at slow corner, precheck |
| Silicon proxy | Does it talk to real devices? | FPGA bring-up against real peripherals, if a board is available |

**Headline property:** for any program, consecutive timed pin edges are exactly
`PERIOD` cycles apart (±1 for fractional periods), independent of control flow.

Document honestly where AI assistance helped and where it produced wrong output —
the organisers named AI-assisted verification as an interest.

---

## Decisions made

| Decision | Choice | Rationale |
|---|---|---|
| HDL | **SystemVerilog**, Yosys-friendly subset; run `sv2v` early | Removes the OCaml learning curve from a 4-month schedule. The CV line is the artifact, not the HDL |
| Testbench | **cocotb** | Existing experience |
| Formal | SymbiYosys + SVA | Well supported; carries the verification story |
| Hardcaml | Optional: one small block (e.g. CRC/LFSR) in November, only if ahead | Real opinion for interviews without betting the tapeout |
| Golden model | Python ISS + assembler, written **before** RTL | Protocols proven in the model before hardware exists |

## Open decisions

- Solo or team.
- 6x4 vs 8x4 (await organiser email).
- The differentiator — after the competitor survey.
- Architecture details — after ISA steps 2–9.

---

## Plan

| Phase | Dates | Work | Exit criterion |
|---|---|---|---|
| 0 · Setup & recon | → 27 Sep (running late) | Sign-up form; harden empty 6x4 template locally; readings; competitor survey | Empty design hardens; one-page survey written |
| 1 · ISA & golden model | → 25 Oct | ISA v0.1; Python ISS + assembler; UART/SPI/I2C passing in the model | **ISA frozen** — the most important gate |
| 2 · RTL | → 29 Nov | Core in SV; cocotb lockstep vs ISS; host interface; weekly synthesis and cell count | Baseline protocols pass on RTL; core hardens within area |
| 3 · Verification & stretch | → 20 Dec | SVA + timing proof; random-program fuzzer; FPGA bring-up; stretch goals only if solid | Properties close; fuzzer clean overnight |
| 4 · Closure & submission | → 11 Jan | Slow-corner timing; precheck; README, docs, verification report | Submitted with a week of buffer |

## Reading list

**Essential**
1. RP2040 datasheet, chapter 3 (PIO), sections 3.1–3.4 — *in progress, at 3.2.3*
2. pico-examples `pio/`: `uart_tx`, `uart_rx`, `spi`, `i2c` — count cycles by hand
3. NXP UM10204 (I2C spec), sections 3.1.1–3.1.10
4. The competition post, reread for judging hints
5. Competitor READMEs (search GitHub: `cmos5l`, `protocol emulator`, `janestreet`)
6. Tiny Tapeout local-hardening guide — while doing setup

**If needed:** Harris & Harris ch. 7 (single-cycle datapath); TI PRU-ICSS overview.

**Later:** SymbiYosys docs (Nov); USB 2.0 ch. 7–8 (stretch); IHP SRAM examples (RTL phase).

---

## Status — 29 September 2026

- Challenge, core problem and baseline protocols understood.
- PIO chapter 3 read through 3.2.3; weakness tracker above.
- Six protocol timelines drafted (ISA method step 1).
- **Next:** extract the operation list (step 2); competitor survey; harden the
  empty template; sign-up form.

## Links

- Competition: <https://blog.janestreet.com/protocol-emulator-asic-competition/>
- Template: <https://github.com/TinyTapeout/ttihp-verilog-template/tree/cmos5l>
- Local hardening: <https://tinytapeout.com/guides/local-hardening/>
- RP2040 datasheet: <https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf>
- PIO examples: <https://github.com/raspberrypi/pico-examples/tree/master/pio>
- I2C spec: <https://www.nxp.com/docs/en/user-guide/UM10204.pdf>
- Hardcaml: <https://hardcaml.org/>
- Competitors: <https://github.com/Abagel-coder/protocol-emulator>,
  <https://github.com/kdp1965/ihp-um-janestreet-prism>
