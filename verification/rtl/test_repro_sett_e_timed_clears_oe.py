"""Timed SET.E val=0 clears push-pull OE under CLK_EN (ISS↔RTL)."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, MissPolicy, PinMode, TickSource
from tick.cfg import dict_to_bytes
from tick.isa import JmpCond, encode_jmp, encode_set
from tick.host_link import HostLink
from lockstep_harness import start_run, rtl_pads

IMG = [
    encode_set(False, True, 0x8, 0x8),
    encode_set(True, True, 0x8, 0x0),
    encode_set(False, False, 0x8, 0x0),
    encode_jmp(JmpCond.AL, 2),
]
CFG = {
    "per": 4.0,
    "phase": 0,
    "clk_en": True,
    "cpol": True,
    "cpha": False,
    "msb_first": True,
    "tick_source": TickSource.TIMER,
    "dout_lp": 3,
    "din_lp": 0,
    "clk_lp": 1,
    "miss_policy": MissPolicy.TRAP,
    "miss_vector": 0,
    "pins": [
        {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
        {"physical": 3, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": False},
        {"physical": 1, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 7, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
    ],
    "events": [{"kind": EventKind.HOST_DATA} for _ in range(4)],
}


@cocotb.test()
async def sett_e_timed_val0_clears_pushpull_oe(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    n = 20
    m = Machine()
    m.load(IMG, [CFG])
    iss = []
    for _ in range(n):
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((out, oe, m.ctx[0].pc))
    assert any((oe & 0x80) == 0 for _, oe, _ in iss[1:]), "LP3 OE never cleared"

    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, CFG, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(IMG)
    # NOTE: drive uio_in before RUN for pin snap
    await start_run(host, dut)
    for cy in range(n):
        await RisingEdge(dut.clk)
        i = cy
        io, ie, ipc = iss[i]
        ro, re = rtl_pads(dut)
        assert ie == re and (io & ie) == (ro & re), f"oe cy={i}"
