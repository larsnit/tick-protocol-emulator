# Pin plan (W12 short-term)

## Today (parallel bring-up)

| Pin | Role |
|---|---|
| `ui_in[3:0]` | `run`, `imem_we`, `host_rd`, `host_wr` |
| `ui_in[7:4]` | load mux (`0xA` addr … `0xE` host flags) |
| `uo_out[5:0]` | status / dbg / pin0 mirror |
| `uio[7:0]` | protocol (LP0 on `[0]`); host load data while `!run` |

While `!run`, `uio_oe = 0` so the host can drive the load bus without fighting the engine.

## Host SPI target (deferred)

Four pins on `ui`/`uo`: **SCLK, MOSI, CS_n, MISO**. All eight `uio` stay protocol-only.
1-bit SPI at ~clk/12 is enough to load programs and stream UART / SPI-target demos;
not for 10BASE-T. Keep the parallel load path until demos starve.

## MTS PER / PHASE

`tick_core` keeps writable `per_fp` / `phase_cfg` / `msb_cfg`, seeded from the
static `cfg_*` ports at reset. Programs may `MTS PER_*` / `PHASE_*` / `ECFG`.
