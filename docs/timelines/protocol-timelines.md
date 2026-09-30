# Protocol timelines (ISA method step 1, reconstructed)

*Reconstructed 29 September 2026 from PROJECT.md demands and isa-v0.1-draft
hand-assembled examples. The original six timelines were cited as done but were
not in the repo.*

Conventions: `wait T` is from the previous timing point; `wait until …` restarts
the timing reference when it ends; pull/release is open-drain.

## UART TX (8N1)

```
host: wait until host data available          [wait host]
host: pull byte                               [host]
time: re-arm / start bit low at next tick     [time pin]
shift: 8 data bits LSB first, one per tick    [shift]
pin: stop bit high at next tick               [time pin]
host: if more data, pull during stop; else wait end of stop and idle
```

**ISA coverage:** WAIT (host), PULL, SET.T, XFER out, JMP HE, WAIT tick/stop.

## UART RX (8N1)

```
wait until RX falling edge, rearm timer       [wait time]
sample mid-start (PHASE=PER/2)                [read time]
if high → glitch, restart                     [branch]
shift in 8 data + stop                        [shift]
push data or framing-error tag                [host]
on error: wait until line idle (timer stopped)
```

**ISA coverage:** WAIT rearm, IN.T, JMP C, XFER in, MFS RX, PUSH, WAIT idle.

## SPI controller (mode 0)

```
assert CS                                     [pin]
for each byte:
  pull host byte (or default)                 [host]
  for 8 bits MSB first:
    drive MOSI, drive SCLK low then high      [pin time]
    sample MISO on rising edge                [read]
  push received byte                          [host]
deassert CS
```

With tick = timer and XFER both: one bit per tick; SET for CS. Engine samples on
rising / drives on falling via setup (CPHA 0).

**ISA coverage:** SET, PULL, XFER both, MFS RX, PUSH. Miss policy = stretch (pause SCK) or trap.

## SPI target (mode 0)

```
wait until CS falls                           [wait]
enable MISO OE                                [pin]
pull.NB reply (default 0xFF if empty)         [host]
XFER both 8; queue next byte ahead            [shift host]
on CS rise (trap): OE off, push EOF           [wait trap pin host]
```

**ISA coverage:** WAIT, SET.E, PULL.NB, XFER, MFS RX, PUSH, trap vector. Tick = SCLK.

## I2C controller

```
START: SDA fall while SCL high                [pin]  (breaks bit timing)
for each bit: open-drain drive/release on SDA; pulse SCL; sample SDA [pin read time]
ACK bit; on NAK branch                        [branch]
STOP: SDA rise while SCL high                 [pin]
stretch: WAIT SCL high with timeout           [wait]
```

**ISA coverage:** SET open-drain, WAIT, XFER both (ARB), JMP, SET for START/STOP outside tick stream (timer stop/idle around them).

## I2C target

```
trap on START (qualified edge)                [wait trap]
XFER 8 in (address+R/W); compare address      [shift branch]
ACK with 1-bit XFER 0                         [shift]
on read: stretch policy until host supplies byte
trap on STOP → idle
```

**ISA coverage:** traps, XFER, stretch miss policy, open-drain, ARB. ~25 instructions estimated.

## Diff vs ISA v0.1 draft

| Timeline need | Draft support | Gap |
|---|---|---|
| Fractional bit period | PER 20.4 + ticks | none |
| Mid-bit sample after edge | WAIT rearm + PHASE | none |
| Host flags / empty default | PULL.NB + policy | none |
| Multi-condition wait + timeout | WAIT evmask + TICK | none |
| Open-drain + read-back | pin mode + ARB | none |
| START/STOP any moment | qualified-edge traps | none |
| Address compare with 4 regs | ALU + LDI | ADDI reserved if squeezed |
| SPI reply within half SCLK | queue + stretch / dummy | hardware lookup still open (draft §8.2) |
| Inter-context data path | none | still open; IRQ-style event only |

No encoding change required for the six baselines. Reserve ADDI; add only if I2C target assembly exceeds ~25 instructions.
