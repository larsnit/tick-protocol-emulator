"""Fuzz trial83 lockstep: QUAL traps + STRETCH + SET.T after timer stop.

Covered canonically by test_repro_trap_sett_timer_restart (trap stops timer;
same-cycle SET.T restarts; tick 0 = post+PHASE). This keeps the original
minimized seed program as a regression.
"""

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
from rtl_bus import load_cfg_bytes, load_program, push_host, reset_dut

ALIGN = 1
IMG = [int(x, 16) for x in [
    "0x4401", "0x350c", "0x4000", "0x3514", "0x4001", "0x5020", "0x5220", "0x5420",
    "0x5620", "0x5820", "0x5a20", "0x5c20", "0x5e20", "0x5420", "0x3038", "0x100",
    "0x900", "0x7c00", "0x51a0", "0x900", "0xa1c0", "0x7800", "0x3558", "0x3b50",
    "0x5420", "0x5100", "0x2200", "0x8700", "0x44", "0x9880", "0x98c0", "0xc80",
    "0x8400", "0x7800", "0x9540", "0x57e0", "0x7c00", "0x3080", "0xe20", "0x309c",
]]
CFG = {
    "per": 4.0, "phase": 0, "msb_first": False, "clk_en": False, "cpol": True, "cpha": False,
    "dout_lp": 1, "din_lp": 0, "clk_lp": 0, "tick_source": TickSource.TIMER,
    "default_byte": 123, "miss_policy": MissPolicy.STRETCH, "miss_vector": 28,
    "pins": [
        {"physical": 6, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": False},
        {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": True},
        {"physical": 2, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": True},
        {"physical": 5, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
    ],
    "events": [
        {"kind": EventKind.QUAL_FALL_WHILE_HIGH, "pin": 1, "qual_pin": 3, "latched": True, "trap": True, "vector": 30},
        {"kind": EventKind.QUAL_RISE_WHILE_HIGH, "pin": 3, "qual_pin": 0, "latched": False, "trap": True, "vector": 16},
        {"kind": EventKind.QUAL_FALL_WHILE_HIGH, "pin": 2, "qual_pin": 1, "latched": True, "trap": False, "vector": 6},
        {"kind": EventKind.EDGE_FALL, "pin": 0, "qual_pin": 0, "latched": False, "trap": False, "vector": 22},
    ],
}
HOST = [0x383, 0xd0, 0x225, 0x215, 0x47, 0x22f, 0x33d, 0x317]
EXT = [42, 224, 142, 184, 76, 188, 86, 70, 196, 176, 234, 248, 112, 94, 4, 238, 156, 50, 132, 110, 40, 50, 66, 240, 182, 156, 18, 157, 84, 182, 54, 230, 64]


@cocotb.test()
async def trial83_lockstep(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    m = Machine()
    m.phys_ext = [(EXT[0] >> p) & 1 for p in range(8)]
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    iss = []
    for cy in range(40):
        m.phys_ext = [(EXT[min(cy, len(EXT) - 1)] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((out, oe, m.ctx[0].pc))
    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, CFG, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, IMG)
    for hw in HOST:
        await push_host(dut, hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    dut.ui_in.value = 1 << 3
    core = dut.user_project.core
    for cy in range(40 + ALIGN):
        dut.uio_in.value = EXT[min(cy, len(EXT) - 1)]
        await RisingEdge(dut.clk)
        if cy < ALIGN:
            continue
        i = cy - ALIGN
        io, ie, ipc = iss[i]
        ro = int(dut.uio_out.value) & 0xFF
        re = int(dut.uio_oe.value) & 0xFF
        rpc = int(core.dbg_pc.value)
        assert ie == re and (io & ie) == (ro & re), (
            f"cy={i} ISS=({io:#04x},{ie:#04x}) pc={ipc} RTL=({ro:#04x},{re:#04x}) pc={rpc}"
        )
        assert ipc == rpc, f"cy={i} pc ISS={ipc} RTL={rpc}"
