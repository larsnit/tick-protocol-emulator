"""Fuzz seed 0xc0ffee01 trial 475: pin7 OE ISS=0 RTL=1 at cy 44.

Root cause: MFS RX waited on registered res_valid, so after XFER completed it
woke one cycle late vs ISS (_on_tick then _service_waits then _exec). PC skew
meant ISS ran SET.E (clear LP3/phys7 OE) while RTL still ran the next XFER
(which re-asserts dout OE). Fix: issue sees res_valid_comb/result_comb.
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
from lockstep_harness import rtl_pads, start_run

IMG = [int(x, 16) for x in [
    "0x4401", "0x350c", "0x4000", "0x3514", "0x4001", "0x5020", "0x5220", "0x5420",
    "0x5620", "0x5820", "0x5a20", "0x5c20", "0x5e20", "0x600", "0x48a1", "0x7000",
    "0x4886", "0x6d80", "0x9c00", "0x7e00", "0x7200", "0x6520", "0x600", "0x910",
    "0x2020", "0x8600", "0x1400", "0x510", "0x7e00", "0x7200", "0x69a0", "0x840",
    "0x8b00", "0x6f10", "0x7200", "0x8600", "0x7000", "0x307c", "0x1600", "0x309c",
]]
CFG = {
    "per": 16.0,
    "phase": 0,
    "msb_first": True,
    "clk_en": False,
    "cpol": False,
    "cpha": False,
    "dout_lp": 3,
    "din_lp": 2,
    "clk_lp": 2,
    "tick_source": TickSource.PIN_EDGE,
    "tick_pin": 1,
    "tick_on_rise": True,
    "default_byte": 77,
    "miss_policy": MissPolicy.STRETCH,
    "miss_vector": 6,
    "pins": [
        {"physical": 6, "mode": PinMode.INPUT, "idle": 0, "glitch_filter": True},
        {"physical": 4, "mode": PinMode.INPUT, "idle": 0, "glitch_filter": True},
        {"physical": 3, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": True},
        {"physical": 7, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
    ],
    "events": [
        {"kind": EventKind.HOST_SPACE, "pin": 1, "qual_pin": 0, "trap": False, "vector": 5},
        {"kind": EventKind.EDGE_RISE, "pin": 2, "qual_pin": 0, "latched": False, "trap": False, "vector": 4},
        {
            "kind": EventKind.QUAL_RISE_WHILE_HIGH,
            "pin": 2,
            "qual_pin": 3,
            "latched": False,
            "trap": True,
            "vector": 22,
        },
        {"kind": EventKind.EDGE_FALL, "pin": 2, "qual_pin": 2, "latched": False, "trap": False, "vector": 31},
    ],
}
HOST = [int(x, 16) for x in ["0x320", "0x6f", "0x10c", "0x2ac", "0x11f", "0x2dd", "0x388", "0x4f"]]
EXT = [
    203, 39, 81, 89, 228, 2, 91, 17, 111, 3, 62, 82, 67, 111, 179, 50, 109, 65, 48, 56,
    131, 239, 60, 149, 46, 107, 82, 92, 7, 138, 20, 21, 228, 38, 55, 115, 100, 79, 94,
    119, 47, 77, 118, 31, 33, 47, 83, 94,
]


@cocotb.test(skip=RTL_ONLY)  # probes user_project.core
async def pin7_oe_matches_iss_after_dout_lp3_idle(dut):
    """At fuzz trial 475 cy 44, phys7 OE must match ISS (undriven)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    n = len(EXT)
    m = Machine()
    m.phys_ext = [(EXT[0] >> p) & 1 for p in range(8)]
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    m.phys_ext = [(EXT[0] >> p) & 1 for p in range(8)]
    m.step()  # warmup
    PIN_LEAD = 1
    iss = []
    iss_pc = []
    for cy in range(n):
        m.phys_ext = [(EXT[cy] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((out, oe))
        iss_pc.append(m.ctx[0].pc)

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
    dut.uio_in.value = EXT[0]
    await RisingEdge(dut.clk)  # warmup
    first = None
    for cy in range(n):
        dut.uio_in.value = EXT[min(cy + PIN_LEAD, n - 1)]
        await RisingEdge(dut.clk)
        io, ie = iss[cy]
        ro, re = rtl_pads(dut)
        rpc = int(core.dbg_pc.value)
        if ie != re or (io & ie) != (ro & re) or iss_pc[cy] != rpc:
            first = (cy, io, ie, ro, re, iss_pc[cy], rpc)
            break
    assert first is None, (
        f"first diverge cy={first[0]} ISS=({first[1]:#04x},{first[2]:#04x}) "
        f"RTL=({first[3]:#04x},{first[4]:#04x}) ISS_pc={first[5]} RTL_pc={first[6]}"
    )
    cy = 44
    io, ie = iss[cy]
    assert (ie & 0x80) == 0, "expected phys7 undriven at cy 44"
