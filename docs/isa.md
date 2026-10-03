# Protocol Emulator ASIC — ISA v0.2 ("Tick")

*v0.1 written 29 September 2026; updated to v0.2 on 30 September 2026 after the
repo review.*

**Status: draft, not frozen.** The ISA freezes only when every baseline program
passes on the ISS against a protocol model *and* in cycle lockstep between the
ISS and the RTL.

This document is the complete ISA specification. The software encoding table in
`sw/tick/isa.py` must match it; the cycle-accurate ISS in `sw/tick/iss.py` is the
executable reference.

---

## 0. What changed from v0.1

| Item | Change |
|---|---|
| Context enable | Each context has a host-controlled `enabled` bit. A disabled context never issues |
| Timed-queue ordering | A new timed op goes into the queue **after** the current cycle's tick has been applied (post-tick state). ISS and RTL must do exactly the same |
| Tick-consuming WAIT | A `WAIT` with TICK in its mask is a real queue entry that consumes a tick. Three new rules: same-cycle event and tick; starting a stopped timer; illegal combinations |
| MFS RX carry | `MFS rd, RX` always sets `C := result[8]` |
| Engine clock | *Proposal, awaiting approval:* clocked protocols use two ticks per bit in both roles; the engine can drive a clock pin |
| XFER width | `XFER` out/both: 1–8 bits; in: 1–16 bits |
| Engine pin selection | Engine pins (DOUT, DIN, CLK) are chosen per context, not hard-wired to LP0/LP1 |
| — | Read-back latency fixed at **3 cycles** |

---

## 1. Core idea: every timed action waits for a tick

1. **Each context has one tick stream.** Its source is either:
   - the timer, which ticks every `PER` cycles (fractional period, phase set when
     the timer is re-armed), or
   - an edge on an external pin, such as SCLK. With the engine clock enabled (§4),
     **both** edges of the clock pin are ticks.
2. **Timed operations take ticks strictly in program order.** Timed operations are
   `SET.T`, `IN.T`, each bit of an `XFER` job (two ticks per bit when the engine
   clock is on), and a `WAIT` that includes TICK. The k-th timed operation gets
   the k-th tick.
   - The hardware holds one operation waiting for its tick (*active*), plus one
     queued behind it (*pending*).
   - A new post goes into the first free slot **after** this cycle's tick has been
     applied. So an op posted in the same cycle that the active op completes
     becomes the new active op, never a stranded pending one.
   - Invariant: the pending slot is only ever full when the active slot is full.
   - If both slots are full, the next post stalls the program, not the wire.
3. **A timed action happens on its tick cycle**, plus a fixed output delay L,
   whatever instructions ran in between. **This is the headline property.**
   A context sees its own pin change on its inputs 3 cycles after driving it
   (architectural read-back latency).
4. **A stopped timer restarts in one of two ways:**
   - at an event: `WAIT ev, rearm` sets tick 0 to event time + `PHASE`. The
     hardware does this at the event cycle, not when the instruction resumes;
   - at the first timed operation posted (this includes a tick-`WAIT`):
     tick 0 = post time + `PHASE`.
5. **A tick that passes with nothing in the active slot, while the timer runs,
   sets `MISS`.** A per-context policy decides what happens next:
   - *flag and continue*: stay on the tick grid;
   - *trap*: cancel the queue, drive pins to their idle values, push an error to
     the host;
   - *send default*: e.g. 0xFF for an SPI target;
   - *stretch*: hold the (open-drain) clock low until a job arrives; for an I2C
     target.
6. **Tick-`WAIT` rules:**
   - **Completion by tick:** when the wait entry is active and its tick arrives,
     the tick is consumed, `EVF.TICK` is set, `tc` is applied, and there is **no
     MISS**.
   - **Completion by event:** if another event in the mask fires first, the WAIT
     ends with that event in `EVF`, and the wait entry is removed from the queue.
     That is always safe: the context stalls right after posting it, so it's the
     last entry.
   - **(a) Event and tick in the same cycle** while the wait entry is active: the
     tick is consumed, `EVF` gets both bits, and there's no MISS.
   - **(b) Timer stopped:** posting the wait entry starts the timer (rule 4).
   - **(c) Illegal:** TICK in the mask together with `tc = rearm` or `tc = idle`,
     because those stop the timer the WAIT is waiting on. The assembler rejects
     it; the ISS asserts.

**Consequences:**
- While the timer is stopped, an empty host FIFO is just idle. While it runs, an
  empty queue is an error. That is exactly the distinction PIO's `FDEBUG.TXSTALL`
  cannot make.
- Nothing ever compares absolute times: each tick comes from a down-counter that
  reloads, so there's no wrap-around comparison problem.
- Controllers and targets use the same instructions; only the tick source differs.
  With two ticks per bit in both roles (§4), the engine also behaves the same.

---

## 2. Machine state

### Per context (2 contexts)
- **Control:** `enabled` bit, written by the host. A disabled context never
  issues and never pulls host data.
- **Registers:** PC (6 bits, relative to the context's base address, so programs
  can be loaded anywhere); four 8-bit registers r0–r3.
- **Flags:** Z, C, EVF (which events ended the last WAIT), LAST and CMD (host
  flags from the last PULL).
- **Timer:** `PER` (20.4 fixed point), `PHASE`, and a 16-bit `TIME` counter of
  cycles since the last re-arm.
- **Timed queue:** active + pending slot. Entry kinds: SET, IN, XFER, WAIT.
- **Bit engine:** 16-bit shift register; a result latch with an overrun flag.
  Pin roles DOUT, DIN and (§4) CLK are logical-pin selections in the static setup.
- **Error flags (sticky):** MISS, UNDER, OVERRUN, ARB.
- **Four logical pins (LP0–LP3).** Each maps to any physical pin and has:
  - a mode: input, push-pull or open-drain;
  - an idle value, driven after a trap.
- **Four event selectors (EV0–EV3).** Each has a source:
  - a pin level or edge;
  - a *qualified* edge, e.g. "SDA falls while SCL is high";
  - host data available, or host space available.

  Any event can be marked as a trap with its own vector address.

### Shared
- 64 × 16-bit instruction memory, split between the contexts by base/bound
  registers.
- Host FIFOs of 10-bit words: 8 data bits + LAST + CMD.
- A free-running cycle counter.
- 2-flop synchronisers and optional 3-sample majority filters on all inputs.
- Scheduling: one instruction issued per cycle. Enabled contexts take turns;
  a waiting or disabled context is skipped. With one enabled context, it issues
  every cycle.

### Static setup vs runtime state
Static setup (pin map, engine pins, event selectors, tick source, error policies,
enable mask) is written by the host at load time. Only values that change while
a program runs go through instructions.

### Host link (decided)
SPI target on 4 dedicated pins (SCLK, MOSI, CS_n on `ui`; MISO on `uo`). All
8 `uio` pins are left for protocols. The link must move host words in both
directions **while contexts run**. At ~clk/12 it is enough to load programs and
stream UART and SPI-target demos, but not 10BASE-T.

---

## 3. Instruction set (11 of 16 opcodes)

| Op | Syntax | Effect |
|---|---|---|
| SET | `SET[.T][.E] mask, val` | Drive logical pins. `.E` sets output-enables instead. `.T` = at the next free tick. Open-drain pins treat 0 as drive-low and 1 as release |
| IN | `IN[.T] lp` | C := pin value. `.T` samples at its tick (blocks until then) |
| WAIT | `WAIT evmask[, tc]` | Block until any selected event (EV0–3, TICK); EVF records which. With TICK it's a queue entry (rule 6). An empty mask means sleep until a trap |
| JMP | `JMP cond, addr` | Conditional jump (see §3.1) |
| LDI | `LDI rd, imm8` | Load immediate |
| ALU | `ALU fn rd, rs` | MOV, ADD, SUB, AND, OR, XOR, CMP, SHR; sets Z and C |
| XFER | `XFER [rs,] n, mode` | Post a bit-engine job: `out` and `both` 1–8 bits (from rs), `in` 1–16 bits. One bit per tick (two with the engine clock on), entirely in hardware |
| PULL | `PULL[.NB] rd` | Read from the host FIFO; sets LAST/CMD. `.NB` applies the empty-FIFO policy instead of blocking |
| PUSH | `PUSH rs, tag` | Write to the host FIFO. Tags: DATA, EOF, ERR, EVT |
| MFS | `MFS rd, spr` | Read a special register (see §3.2). `MFS rd, RX` always sets `C := result[8]` (0 for jobs of 8 bits or fewer) and `Z := (rd == 0)` |
| MTS | `MTS spr, rs` | Write a special register (see §3.2) |

**WAIT timer-control field (`tc`):**

| Value | Name | Meaning | With TICK in mask |
|---|---|---|---|
| 00 | (none) | Timer untouched | Legal: the wait entry takes the next free tick |
| 01 | `rearm` | Timer stopped at entry; re-armed at the event | **Illegal** |
| 10 | `stop` | Timer stopped at exit | Legal: typical end of a frame |
| 11 | `idle` | Timer stopped at entry | **Illegal** |

### 3.1 Jump conditions (4 bits)

| Code | Name | Meaning |
|---|---|---|
| 0 | AL | Always |
| 1 | Z | Zero |
| 2 | NZ | Not zero |
| 3 | C | Carry / last bit set |
| 4 | NC | Carry / last bit clear |
| 5 | `r1--` | Decrement r1; jump if it was non-zero (loop) |
| 6–9 | E0–E3 | Event n was recorded by the last WAIT |
| 10 | TK | The tick ended the last WAIT (timeout) |
| 11 | LAST | Last PULL carried the host LAST flag |
| 12 | CMD | Last PULL was a command byte |
| 13 | HE | Host FIFO empty (non-blocking check) |
| 14 | ERR | Any sticky error |
| 15 | ARB | A driven bit read back differently during the last XFER (I2C/CAN arbitration) |

### 3.2 Special registers (4 bits)

| Code | Name | Access | Meaning |
|---|---|---|---|
| 0 | RX | R | Low byte of the last completed engine result; blocks until one is available; sets C := bit 8 |
| 1 | RXH | R | High bits of the same result (n > 8) |
| 2 | TIME_L | R | Cycles since last re-arm, low byte (reading latches TIME_H) |
| 3 | TIME_H | R | High byte of the latched value |
| 4 | EVF | R | Events recorded by the last WAIT |
| 5 | ERR | R/W | Sticky errors (MISS, UNDER, OVERRUN, ARB); write 1 to clear |
| 6–8 | PER_L/M/H | W | Tick period, 20.4 fixed point |
| 9–10 | PHASE_L/H | W | Offset of tick 0 after a re-arm |
| 11 | ECFG | R/W | Engine config: bit order, line code; §4 clock fields (proposal) |
| 12 | PC | R/W | Write = computed jump (host command dispatch) |
| 13 | ID | R | Version, instruction-memory size, context count |
| 14–15 | — | — | Reserved |

### 3.3 Encoding

Every instruction fits in 16 bits with spare bits left. Unchanged from v0.1.

```
SET   0000 T E mmmm vvvv --
IN    0001 T - ll ----------
WAIT  0010 tt eeeee ------
JMP   0011 cccc aaaaaa --
LDI   0100 dd -- iiiiiiii
ALU   0101 fff dd ss -----
XFER  0110 ss nnnn mm ----
PULL  0111 dd b ---------
PUSH  1000 ss gg --------
MFS   1001 dd rrrr ------
MTS   1010 ss rrrr ------
1011–1111  reserved: CRC/LFSR, capture, ALU-immediate
```

### 3.4 Timeline tags → instructions

| Tag | Instruction |
|---|---|
| pin | `SET` |
| read | `IN`, `XFER in` |
| wait | `WAIT` |
| time | `.T` forms, `PER`/`PHASE`, `TIME` |
| host | `PULL`, `PUSH` |
| shift | `XFER` |
| count | `XFER n`, `r1--` |
| jump / branch | `JMP`, `MTS PC` |

### 3.5 Dropped from PIO, and why

- **Per-instruction delay and side-set:** time comes only from ticks.
- **Clock divider:** instructions always run at full rate.
- **Autopull and `OUT EXEC`:** replaced by explicit byte jobs, plus CMD flags with
  computed jumps.
- **32-bit registers:** replaced by 8-bit ones.

---

## 4. Engine clock generation — *proposal, awaiting approval*

**Why:** a controller has to *produce* the clock, and v0.1 had no way to do it.
The engine drove only one data pin, so the SPI and I2C controller programs never
toggled a clock.

**Proposed static/ECFG fields:** `CLK_EN`, `CLK_LP` (logical pin), `CPOL`, `CPHA`,
plus the engine pins `DOUT_LP`, `DIN_LP`.

**Behaviour:** with `CLK_EN` set, **each XFER bit takes two ticks**, a leading
and a trailing one. `PER` is therefore half a bit period (bit rate = f_clk / (2 · PER)).

| | Leading tick | Trailing tick |
|---|---|---|
| CPHA = 0 | Clock to active level; **sample** DIN | Clock to idle; **drive** the next DOUT bit |
| CPHA = 1 | Clock to active level; **drive** DOUT | Clock to idle; **sample** DIN |

- With CPHA = 0 the first bit is driven when the job starts, at least half a
  period before the first leading tick.
- **Controller:** the tick source is the timer, and the engine drives `CLK_LP`.
- **Target:** the tick source is the clock pin; both of its edges are ticks, and
  the engine doesn't drive the clock. So the engine does the same thing in both
  roles.
- **I2C controller** (open-drain clock): after releasing SCL, the engine waits
  until SCL reads back high (3-cycle latency) before starting the next
  half-period, and re-arms the timer from that observed edge. That is
  controller-side clock-stretch support. **Deferrable:** a controller without it
  still works with targets that never stretch.
- **START/STOP** are `SET.T` sequences on the timer, never untimed `SET`.

**Open for approval:** field placement (ECFG vs static setup) and the exact
first-bit timing for CPHA = 0.

---

## 5. Hand-assembled examples

### 5.1 UART TX (8N1) — 9 instructions

Setup: LP0 = TX (push-pull, idle 1). Engine: DOUT = LP0, LSB first, clock off.
Tick = timer, `PER` = f_clk / baud (e.g. 434.0 for 115200 at 50 MHz).
EV0 = host data available.

```
idle:  WAIT   ev0              ; timer stopped: waiting is normal
       PULL   r0
frame: SET.T  tx=0             ; starts the timer: tick k = start bit
       XFER   r0, 8, out       ; ticks k+1..k+8 = data bits
       SET.T  tx=1             ; tick k+9 = stop bit (queued behind the XFER)
       JMP    HE, done
       PULL   r0               ; next byte, fetched during the stop bit
       JMP    frame            ; next start bit on tick k+10: back-to-back frames
done:  WAIT   tick, stop       ; consumes tick k+10 (end of stop bit): no MISS
       JMP    idle
```

### 5.2 UART RX (8N1) — 11 instructions

Setup: LP0 = RX (input, 3-sample filter). Engine: DIN = LP0, LSB first. EV0 = RX
falling edge; EV1 = RX high. `PHASE` = `PER`/2, so tick 0 falls in the middle of
the start bit. Received bits are right-aligned in arrival order (SR[7:0] = data,
SR[8] = stop).

```
start: WAIT   ev0, rearm       ; timer stopped while waiting, re-armed at the edge
       IN.T   rx               ; tick 0: is the line still low?
       JMP    C, start         ; no → a glitch, not a start bit
       XFER   9, in            ; ticks 1–9: 8 data bits + stop bit
       MFS    r0, RX           ; data byte; C := stop bit (always)
       JMP    NC, ferr
       PUSH   r0, DATA
       JMP    start
ferr:  PUSH   r0, ERR          ; framing error or break, tagged for the host
       WAIT   ev1, idle        ; wait for the line to go idle, with the timer stopped
       JMP    start
```

### 5.3 SPI target (mode 0) — 11 instructions

Setup: tick source = SCLK (both edges, §4); CPOL = 0, CPHA = 0. DOUT = LP0 (MISO,
push-pull, OE off at idle), DIN = LP1 (MOSI), MSB first. EV0 = CS falls. EV1 = CS
rises, configured as a trap to `desel`. Empty-FIFO policy: send default 0xFF.

```
idle:  WAIT    ev0
       SET.E   miso=on
       PULL.NB r0
       XFER    r0, 8, both     ; bit 7 driven immediately (CPHA 0)
loop:  PULL.NB r0              ; reply byte prepared one byte ahead
       XFER    r0, 8, both     ; queued: no gap at the byte boundary
       MFS     r1, RX          ; byte just received from the controller
       PUSH    r1, DATA
       JMP     loop
desel: SET.E   miso=off        ; trap on CS rise: queue cancelled
       PUSH    r1, EOF         ; tag carries the event; data ignored
       JMP     idle
```

- Software works per byte, not per bit: a 5-instruction loop against 80 cycles
  per byte at 5 MHz SCLK.
- Maximum SCLK is limited by the edge path: synchronise + detect + output, about
  4–6 cycles, so roughly 5–8 MHz at 50 MHz. To be measured in RTL.

### 5.4 I2C target — sketch (the shipped program in `sw/programs/i2c_target.asm` is ISS-tested)

Setup: tick source = SCL (both edges, §4). SDA = open-drain DOUT/DIN; ARB
available. EV0 = START (qualified edge), EV1 = STOP, both usable as traps.
Miss policy = stretch.

```
idle:  WAIT   ev0              ; START
       XFER   8, in            ; address byte
       MFS    r0, RX
       ALU    MOV r3, r0       ; keep R/W (bit 0) BEFORE masking
       LDI    r1, 0xFE
       ALU    AND r0, r1
       LDI    r1, ADDR<<1
       ALU    CMP r0, r1
       JMP    NZ, nack
       LDI    r2, 0x00         ; ACK = drive 0 (always initialised)
       XFER   r2, 1, out
       LDI    r1, 0x01
       ALU    AND r3, r1
       JMP    NZ, do_read
       ; write: receive bytes, ACK each, push to host ...
do_read:
       PULL.NB r0              ; stretch policy holds SCL low if the host is late
       XFER   r0, 8, out
       ; read controller's ACK/NACK, repeat or wait for STOP ...
nack:  ...
```

- Bugs to avoid (fixed in the shipped program): R/W was
  masked away before it was tested, and the ACK register was uninitialised.
- An ALU-immediate form (a reserved opcode) would save about 3 instructions.

### 5.5 WS2812 (generality check)

Three ticks per bit at `PER` ≈ 0.4 µs (20 cycles at 50 MHz): 0 = `H L L`,
1 = `H H L`. Time comes from ticks, not from padding instructions. With instruction padding, `MOV` padding made 0 and 1 look identical, which is exactly the PIO
pattern ticks make ineffective.

---

## 6. Against the weakness tracker

| # | PIO weakness | Mechanism here |
|---|---|---|
| 1 | Divider welds bit timing and reaction speed together | Ticks come from `PER`, while instructions run at full rate. Jitter is still ±1 cycle for fractional periods |
| 2 | Timing by counting instructions and padding paths | Timed operations land on their tick, whatever path the program took |
| 3 | The program cannot read the time | `MFS TIME`. An autobaud demo writes `PER` from a measured start bit |
| 4 | Nothing protocol-aware | The bit engine handles bits (and clocks, §4); line coding in `ECFG` and CRC in a reserved opcode are deferred |
| 5 | Complex protocols consume state machines and slots | UART TX 9, UART RX 11, SPI target 11 of 64 slots, with error reporting and streaming |
| 6 | Pin windows only | Each logical pin maps independently to any physical pin; engine pins selectable |
| 7 | Silent underflow stall | Running timer = strict region; `MISS` plus a per-context policy |
| 8 | One condition, no timeout | 5-bit event mask with TICK as the timeout; EVF says which event ended the wait |
| 9 | Only one branchable pin | `IN` + `JMP C` works for any pin |
| 10 | Read-back latency undefined | Defined as 3 cycles |
| 11 | No data path between state machines | **Still open** |
| 12 | Error recovery needs the CPU | Traps, plus error-tagged words pushed to the host |

---

## 7. Properties

| Property | Status (30 Sep, as reported; to be independently re-run) |
|---|---|
| Queue invariant: pending full ⇒ active full | **Proved** in SymbiYosys (k-induction); fails before the queue-ordering fix (commit `69c7e27^`), as it should |
| The k-th timed operation executes on the k-th tick, with its pin change exactly L cycles later, for any instructions in between (**headline**) | ISS-tested (padding and branching sweeps); ISS and RTL agree on the padding sweep |
| While the timer runs, consecutive ticks are ⌊PER⌋ or ⌈PER⌉ apart; over N ticks the total is N·PER ± 1 | ISS-tested (integer PER); formal to do |
| `MISS` rises if and only if a tick passes with nothing active while the timer runs | ISS-tested; formal to do |
| Within a fixed number of cycles after a trap: PC = vector, queue empty, pins idle | ISS-tested; RTL has no traps yet |
| No physical pin ever has two drivers | To do |

---

## 8. Area

| Item | Cells |
|---|---|
| Measured: current RTL (one context, subset of the ISA, flip-flop instruction memory), generic Yosys cells | 6,466 |
| v0.1 estimate for the full design (2 contexts, host link) | ~10–13k |
| Budget on 6x4 | ~25k |

Generic Yosys cells are not IHP cells; re-measure after mapping to the IHP
library and after the second context is added.

---

## 9. Open questions

1. **Engine-clock approval:** field placement, CPHA = 0 first-bit timing; whether the I2C
   SCL-release wait makes it in.
2. **Barrel vs two independent issue paths.** The ISA is the same either way;
   decide with synthesis numbers. The RTL has one context so far.
3. **Replies that depend on the command just received** (SPI register reads,
   answer due within half an SCLK period). I2C solves it by stretching; SPI needs
   dummy cycles or a hardware lookup assist.
4. **`IN.T` in the RTL:** its own queue kind, or a 1-bit `XFER in` internally?
   (The RTL queue kinds are currently empty / SET / XFER / WAIT.)
5. **Result latch:** one latch plus an overrun flag has been enough so far. Check
   against I2C and JTAG.
6. **Pins per context:** four logical pins covers SPI, I2C, JTAG and USB. Check
   against the PS/2 and WS2812 timelines.
7. **Capture/monitor mode:** a plain program works; a hardware capture job would
   do better at fast edge rates.
8. **Inter-context data path** (weakness #11 is still open).
9. **Clock choice:** at 50 MHz a 10BASE-T half-bit is 2.5 cycles. Confirm the
   harness clock before designing a Manchester mode.
10. **`TIME` width:** 16 bits covers 1.3 ms at 50 MHz, too short to autobaud
    below ~800 baud. Widen it, or add a prescaler.
