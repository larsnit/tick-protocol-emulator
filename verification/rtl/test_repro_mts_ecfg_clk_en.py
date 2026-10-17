"""MTS ECFG with CLK_EN=1: ISS↔RTL pin lockstep (engine clock landed)."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, PinMode, TickSource
from tick.cfg import dict_to_bytes
from tick.isa import JmpCond, Spr, XferMode, encode_jmp, encode_ldi, encode_mts, encode_xfer
from rtl_bus import load_cfg_bytes, load_program, push_host, reset_dut

IMG = [
    encode_ldi(1, 0x0F),  # MSB|CLK_EN|CPHA|CPOL
    encode_mts(1, Spr.ECFG),
    encode_xfer(0, 1, XferMode.IN),
    encode_jmp(JmpCond.AL, 3),
]
CFG = {
    "per": 4.0,
    "phase": 0,
    "msb_first": True,
    "clk_en": False,
    "cpol": False,
    "cpha": False,
    "dout_lp": 2,
    "din_lp": 3,
    "tick_source": TickSource.TIMER,
    "default_byte": 0,
    "pins": [
        {"physical": 4, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 2, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 1, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
        {"physical": 6, "mode": PinMode.INPUT, "idle": 0, "glitch_filter": False},
    ],
    "events": [{"kind": EventKind.HOST_DATA} for _ in range(4)],
}
HOST = [0x300]
EXT = [0] * 40
ALIGN = 1
N_CYC = 24


def _iss_trace():
    m = Machine()
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    tr = []
    for cy in range(N_CYC):
        m.phys_ext = [(EXT[min(cy, len(EXT) - 1)] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        tr.append((out, oe))
    return tr


@cocotb.test()
async def lockstep_clk_en_after_mts_ecfg(dut):
    """CLK_EN via MTS ECFG: pad drive matches ISS (two ticks per bit)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    iss = _iss_trace()
    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, CFG, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, IMG)
    for hw in HOST:
        await push_host(dut, hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    dut.ui_in.value = 1 << 3
    rtl = []
    for cy in range(N_CYC + ALIGN):
        dut.uio_in.value = EXT[min(cy, len(EXT) - 1)]
        await RisingEdge(dut.clk)
        rtl.append((int(dut.uio_out.value) & 0xFF, int(dut.uio_oe.value) & 0xFF))
    for i in range(N_CYC):
        io, ie = iss[i]
        ro, re = rtl[i + ALIGN]
        assert ie == re and (io & ie) == (ro & re), (
            f"CLK_EN lockstep cy={i} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x})"
        )
