# Tick ISA — living v0.1 (review 2026-09-30)

*Un-frozen for the review-brief fixes. Encoding and cycle order still live in
`model/opcodes.py` / `model/machine.py`; this document tracks the architectural
rules that landed with W1–W12.*

## Machine

- Two contexts, time-multiplexed: one instruction issued per cycle; a stalled
  context is skipped. A context issues only when **`enabled`** (host static load).
- 64 × 16-bit instruction memory, shared, base/bound per context.
- Per context: PC (6-bit relative), r0–r3 (8-bit), flags Z/C/EVF/LAST/CMD,
  sticky errors MISS/UNDER/OVERRUN/ARB, timer (`PER` 20.4, `PHASE`, `TIME`),
  bit engine (16-bit SR, active + pending job, result latch), four logical pins,
  four event selectors.
- Engine pin map (static): **DOUT / DIN / CLK** logical pins (`dout_lp`, `din_lp`,
  `clk_lp`).
- Host FIFOs: 10-bit words (8 data + LAST + CMD). Host SPI is a pin peripheral;
  the model speaks only to FIFOs (see [pin-plan.md](pin-plan.md)).
- Tick source: timer or external pin edge. Timed ops (`SET.T`, `IN.T`, each
  `XFER` half-bit or bit, and `WAIT` with `tick`) consume ticks in program order.
- Miss policy (per context): flag | trap | send_default | stretch.
- Read-back latency: **3 cycles** (architecturally defined).
- Open-drain: 0 = drive low, 1 = release. Highest context wins on conflict;
  double-drive is a test error.

## Cycle order (`step()`)

1. Update 2-flop sync and event detectors.
2. Emit tick if timer/edge source fires.
3. Event-first: dequeue a timed `WAIT` on non-tick events.
4. Bit engine / timed queue on tick; else if timer running and empty → MISS + policy.
5. Soft waits / PULL / MFS.
6. Issue scheduled context if not stalled.
7. Apply pin updates with 3-cycle read-back visibility.

## Encoding (16-bit)

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
1011–1111  reserved
```

`MFS RX` always sets `C := result[8]` (ready and blocking paths).

**XFER width (W9):** `out`/`both` n ∈ 1..8; `in` may be 1..16 (UART RX 9-bit).

**ECFG (W8):** bit0 MSB-first; bit1 `clk_en` (two ticks/bit + drive CLK); bit2 CPHA;
bit3 CPOL. With `clk_en`, half-bit = one `PER` (one jitter source). CPHA=1: leading
tick drives clock active and updates data; trailing samples and returns clock idle.

Opcodes, jump conditions, special registers, and WAIT `tc` field match the draft
§3. Single source of truth in software: `model/opcodes.py`.

Timed operations that consume ticks in program order: `SET.T`, `IN.T`, each
`XFER` tick (or half-tick when `clk_en`), and a `WAIT` whose event mask includes
`tick` (queue kind = wait).

## Headlined properties

1. While the timer runs, consecutive ticks are ⌊PER⌋ or ⌈PER⌉ apart; over N ticks
   the total is N·PER ± 1.
2. The k-th timed operation executes on the k-th tick; pin change appears exactly
   L (=3) cycles later, independent of control-flow path length.
3. MISS ⟺ a tick passed with no waiting operation while the timer was running.
4. Within a fixed bound after a trap: PC = vector, engine idle, pins at idle.
5. No physical pin has two drivers in a correct program.
6. Queue invariant: pending occupied ⇒ active occupied.

## Defaults locked

- No fused SET on WAIT/JMP; no call/return; dispatch via `MTS PC`.
- TIME remains 16 bits.
- Line-code = raw until stretch phase.
- ADDI stays reserved unless I2C target assembly forces it.
