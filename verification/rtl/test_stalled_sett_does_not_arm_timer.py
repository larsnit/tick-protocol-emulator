"""Stalled SET.T must not arm the timer (docs §2 rule 4: arm on post).

WAIT idle stops the timer while an XFER (+ pending SET.T) fills the queue.
A further SET.T that stalls must leave timer_run=0 — ISS previously armed on
the attempt and then advanced the frozen XFER on engine-clock ticks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, MissPolicy, PinMode, TickSource
from tick.cfg import dict_to_bytes
from tick.isa import (
    JmpCond,
    WaitTc,
    XferMode,
    encode_jmp,
    encode_ldi,
        encode_set,
    encode_wait,
    encode_xfer,
)
from tick.host_link import HostLink
from lockstep_harness import rtl_run_pad_trace


def _pads(m: Machine) -> tuple[int, int]:
    out = oe = 0
    for p in range(8):
        if m.phys_oe[p]:
            oe |= 1 << p
            out |= (m.phys_drive[p] & 1) << p
    return out, oe


@cocotb.test()
async def stalled_sett_does_not_arm_timer(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    # XFER both fills active; SET.T fills pending; WAIT idle stops timer;
    # LDI; SET.T stalls (queue full) — timer must stay stopped.
    img = [
        encode_xfer(0, 3, XferMode.BOTH),
        encode_set(True, True, 0x1, 0x1),
        encode_wait(WaitTc.IDLE, 1 << 0),
        encode_ldi(0, 0xCD),
        encode_set(True, False, 0x4, 0x4),
        encode_jmp(JmpCond.AL, 5),
    ]
    cfg = {
        "per": 16.0,
        "phase": 0,
        "msb_first": True,
        "clk_en": True,
        "cpol": True,
        "cpha": False,
        "dout_lp": 0,
        "din_lp": 2,
        "clk_lp": 3,
        "tick_source": TickSource.TIMER,
        "default_byte": 60,
        "miss_policy": MissPolicy.FLAG,
        "pins": [
            {"physical": 4, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 6, "mode": PinMode.PUSHPULL, "idle": 1},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 7, "mode": PinMode.OPENDRAIN, "idle": 1},
        ],
        "events": [{"kind": EventKind.HOST_DATA}],
    }
    host_words = [0x3F3, 0xCB]
    n = 48
    ext = [0xEE] * (n + 4)

    m = Machine()
    m.phys_ext = [(ext[0] >> p) & 1 for p in range(8)]
    m.load(img, [cfg])
    for hw in host_words:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    m.phys_ext = [(ext[0] >> p) & 1 for p in range(8)]
    m.step()  # SPI warmup
    iss = []
    for cy in range(n):
        m.phys_ext = [(ext[min(cy, len(ext) - 1)] >> p) & 1 for p in range(8)]
        m.step()
        iss.append((_pads(m), m.ctx[0].timer_running, m.ctx[0].pc))

    # After WAIT idle + stalled SET.T, timer must stay off for the rest.
    assert any(not tr and pc >= 4 for (_, tr, pc) in iss[8:]), iss[8:16]
    assert all(not tr for (_, tr, _) in iss[16:]), [t for t in iss[16:] if t[1]]

    hl = HostLink(dut)
    await hl.reset()
    await hl.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await hl.cfg_write_map({0x00: 0x01})
    await hl.load_program(img)
    for hw in host_words:
        await hl.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    rtl = await rtl_run_pad_trace(dut, hl, n, ext)
    for cy in range(n):
        (io, ie), _, _ = iss[cy]
        ro, re = rtl[cy]
        assert ie == re and (io & ie) == (ro & re), (
            f"cy={cy} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x})"
        )
