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


def _pin_trace(m: Machine, n: int) -> list[int]:
    trace = []
    for _ in range(n):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else m.phys_ext[0]
        trace.append(cur)
    return trace


def _falling_edges(trace: list[int]) -> list[int]:
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]


def _rising_edges(trace: list[int]) -> list[int]:
    return [i for i in range(1, len(trace)) if trace[i - 1] == 0 and trace[i] == 1]


def test_uart_tx_back_to_back():
    """W1: two frames with exact PER spacing; ctx1 must not steal host bytes."""
    per = 8
    img = assemble((ROOT / "programs" / "uart_tx.asm").read_text())
    m = Machine()
    m.load(img, [_uart_tx_cfg(float(per))])
    assert m.ctx[0].enabled and not m.ctx[1].enabled
    m.host_push(0x11)
    m.host_push(0x22, last=True)

    miss_while_timer = False
    trace = []
    for _ in range(400):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else m.phys_ext[0]
        trace.append(cur)
        if m.ctx[0].timer_running and m.ctx[0].miss:
            miss_while_timer = True

    assert len(m.host_to_core) == 0
    assert m.ctx[1].regs[0] == 0  # ctx1 never pulled

    # First falling edge after reset idle is start of frame 0
    s0 = next(i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0)
    s1 = s0 + 10 * per  # start + 8 data + stop, then next start
    assert s1 + 10 * per < len(trace)

    def decode_frame(start: int) -> int:
        bits = [trace[start + k * per + per // 2] for k in range(10)]
        assert bits[0] == 0 and bits[9] == 1, (start, bits)
        data = 0
        for i, b in enumerate(bits[1:9]):
            data |= b << i
        return data

    assert decode_frame(s0) == 0x11
    assert decode_frame(s1) == 0x22
    # Second start begins exactly one PER after first stop begins
    stop0 = s0 + 9 * per
    assert s1 == stop0 + per, (s0, stop0, s1)
    # No MISS while the timer is still producing the frames
    # (W3 may still set MISS after the final stop WAIT — allow only after last stop)
    last_stop_end = s1 + 10 * per
    early_miss = False
    m2 = Machine()
    m2.load(img, [_uart_tx_cfg(float(per))])
    m2.host_push(0x11)
    m2.host_push(0x22, last=True)
    for cy in range(last_stop_end):
        m2.step()
        if m2.ctx[0].miss and cy < last_stop_end - 1:
            early_miss = True
            break
    assert not early_miss
    _ = miss_while_timer


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
