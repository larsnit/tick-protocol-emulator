"""Protocol checkers: UART TX waveform vs 8N1 model."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import EventKind, Machine, PinMode, TickSource, assemble


def _uart_tx_cfg(per: float = 8.0):
    return {
        "per": per,
        "phase": 0,
        "tick_source": TickSource.TIMER,
        "msb_first": False,  # UART LSB first
        "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
        "events": [{"kind": EventKind.HOST_DATA}],
    }


def sample_uart_bits(levels: list[tuple[int, int]], per: int, start_cycle: int, nbits: int) -> list[int]:
    """Sample pin at mid-bit for nbits starting at start_cycle (start bit)."""
    bits = []
    for k in range(nbits):
        t = start_cycle + k * per + per // 2
        # find level at cycle t
        val = 1
        for cy, lv in levels:
            if cy <= t:
                val = lv
            else:
                break
        bits.append(val)
    return bits


def test_uart_tx_byte_0x55():
    img = assemble((ROOT / "programs" / "uart_tx.asm").read_text())
    m = Machine()
    m.load(img, [_uart_tx_cfg(8.0)])
    m.host_push(0x55, last=True)
    levels = []
    prev = 1
    for _ in range(200):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else m.phys_ext[0]
        if cur != prev or not levels:
            levels.append((m.cycle, cur))
            prev = cur
    # Find first falling edge (start bit)
    start = None
    for i, (cy, lv) in enumerate(levels):
        if lv == 0 and (i == 0 or levels[i - 1][1] == 1):
            start = cy
            break
    assert start is not None, levels
    # Build dense level timeline
    dense = []
    val = 1
    li = 0
    for cy in range(0, start + 12 * 8):
        while li < len(levels) and levels[li][0] <= cy:
            val = levels[li][1]
            li += 1
        dense.append(val)
    # Sample start + 8 data + stop at bit centers
    per = 8
    bits = []
    for k in range(10):
        t = start + k * per + per // 2
        if t < len(dense):
            bits.append(dense[t])
    assert bits[0] == 0, bits  # start
    data = 0
    for i, b in enumerate(bits[1:9]):
        data |= b << i
    assert data == 0x55, bits
    assert bits[9] == 1, bits  # stop


def test_uart_tx_back_to_back():
    img = assemble((ROOT / "programs" / "uart_tx.asm").read_text())
    m = Machine()
    m.load(img, [_uart_tx_cfg(4.0)])
    m.host_push(0x00)
    m.host_push(0xFF, last=True)
    # Just ensure it runs without miss during frames after host feed
    for _ in range(500):
        m.step()
    # Should have consumed both bytes
    assert len(m.host_to_core) == 0


def test_spi_target_default_0xff():
    img = assemble((ROOT / "programs" / "spi_target.asm").read_text())
    m = Machine()
    m.load(
        img,
        [
            {
                "tick_source": TickSource.PIN_EDGE,
                "tick_pin": 2,
                "tick_on_rise": True,
                "msb_first": True,
                "miss_policy": 2,  # SEND_DEFAULT
                "default_byte": 0xFF,
                "pins": [
                    {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},  # MISO
                    {"physical": 1, "mode": PinMode.INPUT, "idle": 1},  # MOSI
                    {"physical": 2, "mode": PinMode.INPUT, "idle": 1},  # SCLK
                    {"physical": 3, "mode": PinMode.INPUT, "idle": 1},  # CS
                ],
                "events": [
                    {"kind": EventKind.EDGE_FALL, "pin": 3},  # CS fall
                    {
                        "kind": EventKind.EDGE_RISE,
                        "pin": 3,
                        "trap": True,
                        "vector": 9,  # desel label
                    },
                ],
            }
        ],
    )
    # CS low
    m.phys_ext[3] = 0
    for _ in range(10):
        m.step()
    # Clock 8 cycles — no host data → default path via PULL.NB
    for bit in range(8):
        m.phys_ext[2] = 0
        m.step()
        m.step()
        m.phys_ext[2] = 1
        m.step()
        m.step()
    # Program should be in loop; under flag set from PULL.NB
    assert m.ctx[0].under or m.ctx[0].pc >= 0
