<!---

This file is used to generate your project datasheet. Please fill in the information below and delete any unused
sections.

You can also include images in this folder and reference them in the markdown. Each image must be less than
512 kb in size, and the combined size of all images must be less than 1 MB.
-->

## How it works

**Tick** is a programmable protocol-emulator ASIC for the Jane Street competition.
Each context has a tick stream (timer with fractional `PER`/`PHASE`, or an external
edge). Timed operations (`SET.T`, `IN.T`, each `XFER` bit) consume ticks in program
order, so pin edges stay on the grid while instructions run at full clock.

While the timer runs, an empty timed queue raises `MISS` and applies a per-context
policy (flag, trap, send default, or stretch). A stopped timer may idle on an empty
host FIFO without corrupting a frame.

The frozen ISA is in [isa.md](isa.md). A cycle-accurate Python ISS in `model/` is the
golden model; `tick_core` implements a single-context subset used for UART TX bring-up.

## How to test

1. ISS: `python -m pytest model/ -q`
2. RTL: `cd test && PATH=../.venv/bin:$PATH make -B`
3. Fuzzer: `python scripts/fuzz_iss.py`
4. Formal: `sby -f formal/tick.sby`

Load path when `RUN=0`: command nibbles on `ui[7:4]` with data on `uio[7:0]`
(`0xA` addr, `0xB`/`0xC` imem lo/hi, `0xD`/`0xE` host word, pulse `IMEM_WE` /
`HOST_WR`). Set `RUN=1` to execute. Protocol pin is `uio[0]`.

## External hardware

Host MCU or FPGA driving the parallel load bus (SPI-target shim planned on
`ui`/`uo`) and a UART/SPI/I2C peer on the `uio` pins.
