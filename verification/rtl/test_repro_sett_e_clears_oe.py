"""Own-drive delay must zero undriven map bits (SET.E clear then trap restore).

After SET.E clears PP OE, ISS used to keep shifting stale phys_drive into the
own-delay pipe; RTL map_out is 0 when not driving. Re-enabling OE then made ISS
see an EDGE_RISE one cycle early vs RTL. Lockstep of a pin-edge+CLK_EN program
that clears OE then traps (idle restore) must match.
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
    "0x6010", "0x4406", "0x3508", "0x6050", "0x440a", "0x3514", "0x6090", "0x440e",
    "0x3520", "0x60d0", "0x4412", "0x352c", "0x4001", "0x1200", "0x3034", "0x5300",
    "0x401c", "0x1a00", "0x3544", "0x2020", "0x6710", "0x48c5", "0xc44", "0x8a00",
    "0x7c00", "0x2200", "0x68e0", "0x5420", "0x3344", "0x5520", "0x3654", "0x3a68",
    "0x44", "0x440", "0x3d64", "0x2020", "0x8300", "0x3080", "0x44cf", "0x309c",
]]
CFG = {
    "per": 4.0, "phase": 0, "msb_first": True, "clk_en": True, "cpol": True, "cpha": False,
    "dout_lp": 0, "din_lp": 2, "clk_lp": 3,
    "tick_source": TickSource.PIN_EDGE, "tick_pin": 3, "tick_on_rise": True,
    "default_byte": 250, "miss_policy": MissPolicy.TRAP, "miss_vector": 5,
    "pins": [
        {"physical": 4, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
        {"physical": 7, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 5, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": True},
        {"physical": 1, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": False},
    ],
    "events": [
        {"kind": EventKind.EDGE_RISE, "pin": 0, "qual_pin": 2, "latched": True, "trap": True, "vector": 27},
        {"kind": EventKind.QUAL_RISE_WHILE_HIGH, "pin": 2, "qual_pin": 1, "latched": False, "trap": True, "vector": 28},
        {"kind": EventKind.EDGE_RISE, "pin": 3, "qual_pin": 2, "latched": False, "trap": False, "vector": 33},
        {"kind": EventKind.QUAL_FALL_WHILE_HIGH, "pin": 0, "qual_pin": 3, "latched": False, "trap": False, "vector": 10},
    ],
}
HOST = [int(x, 16) for x in ["0x3fc", "0x7c", "0x56", "0x1c4", "0x3ee", "0x196", "0x234", "0x38"]]
EXT = [136, 132, 255, 2, 109, 60, 75, 166, 9, 5, 170, 3, 44, 128, 46, 38, 144, 44, 171, 230, 9, 161, 39, 235, 68, 165, 79, 254, 108, 72, 6, 10, 44, 189, 7, 43, 224, 172, 111, 47, 97, 4, 135, 103, 33, 5, 143, 143, 105, 65, 99, 39, 229, 13, 231, 174, 224, 44, 231, 167, 64, 233, 206, 198, 8, 232, 6, 99, 192, 5, 167, 203, 205, 213, 71, 175, 1, 225, 110, 11, 72, 108, 163, 106, 169, 205, 42, 183, 220, 140, 99, 163, 53, 12, 75, 206, 89, 205, 230, 3, 69, 172, 66, 174, 77, 53, 74, 46, 197, 168, 79, 67, 197, 77, 250, 115, 57, 109, 55, 98, 228, 225, 15, 110, 100, 137, 42, 31, 109, 228, 203, 199, 164, 12, 159, 150, 205, 145, 10, 38, 136, 193, 199, 34, 40, 200, 239, 175, 69, 200, 35, 106, 32, 201, 47, 255, 224, 13, 19, 206, 8, 45, 239, 106, 161, 161, 107, 38, 249, 161, 102, 167, 73, 233, 134, 15, 224, 97, 67, 46, 72, 164, 142, 238, 77, 64, 126, 163, 164, 249, 206, 226, 88, 0, 22, 166, 109, 196]


@cocotb.test(skip=RTL_ONLY)  # probes user_project.core
async def sett_e_val0_clears_pushpull_oe(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    n = len(EXT)
    m = Machine()
    m.enable_trace = True
    m.phys_ext = [(EXT[0] >> p) & 1 for p in range(8)]
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    # Warmup step discarded: SPI's first post-RUN edge is snap+exec; recorded
    # cycles start one execute later (tick-ref abs cy ≥ 1).
    m.phys_ext = [(EXT[0] >> p) & 1 for p in range(8)]
    m.step()
    # RTL sees ext one early (PIN_LEAD) so pin-edge ticks match ISS end-capture.
    PIN_LEAD = 1
    iss = []
    for cy in range(n):
        m.phys_ext = [(EXT[cy] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((out, oe, m.ctx[0].pc, bool(m.trace[-1]["tick0"])))

    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, CFG, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(IMG)
    for hw in HOST:
        await host.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    dut.uio_in.value = EXT[0]
    await start_run(host, dut)
    core = dut.user_project.core
    dut.uio_in.value = EXT[0]
    await RisingEdge(dut.clk)  # warmup snap+exec
    first_pc = first_oe = None
    for cy in range(n):
        dut.uio_in.value = EXT[min(cy + PIN_LEAD, n - 1)]
        await RisingEdge(dut.clk)
        io, ie, ipc, itick = iss[cy]
        # Registered pads: combo OE can lead ISS by one when PIN_LEAD advances
        # timed posts; registered matches ISS phys_* (tick-ref pad compare).
        ro, re = rtl_pads(dut)
        rpc = int(core.dbg_pc.value)
        if cy <= 8 or (30 <= cy <= 45) or (ipc != rpc and first_pc is None):
            dut._log.info(
                f"cy={cy} ISS_pc={ipc} itick={int(itick)} RTL_pc={rpc} "
                f"rtick={int(core.dbg_tick.value)} oe I={ie:#04x} R={re:#04x}"
            )
        if first_pc is None and ipc != rpc:
            first_pc = (cy, ipc, rpc, itick, int(core.dbg_tick.value))
            dut._log.info(
                f"first PC diverge cy={cy} ISS={ipc} RTL={rpc} "
                f"itick={itick} rtick={int(core.dbg_tick.value)}"
            )
        if first_oe is None and (ie != re or (io & ie) != (ro & re)):
            first_oe = (cy, ie, re, ipc, rpc)
            dut._log.info(
                f"first OE diverge cy={cy} ISS_oe={ie:#04x} RTL_oe={re:#04x} "
                f"ISS_pc={ipc} RTL_pc={rpc}"
            )
            raise AssertionError(f"oe cy={cy}")
    if first_pc is not None:
        raise AssertionError(f"pc diverge {first_pc}")
