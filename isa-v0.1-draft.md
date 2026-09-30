# Protocol Emulator ASIC — ISA v0.1 Draft

*Written 29 September 2026. Built from PROJECT.md and rp2040-datasheet-findings.md.*

**Scope note:** the six protocol timelines were not in context when this was drafted. The draft works from the brief's "Required capabilities" and "Demands by protocol" sections. Step 2 of the ISA method should still check it against the timelines line by line.

---

## 1. Core idea: every timed action waits for a tick

This is the brief's DEADLINE/PERIOD idea, restated so a program never has to name a deadline.

1. **Each context (≈ state machine) has one tick stream.** Its source is either:
   - the timer, which ticks every `PER` cycles (fractional period, phase set when the timer is re-armed), or
   - an edge on an external pin, such as SCLK.
2. **Timed operations take ticks strictly in program order.** Timed operations are `SET.T`, `IN.T`, each bit of an `XFER` job, and a `WAIT` that includes the tick. The k-th timed operation gets the k-th tick.
   - The hardware holds one operation waiting for its tick, plus one queued behind it.
   - If both places are full, the next post stalls the program, not the wire.
3. **A timed action happens on its tick cycle**, plus a fixed output delay, whatever instructions ran in between. This is the headline property.
4. **A stopped timer restarts in one of two ways:**
   - at an event: `WAIT ev, rearm` sets tick 0 to event time + `PHASE`. The hardware does this at the event cycle, not when the instruction resumes;
   - at the first timed operation posted: tick 0 = post time + `PHASE`.
5. **A tick that passes with no operation waiting for it, while the timer runs, sets `MISS`.** A per-context policy decides what happens next:
   - *flag and continue*: stay on the tick grid;
   - *trap*: cancel the job, drive pins to their idle values, push an error to the host;
   - *send default*: for an SPI target;
   - *stretch*: hold SCL low until a job arrives; for an I2C target.

**Consequences:**
- While the timer is stopped, an empty host FIFO is just idle. While it runs, an empty FIFO is an error. That is exactly the distinction PIO's `FDEBUG.TXSTALL` cannot make.
- Nothing ever compares absolute times: each tick comes from a down-counter that reloads. The wrap-around comparison problem from the findings therefore disappears.
- Rule 1 means a controller and a target use the same instructions, just with a different tick source. This is a candidate story for the "most novel" criterion.

---

## 2. Machine state

### Per context (2 contexts)
- **Registers:** PC (6 bits, relative to the context's base address, so programs can be loaded anywhere); four 8-bit registers r0–r3.
- **Flags:** Z, C, EVF (which events ended the last WAIT), LAST and CMD (host flags from the last PULL).
- **Timer:** `PER` (20.4 fixed point), `PHASE`, and a 16-bit `TIME` counter of cycles since the last re-arm.
- **Bit engine:** 16-bit shift register; one executing job plus one pending job; a result latch with an overrun flag.
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
- 64 × 16-bit instruction memory, split between the contexts by base/bound registers.
- Host FIFOs of 10-bit words: 8 data bits + 2 flag bits.
- A free-running cycle counter.
- 2-flop synchronisers and optional 3-sample majority filters on all inputs.

### Static setup vs runtime state
Static setup (pin map, event selectors, tick source, error policies) is written by the host at load time. Only values that change while a program runs go through instructions.

---

## 3. Instruction set (11 of 16 opcodes)

| Op | Syntax | Effect |
|---|---|---|
| SET | `SET[.T][.E] mask, val` | Drive logical pins. `.E` sets output-enables instead. `.T` = at the next tick. Open-drain pins treat 0 as drive-low and 1 as release |
| IN | `IN[.T] lp` | C := pin value. `.T` samples at the next tick (blocks until then) |
| WAIT | `WAIT evmask[, tc]` | Block until any selected event (EV0–3, TICK); EVF records which. An empty mask means sleep until a trap |
| JMP | `JMP cond, addr` | Conditional jump (see §3.1) |
| LDI | `LDI rd, imm8` | Load immediate |
| ALU | `ALU fn rd, rs` | MOV, ADD, SUB, AND, OR, XOR, CMP, SHR; sets Z and C |
| XFER | `XFER [rs,] n, mode` | Post a bit-engine job of 1–16 bits: `out`, `in` or `both`. One bit per tick, entirely in hardware |
| PULL | `PULL[.NB] rd` | Read from the host FIFO; sets LAST/CMD. `.NB` applies the empty-FIFO policy instead of blocking |
| PUSH | `PUSH rs, tag` | Write to the host FIFO. Tags: DATA, EOF, ERR, EVT |
| MFS | `MFS rd, spr` | Read a special register (see §3.2) |
| MTS | `MTS spr, rs` | Write a special register (see §3.2) |

**WAIT timer-control field (`tc`):**

| Value | Name | Meaning |
|---|---|---|
| 00 | (none) | Timer untouched. If it is running, include TICK in the mask or it will MISS |
| 01 | `rearm` | Timer stopped at entry; re-armed at the event |
| 10 | `stop` | Timer stopped at exit |
| 11 | `idle` | Timer stopped at entry |

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
| 0 | RX | R | Low byte of the last completed engine result; blocks until one is available |
| 1 | RXH | R | High bits of the same result (n > 8) |
| 2 | TIME_L | R | Cycles since last re-arm, low byte (reading latches TIME_H) |
| 3 | TIME_H | R | High byte of the latched value |
| 4 | EVF | R | Events recorded by the last WAIT |
| 5 | ERR | R/W | Sticky errors (MISS, UNDER, OVERRUN, ARB); write 1 to clear |
| 6–8 | PER_L/M/H | W | Tick period, 20.4 fixed point |
| 9–10 | PHASE_L/H | W | Offset of tick 0 after a re-arm |
| 11 | ECFG | R/W | Engine config: bit order, line code |
| 12 | PC | R/W | Write = computed jump (host command dispatch) |
| 13 | ID | R | Version, instruction-memory size, context count |
| 14–15 | — | — | Reserved |

### 3.3 Encoding

Every instruction fits in 16 bits with spare bits left.

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
- **Autopull and `OUT EXEC`:** replaced by explicit byte jobs, plus CMD flags with computed jumps.
- **32-bit registers:** replaced by 8-bit ones.

---

## 4. Hand-assembled examples

### 4.1 UART TX (8N1) — 9 instructions

Setup: LP0 = TX (push-pull, idle 1). Engine: DOUT = LP0, LSB first. Tick = timer, `PER` = f_clk / baud (e.g. 434.0 for 115200 at 50 MHz). EV0 = host data available.

```
idle:  WAIT   ev0              ; timer stopped: waiting is normal
       PULL   r0
frame: SET.T  tx=0             ; starts the timer: tick k = start bit
       XFER   r0, 8, out       ; ticks k+1..k+8 = data bits
       SET.T  tx=1             ; tick k+9 = stop bit (queued behind the XFER)
       JMP    HE, done
       PULL   r0               ; next byte, fetched during the stop bit
       JMP    frame            ; next start bit on tick k+10: back-to-back frames
done:  WAIT   tick, stop       ; end of stop bit, then stop the timer
       JMP    idle
```

### 4.2 UART RX (8N1) — 11 instructions

Setup: LP0 = RX (input, 3-sample filter). Engine: DIN = LP0, LSB first. EV0 = RX falling edge; EV1 = RX high. `PHASE` = `PER`/2, so tick 0 falls in the middle of the start bit. Received bits are right-aligned in arrival order (SR[7:0] = data, SR[8] = stop).

```
start: WAIT   ev0, rearm       ; timer stopped while waiting, re-armed at the edge
       IN.T   rx               ; tick 0: is the line still low?
       JMP    C, start         ; no → a glitch, not a start bit
       XFER   9, in            ; ticks 1–9: 8 data bits + stop bit
       MFS    r0, RX           ; data byte; C = stop bit
       JMP    NC, ferr
       PUSH   r0, DATA
       JMP    start
ferr:  PUSH   r0, ERR          ; framing error or break, tagged for the host
       WAIT   ev1, idle        ; wait for the line to go idle, with the timer stopped
       JMP    start
```

### 4.3 SPI target (mode 0) — 11 instructions

Setup: tick source = SCLK. Engine drives MISO on falling edges, samples MOSI on rising edges; DOUT = LP0 (MISO, push-pull, OE off at idle), DIN = LP1 (MOSI), MSB first. EV0 = CS falls. EV1 = CS rises, configured as a trap to `desel`. Empty-FIFO policy: send default 0xFF.

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
desel: SET.E   miso=off        ; trap on CS rise: queued jobs cancelled
       PUSH    r1, EOF         ; tag carries the event; data ignored
       JMP     idle
```

- Software works per byte, not per bit: a 5-instruction loop against 80 cycles per byte at 5 MHz SCLK.
- Maximum SCLK is limited by the hardware edge path: synchronise + detect + output, about 4–6 cycles. That puts the ceiling around 5–8 MHz at 50 MHz. This is an estimate to confirm in RTL.

### 4.4 I2C target — sketch only

- **START and STOP** are qualified-edge events configured as traps. They can arrive at any moment without the program polling for them.
- **Tick source** = SCL: sample on rising, drive on falling. SDA is open-drain; the ARB flag is available.
- **Address phase:**
  - `XFER 8, in`, then mask off the R/W bit and compare with the target address.
  - About 5 instructions with only four registers.
  - An ALU-immediate form (one of the reserved opcodes) would save 2.
- **ACK:** a 1-bit `XFER` of 0.
- **Reads:** use the *stretch* policy. When the controller clocks a bit and no job is queued, the engine holds SCL low until the program posts the next byte.
  - This is DW I2C's deliberate stretching (datasheet 4.3.10.1.2), generalised into a policy.
  - The same policy means "pause SCK" in SPI controller mode.
- **Estimate:** about 25 instructions. With both UARTs (20 instructions), this still fits in 64 slots.

---

## 5. Against the weakness tracker

| # | PIO weakness | Mechanism here |
|---|---|---|
| 1 | Divider welds bit timing and reaction speed together | Ticks come from `PER`, while instructions run at full rate. Jitter is still ±1 cycle for fractional periods |
| 2 | Timing by counting instructions and padding paths | Timed operations land on their tick, whatever path the program took |
| 3 | The program cannot read the time | `MFS TIME`. An autobaud demo writes `PER` from a measured start bit |
| 4 | Nothing protocol-aware | The bit engine handles bits; line coding (NRZI, Manchester, bit stuffing) goes in `ECFG`; CRC takes a reserved opcode |
| 5 | Complex protocols consume state machines and slots | UART TX 9, UART RX 11, SPI target 11 of 64 slots. Not smaller than PIO per program, but with error reporting and streaming |
| 6 | Pin windows only | Each logical pin maps independently to any physical pin |
| 7 | Silent underflow stall | Running timer = strict region; `MISS` plus a per-context policy |
| 8 | One condition, no timeout | 5-bit event mask with TICK as the timeout; EVF says which event ended the wait |
| 9 | Only one branchable pin | `IN` + `JMP C` works for any pin |
| 10 | Read-back latency undefined | Define it as a constant (e.g. 3 cycles) and prove it |
| 11 | No data path between state machines | **Still open.** An event could come from the other context, but there is still no data path |
| 12 | Error recovery needs the CPU | Traps, plus error-tagged words pushed to the host |

---

## 6. Properties this makes provable

- While the timer runs, consecutive ticks are ⌊PER⌋ or ⌈PER⌉ apart. Over N ticks the total is N·PER ± 1.
- The k-th timed operation executes on the k-th tick. Its pin change appears exactly L cycles later, for any instructions in between. **This is the headline property.**
- `MISS` is set if and only if a tick passed with no operation waiting for it while the timer was running.
- Within a fixed number of cycles after a trap event: PC = the trap vector, the engine is idle, and every pin is at its idle value.
- No physical pin ever has two drivers.

---

## 7. Rough area

This is a guess; a synthesis run should replace it.

| Block | Estimate (cells) |
|---|---|
| Instruction memory (flip-flops; about half as a latch array) | ~3–4k |
| Two contexts | ~3–4k |
| Decode + ALU | ~0.7k |
| Host FIFOs + link | ~2k |
| **Total** | **~10–13k** |

That leaves room for the line-coding unit, CRC and capture within the ~25k estimate for 6x4.

---

## 8. Open questions

1. **Barrel vs two independent issue paths.**
   - A barrel core halves instruction rate to 25 MIPS per context. Because bits run in hardware, that barely matters.
   - The ISA is the same either way, so decide this with synthesis numbers.
2. **Replies that depend on the command just received.**
   - This is SPI register reads, where the answer must be ready within half an SCLK period.
   - I2C solves it by stretching. SPI would need a hardware lookup assist, or protocols with dummy cycles.
3. **Result latch.** One latch plus an overrun flag was enough for these examples. Check it against I2C and JTAG.
4. **Pins per context.** Four logical pins covers SPI, I2C, JTAG and USB. Check it against the PS/2 and WS2812 timelines.
5. **Capture/monitor mode.** It can be a plain program: `WAIT` any edge → `MFS TIME` → `PUSH`. At fast edge rates, a hardware capture job would do better.
6. **Fused operations.** Should `WAIT` or `JMP` carry a fused `SET` in their spare bits? Decide after step 7 shows whether it's needed.
7. **Clock choice.** At 50 MHz, a 10BASE-T Manchester half-bit is 2.5 cycles (see findings §1.5). Confirm the harness clock before designing the Manchester mode.
8. **TIME width.** 16 bits covers 1.3 ms at 50 MHz, which is too short to autobaud below ~800 baud. Decide between widening it or adding a prescaler.
