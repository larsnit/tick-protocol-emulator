# Generality gaps (pre-freeze check)

Programs assembled and checked against the ISS:
- UART TX / RX
- SPI controller / target
- I2C controller / target (sketches; address match uses AND+CMP+LDI)

## Extra protocols (ugly but expressible)

| Protocol | Fit | Notes |
|---|---|---|
| WS2812 | OK | Fixed T0H/T1H via PER changes or dual SET.T spacing; 24-bit needs two XFERs + colour in regs |
| PS/2 | OK | Open-drain clock/data, device as target with edge tick; parity in software |
| JTAG shift | OK | TMS/TDI/TCK/TDO on 4 logical pins; XFER both on TDI/TDO |
| SWD | Awkward | Turnaround mid-transaction needs OE flip between ticks; doable with SET.E |

## Gaps that did **not** force an encoding change

1. No inter-context data path (event from other context still open).
2. SPI register-read reply within half SCLK still needs stretch, dummy cycles, or a later assist.
3. ADDI not required for I2C target at current size (~22 instructions).
4. Capture/monitor works as `WAIT` edge → `MFS TIME` → `PUSH` (no hardware capture yet).

Freeze stands as in [docs/isa.md](isa.md).
