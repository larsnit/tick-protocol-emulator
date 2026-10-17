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
from rtl_bus import load_cfg_bytes, load_program, reset_dut

ALIGN = 1
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

    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, CFG, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, IMG)
    dut.ui_in.value = 1 << 3
    for cy in range(n + ALIGN):
        await RisingEdge(dut.clk)
        if cy < ALIGN:
            continue
        i = cy - ALIGN
        io, ie, ipc = iss[i]
        ro = int(dut.uio_out.value) & 0xFF
        re = int(dut.uio_oe.value) & 0xFF
        assert ie == re and (io & ie) == (ro & re), f"oe cy={i}"
