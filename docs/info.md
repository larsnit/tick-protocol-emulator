## How it works

**Tick** is a programmable protocol-emulator ASIC for the Jane Street competition.
Each context has a tick stream (timer with fractional `PER`/`PHASE`, or an external
edge). Timed operations (`SET.T`, `IN.T`, each `XFER` bit, tick-`WAIT`) consume
ticks in program order, so pin edges stay on the grid while instructions run at
full clock.

While the timer runs, an empty timed queue raises `MISS` and applies a per-context
policy (flag, trap, send default, or stretch). A stopped timer may idle on an empty
host FIFO without corrupting a frame.

The ISA is [isa.md](isa.md) (draft). The golden model is the installable `tick`
package (`sw/tick/`). `tick_core` implements a single-context subset used for UART
TX bring-up on Tiny Tapeout.

## How to test

From the repo root (after `pip install -e .`):

1. ISS: `make test-model` (pytest suite)
2. RTL: `make test-rtl` (cocotb suite; needs iverilog)
3. Formal: `make formal` (SymbiYosys)
4. ISS fuzzer: included in `make test-model`

Host link: SPI mode 0 on `ui[0]=SCLK`, `ui[1]=MOSI`, `ui[2]=CS_n`; `uo[0]=MISO`,
`uo[1]=IRQ`, `uo[2]=RUN`. All eight `uio` pins are protocol-only. Load programs
and config through SPI (`CTRL.RUN` starts execution). See [isa.md](isa.md) Host link.

## External hardware

Host MCU (e.g. RP2040 on the Tiny Tapeout demo board) as SPI controller, and a
UART/SPI/I2C peer on the `uio` pins.
