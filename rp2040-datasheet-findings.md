# RP2040 Datasheet — Findings for the Protocol Emulator ASIC

*Reading notes against PROJECT.md. Written 29 September 2026. Section numbers refer to the RP2040 datasheet (build 2025-02-20).*

**Summary:** Chapter 3 closes the two open checks: weaknesses #3 and #4 are both confirmed. The most useful material for this design lies outside PIO. The fixed I2C, SPI, UART, PWM and Timer blocks are reference answers to the problems the protocol timelines raise. Appendix B (errata) is ready-made evidence for the verification section.

---

## 1. Six things that change the plan

1. **The deadline register doesn't reduce jitter; it decouples jitter from execution.**
   - A fractional `PERIOD` of 2.5 still alternates between 2 and 3 cycles, exactly like PIO's 2.5 divider (3.5.5). The clock generator does the same (2.15.3.3).
   - What the deadline approach gains is that the core keeps running at full clock, so reaction speed is preserved while edges stay paced.
   - Frame weakness #1 this way in the submission; otherwise it reads as an overclaim.

2. **Compare deadlines with a wrap-safe test.**
   - The system timer's alarms fire only on an exact *equality* match with the low 32 bits of the counter (4.6.3). A deadline that is already in the past therefore waits a full wrap, about 72 minutes.
   - The SDK's busy-wait uses `now - start < delay` and caps delays at 31 bits to avoid a race (4.6.4.3).
   - `WAITD` needs the same approach: compare using a signed difference, and limit deadlines to half the counter range. This also gives a clean formal property.

3. **What to do when the FIFO runs empty must be chosen per protocol, not fixed globally.**
   - DW I2C stalls the bus by holding SCL low when its TX FIFO empties (4.3.7.1). This is legal, because I2C allows clock stretching.
   - PIO stalls the same way for UART, where it corrupts the frame (weakness #7).
   - For an SPI controller, pausing SCK is legal. For UART, USB and Ethernet, a mid-frame stall is fatal.
   - This justifies letting each program declare its underflow mode: stall, abort-and-flag, or send a default value. That declaration is also the natural home for missed-deadline semantics.

4. **The host link is itself an SPI target, and SPI targets are slow.**
   - PL022 in slave mode needs its own clock to be at least 12× the incoming SCLK (4.4.3.4). At 50 MHz that gives about 4 Mbit/s.
   - A more aggressive two-flop synchroniser design might reach about clk/4, roughly 12 Mbit/s.
   - Either way, the host cannot stream a 10 Mbit/s 10BASE-T frame in real time. Ethernet needs one of:
     - an on-chip frame buffer,
     - a wider host link (QSPI or parallel), or
     - a smaller demo (short, fixed frames).
   - Low-speed USB at 1.5 Mbit/s is fine.

5. **50 MHz is an awkward clock for 10BASE-T.**
   - A 50 ns half-bit is 2.5 clock cycles at 50 MHz.
   - PIO's Manchester example uses 12 cycles per bit, about 10.4 Mbps at 125 MHz (3.6.5). At 50 MHz the same program gives about 4.2 Mbps.
   - Even a hardware Manchester encoder needs either a clock that is a multiple of 20 MHz, or output on both clock edges.
   - Confirm the harness clock before committing to the 10BASE-T stretch goal.

6. **Several novelty candidates already exist in fixed form; the novelty is making them programmable.**
   - *Non-blocking read with a default:* PIO's `pull noblock` copies X into OSR when the FIFO is empty (3.4.7).
   - *Flags travelling with data:* DW I2C's `IC_DATA_CMD` carries CMD/STOP/RESTART bits in each TX entry (4.3.7.1). PL011's RX FIFO stores 4 error bits alongside each byte (4.2.3.2.3).
   - *START/STOP detectors and deliberate clock stretching to hide software latency:* DW I2C does both in hardware (4.3.10.1.2).
   - *What is genuinely absent:* none of the PIO examples in 3.6 plays the target role for SPI or I2C. The I2C program explicitly covers the initiator role only (3.6.7). This supports making target/impersonation modes the headline.

---

## 2. Closing the open checks

### #3 — The program cannot read the time: **confirmed**

- `MOV` sources are PINS, X, Y, NULL, STATUS, ISR and OSR (3.4.8). STATUS only compares a FIFO level with N. No counter is visible to the program.
- Measuring a pulse requires a `jmp x--` counting loop:
  - resolution is at least 2 cycles,
  - the count comes out inverted,
  - the state machine can do nothing else while it counts.
- RP2040's real answer lives outside PIO. The PWM block can count while pin B is high, or count its edges (4.5.2.5), and the CPU polls the result.

### #4 — Nothing protocol-aware: **confirmed, now with numbers**

- **Manchester:** TX and RX cost 12 state-machine cycles per bit (3.6.5).
- **Differential Manchester (BMC):**
  - costs 16 cycles per bit;
  - needs two copies of the entire TX and RX loops, one per line level, because the program counter is the only place to store the current line state (3.6.6);
  - BMC TX + RX together occupy 20 of the 32 instruction slots.
- **Neither program does bit stuffing or CRC.**
- **CRC on RP2040 lives in the DMA sniffer.** It computes fixed CRC-32 and CRC-16-CCITT over words passing through DMA (2.5.5.2). There is no CRC-5 and nothing at bit level.
- **Bit stuffing and NRZI exist only inside the fixed USB controller** (4.1.2.5).
- **Argument for the line-coding unit:** keeping encoding state in the PC doubles program size, and doing the encoding in instructions costs 12–16 cycles per bit.

---

## 3. Rest of Chapter 3 (read closely — this is the ISA being answered)

### Timing
- **Delays count from when a stall clears** (3.2.4). After a WAIT, PIO's timing reference therefore re-anchors automatically. This matches the brief's rule that a wait re-arms the timing reference.
- **Side-set fires on the first cycle even if the instruction stalls.** This is how `uart_tx` idles high while waiting for data (3.6.3).
- **The divider produces a clock enable, not a separate clock** (3.5.5).
  - `CTRL.CLKDIV_RESTART` re-phases several state machines together.
  - One clock plus enables is the right pattern for Tiny Tapeout, and it keeps formal verification simple.
- **Path balancing is explicit in the examples.** The PWM program has a dummy `nop` purely to keep two paths the same length (3.6.8). Further evidence for weakness #2.

### Pins and read-back
- **Pin windows:** four independent windows (OUT, SET, IN, side-set), plus a single absolute JMP pin (3.2.5, 3.4.2).
- **Only one pin per state machine can be branched on directly.** Branching on any other pin costs an IN or MOV into X, then `jmp !x`.
- **Read-back latency:** a state machine sees its own output 2 cycles later with synchronisers bypassed, or 4 cycles with them (3.5.6.1).
  - This latency governs I2C ACK, arbitration and clock-stretch detection.
  - Make it an architecturally defined constant in the ISA, and a property to prove.
- **Open-drain is not native.**
  - The I2C example drives `pindirs` and inverts output-enable in the GPIO mux to save an instruction.
  - It also requires SCL to be pin SDA + 1 for the wait mapping (3.6.7).
  - This is evidence for weakness #6, and for making open-drain first-class.
- **Pin conflicts are resolved per pin.** The highest-numbered state machine wins, and within one machine side-set beats OUT/SET (3.2.5). A two-state-machine design needs an equally explicit rule.

### Control flow and errors
- **WAIT takes one condition and has no timeout** (3.4.3).
  - The I2C program's `wait 1 pin, 1` for clock stretching hangs forever if SCL is stuck low.
  - "SCLK rises OR CS goes high" cannot be expressed without a second state machine.
- **Error recovery needs the CPU.** On an unexpected NAK, the I2C program executes `irq wait`. Software then drains the FIFO and forces a jump back (3.6.7).
- **Command dispatch works by executing instructions from the data stream** (`OUT EXEC`, 3.5.7).
  - START and STOP are inserted this way. The top 6 bits of a TX word say "the next n+1 words are instructions".
  - Each inserted instruction costs one FIFO word.
- **There is no data path between state machines,** only 8 IRQ flags for synchronisation (3.2.7). UART TX and RX are therefore two separate state machines (3.5.3).
- **Constants and arithmetic are very limited.**
  - `SET` loads only 0–31. Larger constants come via the FIFO, or via the "ISR as config register" trick (3.6.8).
  - Arithmetic is limited to decrement and compare. The addition example is a joke that takes about a minute (3.6.9).

### Storage and area
- **The instruction memory has 1 write port and 4 read ports** (3.2.7), so all four state machines can fetch in the same cycle.
  - A time-multiplexed core needs only one read port.
  - This is a concrete area argument for the "2 SMs, time-multiplexed" candidate.
- **Timing closure shaped the architecture.** Autopull can refill the OSR alongside the last OUT. It cannot fill an empty OSR and OUT from it in the same cycle, because the logic path would be too long (3.5.4.2). Expect the same kind of trade-off at 130 nm.
- **32-bit width costs effort wherever bytes appear.**
  - WS2812 pre-shifts its data by 8.
  - UART RX reads the FIFO at byte offset +3, or uses `in null, 24`.
  - SPI relies on the bus fabric replicating narrow writes across byte lanes (2.1.4, 3.6.1–3.6.4).
  - This supports the "32-bit is a trap" note.

### Registers (3.7) — skim
- **`FDEBUG.TXSTALL`** is a sticky "stalled on empty TX" flag, so weakness #7 is not invisible to the host. However, it fires equally for intended idle stalls. It cannot distinguish an underflow mid-frame from simply waiting for the next frame.
- **`DBG_CFGINFO`** reports instruction-memory size, state-machine count and FIFO depth. It is cheap and worth copying, so firmware loaded after fabrication can discover the machine.

---

## 4. Outside PIO — the fixed blocks as benchmarks

### 4.3 I2C (DW_apb_i2c) — read closely
This is the only complete I2C *target* in the document.
- **Deliberate clock stretching:** the target holds SCL low on a read request until software supplies data, and also whenever its RX FIFO is full (4.3.10.1.2–.3). This hides software latency.
- **Condition detection in hardware:** START_DET, STOP_DET and RESTART_DET interrupts. This is the background condition detector, in fixed form.
- **Spike suppression:** a counter requires the input to stay stable for N cycles (default 7), after a two-flop synchroniser (4.3.11).
- **Latency budget to beat:** the minimum SCL low and high times it generates are 9 and 13 clocks (4.3.14.1).
- **Reset hazard** (warning in 4.3.10.1.1):
  - Releasing reset while the bus is active can register a false START, because the synchroniser flops go from their reset value to the live value.
  - Reset synchronisers to the line's idle level, or ignore detectors for a few cycles after configuration.
  - This is another property to prove.
- **Error reporting:** `IC_TX_ABRT_SOURCE` records 17 distinct abort causes, plus how many TX entries were flushed (4.3.17). It is a model for first-class error semantics.
- **Bus clear:** up to 9 clocks to free a stuck SDA line (4.3.13).

### 4.4 SPI (PL022) — medium
- **Slave-mode clock requirement:** its clock must be at least 12× SCLKIN, because synchronisation takes two flops plus one cycle to detect the edge (4.4.3.4). At 133 MHz this gives about 11 Mbit/s.
- This is the SPI-target number to beat, and the host-link constraint from §1.4.
- **Chip-select behaviour:** in CPHA = 0 mode, the slave requires CS to go high between frames (4.4.3.10). The target design must decide between per-byte and per-transaction CS handling.

### 4.2 UART (PL011) — medium
- **Receive sampling:**
  - 16× oversampling;
  - the start bit is confirmed on the 8th tick;
  - each bit is sampled three times, with a majority vote (4.2.3.2.2).
  - This is a ready-made spec for the glitch filter.
- **Receive timeout** fires after 32 bit-periods of silence while data is waiting (4.2.6.4). This idle detection is useful for finding frame boundaries in monitor mode.

### 4.5 PWM — medium
- **Double-buffered updates:** compare and top values are latched at the period boundary (4.5.2.3). This is "timed pin write" in fixed form.
- **Phase advance/retard** inserts or deletes one enable pulse while running (4.5.2.8). It is precedent for nudging a deadline by ±1 cycle, for example to resynchronise UART RX.

### 4.6 Timer — short
- **Alarms need a wrap-safe compare:** see §1.2 (equality-match alarms; the SDK's wrap-safe compare with a 31-bit cap).
- **Wide counters over narrow buses:** reading a 64-bit counter through a 32-bit bus needs either latching or re-read logic (4.6.4.1). If the counter is wider than the registers, the same problem appears.

### 2.5 DMA — short
- **Why a 4-deep FIFO is enough on RP2040:** the credit-based DREQ scheme keeps exactly as many transfers in flight as the FIFO has room for (2.5.3.2).
- An off-chip host has no such mechanism. This is the quantitative reason this design's FIFO must differ.
- The sniffer CRC is covered in §2 (#4).

### 4.1.2 USB — skim
- **A hard-wired line-coding unit:** the fixed controller samples at 48 MHz (4× per full-speed bit), and does line-state detection, bit-unstuffing and CRC in hardware. It is a line-coding unit wired for one protocol.
- **Buffer ownership handoff** (4.1.2.7.1) is a good pattern for host-written buffers:
  1. Write the buffer fields first.
  2. Set the AVAILABLE bit last.
  3. Allow at least one cycle of the other clock in between.

### 4.10.9.1.1 SSI RX sample delay — short
- The sampling point can be delayed by a programmable number of cycles, to absorb round-trip IO delay when acting as controller.
- At Tiny Tapeout IO speeds, the SPI controller will likely need the same knob.

### Skip
- **Sections:** 2.1–2.4, 2.6–2.18, 2.20–2.22, 4.7–4.9, and Chapter 5.
- **Chapter 5 pad timings don't transfer:** the 40 nm figures in 5.5.3.6 do not apply to IHP 130 nm through the Tiny Tapeout mux.
- **2.19.2–2.19.4 (GPIO overrides, pads):** worth ten minutes only to see what won't be available. Tiny Tapeout pads are fixed, so Schmitt triggers and slew control have to become digital filtering.

---

## 5. Appendix B errata — verification evidence

A careful team shipped these bugs in silicon. Most are exactly what properties and constrained-random tests target:

- **E1 — counter bug:** the watchdog decrements twice per tick. A one-line counter property catches this.
- **Control-state corner cases:**
  - **E4:** the USB host toggles its buffer select even in single-buffered mode.
  - **E13:** DMA ABORT reports completion before in-flight transfers have finished.
  - **E8:** a race when restarting an XIP stream.
  - **E12:** the in-flight address correction assumes linear addressing.
- **E16 — clock-domain crossing:** synchronisers are missing on USB status signals, and the bug was only found in the lab at process/voltage/temperature extremes. This is a CDC-lint result. It is relevant if the host link runs on the host's clock.

One paragraph citing these is stronger than a general claim that verification matters.

---

## 6. Weakness tracker updates

| # | Observation | Status | Evidence |
|---|---|---|---|
| 1 | Timing via divider; bit timing and reaction speed welded together | Confirmed — reframe | Divider is a clock enable using first-order delta-sigma (3.5.5). A fractional deadline has the same ±1-cycle jitter; the gain is full-speed reaction |
| 2 | Timing = instruction counting; branches padded | Confirmed | Dummy `nop` for path length (3.6.8) |
| 3 | Program cannot read the time | Confirmed | No time source among MOV sources (3.4.8); pulse measurement delegated to PWM (4.5.2.5) |
| 4 | Nothing protocol-aware | Confirmed | 12–16 cycles/bit; BMC keeps line state in the PC, doubling the code (3.6.5–3.6.6); CRC in the DMA sniffer (2.5.5.2) |
| 5 | Complex protocols consume SMs and slots | Confirmed | UART needs 2 state machines (3.5.3); I2C controller uses 18 of 32 slots; BMC TX+RX uses 20 |
| 6 | Window pin mapping, not a crossbar | Confirmed | SCL must be pin SDA + 1 (3.6.7) |
| 7 | FIFO underflow stalls and stretches timing | Refined | `FDEBUG.TXSTALL` records it, but cannot tell idle waiting from mid-frame underflow (3.7) |
| 8 | WAIT: one condition, no timeout | New — confirmed | A stuck SCL hangs I2C (3.4.3, 3.6.7) |
| 9 | Only one branchable pin per SM | New — confirmed | 3.4.2 |
| 10 | Read-back latency of 2–4 cycles, implicit | New — confirmed | 3.5.6.1 |
| 11 | No data path between state machines | New — confirmed | IRQ sync only (3.2.7) |
| 12 | Error recovery needs CPU intervention | New — confirmed | 3.6.7 |

**Add to "Traps if copied":** the instruction memory is a 1-write / 4-read register file (3.2.7). Four fetch ports are expensive, and a time-multiplexed core needs one.
