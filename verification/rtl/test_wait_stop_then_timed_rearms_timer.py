"""WAIT STOP (soft or tick) + same-cycle timed post must re-arm the timer.

When WAIT …, stop completes it asserts timer stop (queue or issue). An IN.T /
SET.T / XFER posted that same cycle must still start the timer — ISS calls
``_ensure_timer_for_timed`` after the stop. RTL must always assert ``tcmd_start``
on a successful timed post so start-after-stop in ``tick_timer`` restarts.
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
    encode_in,
    encode_jmp,
    encode_ldi,
    encode_set,
    encode_wait,
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
async def wait_stop_then_timed_rearms_timer(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = [
        encode_set(True, False, 0x4, 0x4),  # occupy active slot briefly
        encode_ldi(1, 2),
        encode_jmp(JmpCond.R1DEC, 2),
        encode_wait(WaitTc.STOP, 1 << 0),  # soft STOP on host data
        encode_in(True, 0),  # IN.T must re-arm after STOP
        encode_set(False, False, 0x8, 0x8),  # marker when IN.T done
        encode_jmp(JmpCond.AL, 6),
    ]
    cfg = {
        "per": 4.0,
        "phase": 0,
        "msb_first": False,
        "clk_en": False,
        "dout_lp": 0,
        "din_lp": 0,
        "tick_source": TickSource.TIMER,
        "miss_policy": MissPolicy.FLAG,
        "pins": [
            {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 1, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 0},
        ],
        "events": [{"kind": EventKind.HOST_DATA}],
    }
    host_words = [0x100]
    n = 40
    ext = [0xFF] * (n + 4)

    m = Machine()
    m.phys_ext = [(ext[0] >> p) & 1 for p in range(8)]
    m.load(img, [cfg])
    for hw in host_words:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    m.phys_ext = [(ext[0] >> p) & 1 for p in range(8)]
    m.step()
    iss = []
    saw_timer_after_int = False
    for cy in range(n):
        m.phys_ext = [(ext[min(cy, len(ext) - 1)] >> p) & 1 for p in range(8)]
        m.step()
        c = m.ctx[0]
        iss.append(_pads(m))
        if c.pc >= 5 and c.timer_running:
            saw_timer_after_int = True
    assert saw_timer_after_int, "IN.T must leave the timer running after WAIT STOP"

    hl = HostLink(dut)
    await hl.reset()
    await hl.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await hl.cfg_write_map({0x00: 0x01})
    await hl.load_program(img)
    for hw in host_words:
        await hl.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    rtl = await rtl_run_pad_trace(dut, hl, n, ext)
    for cy in range(n):
        io, ie = iss[cy]
        ro, re = rtl[cy]
        assert ie == re and (io & ie) == (ro & re), (
            f"cy={cy} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x})"
        )


@cocotb.test()
async def wait_tick_stop_then_int_rearms(dut):
    """WAIT tick,stop completing on a tick must not leave IN.T without a timer."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = [
        encode_wait(WaitTc.STOP, 1 << 4),
        encode_in(True, 0),
        encode_set(False, False, 0x8, 0x8),
        encode_jmp(JmpCond.AL, 3),
    ]
    cfg = {
        "per": 8.0,
        "phase": 0,
        "msb_first": False,
        "clk_en": True,
        "cpol": True,
        "cpha": True,
        "dout_lp": 2,
        "din_lp": 0,
        "clk_lp": 1,
        "tick_source": TickSource.TIMER,
        "miss_policy": MissPolicy.STRETCH,
        "pins": [
            {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 5, "mode": PinMode.OPENDRAIN, "idle": 1},
            {"physical": 7, "mode": PinMode.INPUT, "idle": 0},
            {"physical": 6, "mode": PinMode.PUSHPULL, "idle": 1},
        ],
        "events": [{"kind": EventKind.HOST_DATA}],
    }
    n = 48
    ext = [0x04] * (n + 4)
    m = Machine()
    m.phys_ext = [(ext[0] >> p) & 1 for p in range(8)]
    m.load(img, [cfg])
    m.phys_ext = [(ext[0] >> p) & 1 for p in range(8)]
    m.step()
    iss = []
    for cy in range(n):
        m.phys_ext = [(ext[min(cy, len(ext) - 1)] >> p) & 1 for p in range(8)]
        m.step()
        iss.append(_pads(m))
    assert any(oe & 0x20 for (_, oe) in iss[16:]), "engine clock OE should toggle after IN.T"

    hl = HostLink(dut)
    await hl.reset()
    await hl.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await hl.cfg_write_map({0x00: 0x01})
    await hl.load_program(img)
    rtl = await rtl_run_pad_trace(dut, hl, n, ext)
    for cy in range(n):
        io, ie = iss[cy]
        ro, re = rtl[cy]
        assert ie == re and (io & ie) == (ro & re), (
            f"cy={cy} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x})"
        )
