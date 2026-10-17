"""LEVEL trap must not fire on load-bus residue at RUN rise (2026-10-17).

Symptom: RTL PC jumps to LEVEL_LOW trap vector on cy0; ISS runs the program;
later OE diverges (ISS OD idle, RTL after trap path).
Root cause: sync1/filt still held load-bus levels at RUN rise so LEVEL_* was
live before post-run inputs; trap_req sampled that cycle. Fixed: snap sync on
RUN rise + suppress traps until run_q. Found 2026-10-17 in 1000×500 trial 24.
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
    "0x4000", "0x4400", "0x5420", "0x3114", "0x3020", "0x3220", "0x3320", "0x3420",
    "0x4000", "0x4401", "0x5420", "0x3334", "0x4000", "0x313c", "0x3440", "0x3244",
    "0x4001", "0x3a44", "0x7600", "0x7200", "0x2020", "0x3a4c", "0x888", "0xa140",
    "0x304c", "0x3e54", "0x63d0", "0x2020", "0x7400", "0x620", "0x354c", "0xd00",
    "0x2020", "0x8400", "0x7600", "0x304c", "0x5420", "0x307c", "0x4c6c", "0x309c",
]]
CFG = {
    "per": 4.0,
    "msb_first": False,
    "clk_en": False,
    "cpol": False,
    "cpha": True,
    "dout_lp": 2,
    "din_lp": 1,
    "clk_lp": 2,
    "tick_source": TickSource.TIMER,
    "default_byte": 247,
    "miss_policy": MissPolicy.FLAG,
    "miss_vector": 13,
    "pins": [
        {"physical": 3, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": True},
        {"physical": 5, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 0, "glitch_filter": True},
        {"physical": 6, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": True},
    ],
    "events": [
        {"kind": EventKind.LEVEL_HIGH, "pin": 0, "trap": False, "vector": 28},
        {"kind": EventKind.LEVEL_LOW, "pin": 3, "trap": True, "vector": 36},
        {"kind": EventKind.EDGE_FALL, "pin": 2, "latched": True, "trap": False, "vector": 12},
        {"kind": EventKind.LEVEL_HIGH, "pin": 0, "trap": False, "vector": 3},
    ],
}
HOST = [int(x, 16) for x in ["0x3da", "0xe3", "0x15a", "0x134", "0x318", "0x7b", "0x1f", "0x2c9"]]
EXT = [232, 253, 88, 112, 150, 116, 248, 76, 128, 13, 118, 144]


@cocotb.test()
async def level_trap_not_on_load_bus_at_run_rise(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    m = Machine()
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    iss = []
    for cy in range(20):
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
    for cy in range(20 + ALIGN):
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
