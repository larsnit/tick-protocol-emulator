# Host link: 4-pin SPI (draft v0.1)

*Draft for review, 17 October 2026. Once approved it becomes a section of
`docs/isa.md` in the repo, and Cursor implements it.*

## 1. Purpose

The host (a microcontroller, e.g. the RP2040 on the Tiny Tapeout demo board)
must be able to:

1. load programs into the instruction memory and read them back;
2. write and read every configuration register;
3. start and stop the chip;
4. send data to the running program and receive data from it **while it runs**;
5. see status (FIFO levels, errors) cheaply, without stopping the chip.

Today's parallel bus only does 1–2, and only while stopped. It also borrows the
`uio` pins, which belong to the protocols.

## 2. Pins

| Pin | Signal | Direction | Notes |
|---|---|---|---|
| `ui[0]` | SCLK | in | from host |
| `ui[1]` | MOSI | in | host → chip |
| `ui[2]` | CS_n | in | active low, frames one transaction |
| `ui[3..7]` | — | in | reserved, tie low (see open question 1) |
| `uo[0]` | MISO | out | chip → host; always driven (`uo` can't be tri-stated), so one host per chip |
| `uo[1]` | IRQ | out | high when an enabled interrupt condition is true (§6) |
| `uo[2]` | RUN | out | mirrors `CTRL.RUN` |
| `uo[3]` | ERR | out | any sticky core error (ERR register non-zero) |
| `uo[4]` | MISS | out | sticky MISS (context 0) |
| `uo[5]` | TICK | out | tick pulse (context 0), for scope debugging |
| `uo[6..7]` | — | out | reserved (0) |

All 8 `uio` pins are protocol pins only.

## 3. Electrical and timing

- **SPI mode 0** (CPOL = 0, CPHA = 0), MSB first, 8-bit bytes. The host samples
  MISO on the rising edge; the chip changes MISO after the falling edge.
- **One clock domain.** SCLK, MOSI and CS_n are oversampled by the core clock
  through 2-flop synchronisers and edge detectors. There is no second clock
  domain, so there are no clock-domain-crossing bugs to verify (cf. RP2040
  erratum E16).
- **Maximum SCLK = f_clk / 8** (6.25 MHz at 50 MHz). Recommended: f_clk / 10
  (5 MHz). Reason: the chip sees a falling edge ~3 cycles late (synchroniser +
  detect) and needs ~1 more cycle to drive MISO, all within half an SCLK period.
- **CS timing (in core clock cycles):**

  | Parameter | Min |
  |---|---|
  | CS_n falling → first SCLK rising | 4 cycles |
  | Last SCLK falling → CS_n rising | 4 cycles |
  | CS_n high between transactions | 4 cycles |

- **Throughput at 5 MHz SCLK:** ≈ 600 kB/s for pushes, ≈ 300 k entries/s for
  pulls (2 bytes per entry). That's enough to stream UART at several Mbaud.

## 4. Transaction format

```
CS_n  ‾‾\______________________________________________/‾‾
MOSI      [ CMD ][ ARG ][ ... payload / dummy ... ]
MISO      [STATUS][  0  ][ ... read data ...      ]
```

- **Byte 1, host → chip:** command. **Chip → host during that byte:** the
  STATUS byte (§5), snapshotted when CS_n falls. Every transaction returns
  status for free.
- **Reads always have one dummy byte** between the last command/address byte and
  the first data byte. That gives the chip a full byte time to fetch the data,
  instead of half an SCLK period.
- **Auto-increment:** writes and reads continue at the next address for as long
  as the host keeps clocking.
- **CS_n rising ends the transaction.** A partially shifted byte is discarded.
  Multi-byte units (an instruction word, a push with LAST) are committed only
  when complete (§7).

### 4.1 Commands

| Code | Name | Host sends after the command | Host receives | Notes |
|---|---|---|---|---|
| `0x00` | NOP | — | — | Status poll: just the STATUS byte |
| `0x01` | CFG_WRITE | ADDR, D0, D1, … | — | Auto-increment. Same rules as today: writes to an enabled context are rejected and set `ERR.CFG` |
| `0x02` | CFG_READ | ADDR, dummy, then clocks | D0, D1, … | Auto-increment |
| `0x03` | IMEM_WRITE | WADDR (0–63), HI0, LO0, HI1, LO1, … | — | Word committed after its LO byte. Rejected while the owning context is enabled (§7) |
| `0x04` | IMEM_READ | WADDR, dummy, then clocks | HI0, LO0, HI1, LO1, … | Lets the host verify a loaded program |
| `0x10`–`0x13` | PUSH | data bytes | — | Host → program FIFO. Bit 1 of the command = CMD flag on all bytes; bit 0 = mark the **final** byte with LAST |
| `0x20` | PULL | dummy, then clocks | pairs: TAGBYTE, DATA, … | Program → host FIFO (§4.2) |
| others | — | — | — | Ignored until CS_n rises; sets `LINKERR.BADCMD` |

### 4.2 PUSH and PULL details

- **PUSH with LAST:** the chip holds each received byte for one byte time
  before pushing it. When the next byte arrives, the held byte is pushed without
  LAST. When CS_n rises, the held byte is pushed with LAST (if bit 0 of the
  command was set). So the final byte carries LAST without the host having to
  announce the length in advance.
- **PUSH into a full FIFO:** the byte is dropped and `LINKERR.OVERFLOW` is set.
  To avoid that, the host checks `TX_FREE` (§5) or the STATUS byte before
  pushing.
- **PULL entry format:** each FIFO entry comes back as two bytes:
  - `TAGBYTE = {VALID, 0, 0, 0, 0, 0, TAG[1:0]}`, where TAG is one of DATA, EOF,
    ERR, EVT, as pushed by the program;
  - `DATA` = the 8-bit value.
  - If the FIFO is empty, VALID = 0 and DATA = 0, and nothing is consumed. The
    host stops at the first invalid entry, or reads `RX_COUNT` first.
  - An entry is consumed only after both of its bytes have been shifted out, so
    a CS_n abort in between loses nothing.

## 5. Status and shared registers

**STATUS byte** (returned during every command byte):

| Bit | Meaning |
|---|---|
| 7 | RUN |
| 6 | IRQ (same as the pin) |
| 5 | RX_AVAIL: program → host FIFO not empty |
| 4 | TX_FULL: host → program FIFO full |
| 3 | ERR: any sticky core error |
| 2 | LINKERR: any link error bit set |
| 1 | always 0 |
| 0 | always 1 |

Bits 1 and 0 are fixed, so a host can tell a live chip from a floating or stuck
MISO line.

**Shared configuration registers** (below `0x10`; context registers unchanged):

| Addr | Name | Access | Bits |
|---|---|---|---|
| `0x00` | ENABLE | R/W | context enables (unchanged) |
| `0x01` | CTRL | R/W | bit 0 RUN (replaces the `ui[3]` pin); bit 1 SOFT_RESET (self-clearing: clears queues, FIFOs, PC, flags, pending events; keeps program memory and configuration); bit 2 IRQ_EN_RX (IRQ when RX_AVAIL); bit 3 IRQ_EN_ERR (IRQ when ERR or LINKERR) |
| `0x02` | TX_FREE | R | free entries in the host → program FIFO (0–8) |
| `0x03` | RX_COUNT | R | entries waiting in the program → host FIFO (0–8) |
| `0x04` | LINKERR | R/W1C | bit 0 BADCMD, bit 1 OVERFLOW, bit 2 IMEM_REJECTED, bit 3 ABORTED (CS_n rose inside a multi-byte unit) |
| `0x05` | ID | R | version / build ID |

*To check:* that `0x01`–`0x05` are still free in the current map.

## 6. Interrupt pin

`IRQ = (IRQ_EN_RX & RX_AVAIL) | (IRQ_EN_ERR & (ERR | LINKERR))`. It's a level
signal: it stays high while the condition holds and clears when the host drains
the FIFO or clears the errors. The host can sleep until IRQ instead of polling.

## 7. Access rules and error handling

| Situation | Behaviour |
|---|---|
| CFG_WRITE to an enabled context | rejected, `ERR.CFG` set (existing rule) |
| IMEM_WRITE while the context that owns the address is enabled | rejected, `LINKERR.IMEM_REJECTED` set. (Single context today: rejected while context 0 is enabled.) |
| PUSH / PULL / status / shared registers | allowed at any time, running or not |
| CS_n rises mid-byte | partial byte discarded |
| CS_n rises inside a multi-byte unit (half an instruction word, a PULL pair) | unit discarded / entry not consumed; `LINKERR.ABORTED` set |
| Unknown command | rest of the transaction ignored; `LINKERR.BADCMD` set |
| Reset (`rst_n`) | link active immediately; RUN = 0; contexts disabled; pins inputs |

## 8. Implementation sketch

- **New module `host_spi.sv`:** synchronisers + edge detect for SCLK/MOSI/CS_n,
  bit counter, RX/TX shift registers, command state machine (IDLE → CMD → ARG →
  [DUMMY] → DATA).
- It drives the ports that already exist: config write/read, program-memory
  write/read, host FIFO push/pop. The core doesn't change, apart from RUN moving
  from a pin into `CTRL` and the new shared registers.
- **New:** an instruction-memory read port for IMEM_READ (one more read path
  into `tick_imem`).
- **Estimated size:** 300–500 cells.

## 9. Verification plan

- **Python host driver** (`sw/tick/host_link.py`): encodes and decodes every
  command. It's used by all cocotb tests (replacing today's parallel-bus
  helpers), and later by real host scripts.
- **Transaction-level reference model** of the link: expected config, program
  memory, FIFO contents and error bits after any command stream.
- **Random tests:** random command streams, including CS_n aborts at random bit
  positions, overflow and reads of an empty FIFO; compared against the reference
  model.
- **SCLK at f_clk / 8 with random phase** relative to the core clock, to
  exercise the synchronisers.
- **Formal properties:** an aborted IMEM_WRITE never writes half a word; a
  dropped push always sets OVERFLOW; PULL consumes an entry only after both
  bytes.
- **Gate level:** the gate-level tests load programs through the SPI link.

## 10. Decisions (Lars, 17 Oct 2026)

1. **The parallel bus is removed.** The SPI link is the only host interface, so
   its verification (§9) has to be thorough.
2. **RUN is a register only** (`CTRL.RUN`); no RUN pin.
3. **`ui[3..7]` stay reserved** (tie low).
4. **PULL keeps two bytes per entry,** so every byte carries its tag.
