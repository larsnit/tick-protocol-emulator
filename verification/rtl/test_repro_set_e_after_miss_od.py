"""SET.E after MISS trap must not drive OD idle-high pins (2026-10-17).

Symptom: 1000×500 trial25 cy23 ISS OE=0x20 RTL OE=0x60 (extra phys6).
Root cause: RTL idle/trap/miss path overwrote OD drv_val to 0 after assigning
pinidle; ISS keeps drive_val=idle. Post-trap SET.E enables OE with RTL val=0
→ drives low; ISS val=1 → stays released. Fix: leave OD drv_val=pinidle.
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


# WAIT tick (tc=none → timer keeps running) → MISS trap to SET.T.E on OD idle-high.
IMG = [
    0x2200,  # WAIT tick
    0x3008,  # JMP AL, 2
    0x0C88,  # SET.T.E mask=2 val=2  (enable OE on LP1 / phys6)
    0x300C,  # JMP AL, 3
]
CFG = {
    "per": 4.0,
    "phase": 0,
    "msb_first": True,
    "clk_en": False,
    "cpol": False,
    "cpha": True,
    "dout_lp": 2,
    "din_lp": 3,
    "clk_lp": 0,
    "tick_source": TickSource.TIMER,
    "default_byte": 0,
    "miss_policy": MissPolicy.TRAP,
    "miss_vector": 2,
    "pins": [
        {"physical": 3, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": False},
        {"physical": 6, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": False},
        {"physical": 1, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": False},
        {"physical": 5, "mode": PinMode.OPENDRAIN, "idle": 0, "glitch_filter": False},
    ],
    "events": [
        {"kind": EventKind.HOST_DATA, "vector": 0},
        {"kind": EventKind.HOST_DATA, "vector": 0},
        {"kind": EventKind.HOST_DATA, "vector": 0},
        {"kind": EventKind.HOST_DATA, "vector": 0},
    ],
}


@cocotb.test(skip=RTL_ONLY)  # probes user_project.core
async def set_e_after_miss_od_idle_high_stays_released(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    m = Machine()
    m.load(IMG, [CFG])
    n = 40
    iss = []
    post_miss_set_e = False
    for cy in range(n):
        m.phys_ext = [1] * 8
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        c = m.ctx[0]
        iss.append((out, oe, c.pc))
        # After MISS trap, SET.E with drive_val=idle must leave phys6 released.
        if c.miss and (c.drive_oe & 0x2) and c.timed_active is None:
            post_miss_set_e = True
            assert (oe & (1 << 6)) == 0, (
                f"ISS cy={cy} post-miss SET.E drove phys6 oe={oe:#x} val={c.drive_val:#x}"
            )
    assert post_miss_set_e, "never saw post-miss SET.E commit"

    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, CFG, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(IMG)
    dut.uio_in.value = 0xFF
    await start_run(host, dut)
    core = dut.user_project.core
    for cy in range(n):
        dut.uio_in.value = 0xFF
        await RisingEdge(dut.clk)
        i = cy
        io, ie, ipc = iss[i]
        ro, re = rtl_pads(dut)
        rpc = int(core.dbg_pc.value)
        assert ie == re and (io & ie) == (ro & re), (
            f"cy={i} ISS=({io:#04x},{ie:#04x}) pc={ipc} "
            f"RTL=({ro:#04x},{re:#04x}) pc={rpc}"
        )
        assert ipc == rpc, f"cy={i} pc ISS={ipc} RTL={rpc}"
