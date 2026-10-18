"""No phantom QUAL/EDGE trap the cycle after RUN rise (trial298 class).

Symptom: fuzz trial298 cy1 RTL PC jumps to QUAL trap vector; ISS continues.
Root cause: on RUN rise, lp_prev snapped to pre-snap lp_in while sync snapped
to pin_raw — next cycle looked like QUAL_RISE. Fix: snap lp_prev to lp_snap
(pin_raw mapped to LPs).
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
from tick.isa import JmpCond, encode_jmp, encode_ldi
from tick.host_link import HostLink
from rtl_only import RTL_ONLY
from lockstep_harness import start_run, rtl_pads

IMG = [
    encode_ldi(0, 0),
    encode_ldi(0, 1),
    encode_ldi(0, 2),
    encode_jmp(JmpCond.AL, 3),
    encode_jmp(JmpCond.AL, 4),  # trap vector — must not reach
]
CFG = {
    "per": 4.0,
    "phase": 0,
    "msb_first": True,
    "clk_en": False,
    "cpol": False,
    "cpha": True,
    "dout_lp": 1,
    "din_lp": 3,
    "clk_lp": 0,
    "tick_source": TickSource.TIMER,
    "default_byte": 0,
    "miss_policy": MissPolicy.FLAG,
    "miss_vector": 0,
    "pins": [
        {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": True},
        {"physical": 7, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
        {"physical": 3, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": True},
        {"physical": 4, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
    ],
    "events": [
        {"kind": EventKind.QUAL_RISE_WHILE_HIGH, "pin": 0, "qual_pin": 1, "trap": True, "vector": 4},
        {"kind": EventKind.EDGE_FALL, "pin": 0, "latched": True, "trap": False, "vector": 0},
        {"kind": EventKind.LEVEL_HIGH, "pin": 2, "trap": False, "vector": 0},
        {"kind": EventKind.QUAL_FALL_WHILE_HIGH, "pin": 0, "qual_pin": 0, "trap": False, "vector": 0},
    ],
}
# Static high on pin0/qual — snap must not invent a rise.
EXT = [0xFF] * 16


@cocotb.test(skip=RTL_ONLY)  # probes user_project.core
async def no_phantom_qual_trap_after_run_rise(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    m = Machine()
    m.phys_ext = [(EXT[0] >> p) & 1 for p in range(8)]
    m.load(IMG, [CFG])
    n = 12
    iss = []
    for cy in range(n):
        m.phys_ext = [(EXT[min(cy, len(EXT) - 1)] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((out, oe, m.ctx[0].pc))
        assert m.ctx[0].pc != 4, f"ISS phantom QUAL trap cy={cy}"

    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, CFG, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(IMG)
    dut.uio_in.value = EXT[0] if EXT else 0
    await start_run(host, dut)
    core = dut.user_project.core
    for cy in range(n):
        dut.uio_in.value = EXT[min(cy, len(EXT) - 1)]
        await RisingEdge(dut.clk)
        i = cy
        io, ie, ipc = iss[i]
        ro, re = rtl_pads(dut)
        rpc = int(core.dbg_pc.value)
        assert rpc != 4, f"RTL phantom QUAL trap cy={i} pc={rpc}"
        assert ie == re and (io & ie) == (ro & re), (
            f"cy={i} ISS=({io:#04x},{ie:#04x}) pc={ipc} RTL=({ro:#04x},{re:#04x}) pc={rpc}"
        )
        assert ipc == rpc, f"cy={i} pc ISS={ipc} RTL={rpc}"
