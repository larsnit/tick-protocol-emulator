"""ISS/RTL lockstep after enable: no phantom EDGE from sync→idle (2026-10-17).

Symptom: ISS oe=0x2c (trapped, no stretch), RTL oe=0x3c (MISS stretch on CLK_LP).
Root cause: ISS sync reset-1 then tracked PP idle=0 as EDGE_FALL/trap; RTL had
already settled before RUN and snapped pending on RUN rise. Fixed ISS enable snap.
Found 2026-10-17 in 1000×500 trial 15.
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
from tick.host_link import HostLink
from rtl_only import RTL_ONLY
from lockstep_harness import start_run, rtl_pads


IMG = [int(x, 16) for x in [
    "0x3f04", "0x40ff", "0x6060", "0x4408", "0x3510", "0x3f1c", "0x4000",
    "0x6010", "0x4404", "0x3524", "0x9000", "0x9440", "0x3030",
]]
CFG = {
    "per": 16.0,
    "phase": 0,
    "msb_first": False,
    "clk_en": False,
    "cpol": True,
    "cpha": False,
    "dout_lp": 0,
    "din_lp": 3,
    "clk_lp": 0,
    "tick_source": TickSource.TIMER,
    "default_byte": 11,
    "miss_policy": MissPolicy.STRETCH,
    "miss_vector": 5,
    "pins": [
        {"physical": 4, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": True},
        {"physical": 5, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": True},
        {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
        {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": True},
    ],
    "events": [
        {"kind": EventKind.LEVEL_LOW, "pin": 3, "qual_pin": 2, "trap": False, "vector": 1},
        {"kind": EventKind.HOST_SPACE, "pin": 0, "qual_pin": 1, "trap": False, "vector": 7},
        {"kind": EventKind.EDGE_FALL, "pin": 0, "qual_pin": 0, "latched": False, "trap": False, "vector": 5},
        {"kind": EventKind.EDGE_FALL, "pin": 1, "qual_pin": 2, "latched": True, "trap": True, "vector": 12},
    ],
}
HOST = [int(x, 16) for x in ["0x3d3", "0xc8", "0x267", "0xf1", "0x350", "0xa2", "0x30a", "0x20a"]]
EXT = [
    207, 166, 160, 7, 0, 44, 42, 169, 201, 70, 238, 165, 131, 168, 194, 163, 103, 0, 3,
    236, 35, 207, 192, 32, 137, 231, 44, 139, 226, 202, 129, 163, 64, 7, 3, 9, 97, 101,
    233, 197, 103, 38, 104, 3, 169, 175, 107, 228, 139, 44, 109, 105, 36, 7, 198, 111,
    238, 236, 102, 197, 134, 136, 14, 96, 47, 239, 15, 239, 98, 68,
]


@cocotb.test(skip=RTL_ONLY)  # probes user_project.core
async def trap_clears_stretch_oe_on_clk_lp(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    n = 80
    m = Machine()
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    iss = []
    for cy in range(n):
        m.phys_ext = [(EXT[min(cy, len(EXT) - 1)] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((out, oe, m.ctx[0].pc, m.ctx[0].stretching, m.ctx[0].evf))

    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, CFG, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(IMG)
    for hw in HOST:
        await host.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    dut.uio_in.value = EXT[0] if EXT else 0
    await start_run(host, dut)
    core = dut.user_project.core
    bad = None
    for cy in range(n):
        dut.uio_in.value = EXT[min(cy, len(EXT) - 1)]
        await RisingEdge(dut.clk)
        i = cy
        io, ie, ipc, ist, ievf = iss[i]
        ro, re = rtl_pads(dut)
        rpc = int(core.dbg_pc.value)
        rst = int(core.u_queue.stretching_obs.value) if hasattr(core.u_queue, "stretching_obs") else -1
        if ie != re or (io & ie) != (ro & re):
            bad = (i, io, ie, ro, re, ipc, rpc, ist, rst, ievf)
            dut._log.info(
                f"MISMATCH cy={i} ISS=({io:#x},{ie:#x}) pc={ipc} st={ist} evf={ievf:#x} "
                f"RTL=({ro:#x},{re:#x}) pc={rpc} st={rst}"
            )
            break
        if i <= 12 or i == 66:
            live = int(core.ev_live.value) & 0xF
            pend = int(core.ev_pending.value) & 0xF
            trap = int(core.u_events.trap_req.value) if hasattr(core, "event_trap_req") else -1
            lp = int(core.lp_in.value) & 0xF
            dut._log.info(
                f"cy={i} ISS=({io:#x},{ie:#x}) pc={ipc} st={ist} "
                f"RTL=({ro:#x},{re:#x}) pc={rpc} st={rst} "
                f"lp={lp:x} live={live:x} pend={pend:x} trap={trap}"
            )
    assert bad is None, bad
