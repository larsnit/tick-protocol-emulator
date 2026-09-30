# Tick ISA — frozen v0.1

*Frozen from [isa-v0.1-draft.md](../isa-v0.1-draft.md) after timeline reconciliation
([docs/timelines/protocol-timelines.md](timelines/protocol-timelines.md)).
Encoding, stall rules, and the cycle order below stop changing without a new
version bump.*

## Machine

- Two contexts, time-multiplexed: one instruction issued per cycle; a stalled
  context is skipped.
- 64 × 16-bit instruction memory, shared, base/bound per context.
- Per context: PC (6-bit relative), r0–r3 (8-bit), flags Z/C/EVF/LAST/CMD,
  sticky errors MISS/UNDER/OVERRUN/ARB, timer (`PER` 20.4, `PHASE`, `TIME`),
  bit engine (16-bit SR, active + pending job, result latch), four logical pins,
  four event selectors.
- Host FIFOs: 10-bit words (8 data + LAST + CMD). Host SPI is a pin peripheral;
  the model speaks only to FIFOs.
- Tick source: timer or external pin edge. Timed ops (`SET.T`, `IN.T`, each
  `XFER` bit) consume ticks in program order.
- Miss policy (per context): flag | trap | send_default | stretch.
- Read-back latency: **3 cycles** (architecturally defined).
- Open-drain: 0 = drive low, 1 = release. Highest context wins on conflict;
  double-drive is a test error.

## Cycle order (`step()`)

1. Update 2-flop sync and event detectors.
2. Emit tick if timer/edge source fires.
3. Bit engine: one bit of active job on tick; else if timer running and empty → MISS + policy.
4. Issue scheduled context if not stalled (WAIT, blocking PULL, MFS RX, full job queue).
5. Apply pin updates with 3-cycle read-back visibility.

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

`MFS RX` always sets `C := result[8]` (both the ready path and the blocking
resume path), so UART RX stop/parity bits are visible without a second read.

Opcodes, jump conditions, special registers, and WAIT `tc` field match the draft
§3. Single source of truth in software: `model/opcodes.py`.

Timed operations that consume ticks in program order: `SET.T`, `IN.T`, each
`XFER` bit, and a `WAIT` whose event mask includes `tick` (queue kind = wait).

## Headlined properties

1. While the timer runs, consecutive ticks are ⌊PER⌋ or ⌈PER⌉ apart; over N ticks
   the total is N·PER ± 1.
2. The k-th timed operation executes on the k-th tick; pin change appears exactly
   L (=3) cycles later, independent of control-flow path length.
3. MISS ⟺ a tick passed with no waiting operation while the timer was running.
4. Within a fixed bound after a trap: PC = vector, engine idle, pins at idle.
5. No physical pin has two drivers in a correct program.

## Defaults locked

- No fused SET on WAIT/JMP; no call/return; dispatch via `MTS PC`.
- TIME remains 16 bits.
- ECFG line-code = raw until stretch phase.
- ADDI stays reserved unless I2C target assembly forces it.
