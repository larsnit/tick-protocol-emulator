"""Directed lockstep repro for fuzz trial=11 TIME_L off-by-one (seed 0xb22df2b2)."""

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
from rtl_bus import load_cfg_bytes, load_program, push_host, reset_dut

IMG = [
    0x4401, 0x350C, 0x4000, 0x3514, 0x4001, 0x5020, 0x5220, 0x5420, 0x5620,
    0x5820, 0x5A20, 0x5C20, 0x5E20, 0x6400, 0x0C44, 0x96C0, 0x9480, 0x0110,
    0x3034, 0x3C44, 0x6710, 0x3054, 0x6450, 0x4052, 0x7600, 0x2020, 0x5BC0,
    0x9340, 0x383C, 0x6500, 0x3954, 0x7600, 0x1600, 0x5420, 0x336C, 0x1000,
    0x8700, 0x3574, 0x4CAF, 0x309C,
]
CFG = {
    "per": 4.0,
    "phase": 0,
    "msb_first": False,
    "clk_en": False,
    "cpol": False,
    "cpha": False,
    "dout_lp": 2,
    "din_lp": 3,
    "tick_source": TickSource.TIMER,
    "default_byte": 200,
    "pins": [
        {"physical": 2, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 4, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
        {"physical": 5, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
        {"physical": 3, "mode": PinMode.INPUT, "idle": 0, "glitch_filter": False},
    ],
    "events": [{"kind": EventKind.HOST_DATA} for _ in range(4)],
}
HOST = [0x33E, 0xA3, 0x3DF, 0x145, 0x38C, 0x2D2, 0x79, 0xB3]
EXT = [
    132, 67, 78, 22, 152, 23, 197, 197, 13, 138, 189, 91, 199, 75, 192, 85,
    149, 34, 154, 95, 205, 199, 217, 209, 79, 131, 30, 68,
]
ALIGN = 1
N_CYC = 40


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
async def repro_trial11_time_l_xfer(dut):
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
        if ie != re or (io & ie) != (ro & re):
            raise AssertionError(
                f"mismatch cy={i} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x})"
            )
