"""Fuzz trial197: ISS OE=0 vs RTL OE=0x10 at cy194 (engine+pin-edge)."""

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
    "0x6010", "0x4406", "0x3508", "0x6050", "0x440a", "0x3514", "0x6090", "0x440e",
    "0x3520", "0x60d0", "0x4412", "0x352c", "0x4001", "0x1200", "0x3034", "0x5300",
    "0x401c", "0x1a00", "0x3544", "0x2020", "0x6710", "0x48c5", "0xc44", "0x8a00",
    "0x7c00", "0x2200", "0x68e0", "0x5420", "0x3344", "0x5520", "0x3654", "0x3a68",
    "0x44", "0x440", "0x3d64", "0x2020", "0x8300", "0x3080", "0x44cf", "0x309c",
]]
CFG = {
    "per": 4.0, "phase": 0, "msb_first": True, "clk_en": True, "cpol": True, "cpha": False,
    "dout_lp": 3, "din_lp": 2, "clk_lp": 3,
    "tick_source": TickSource.PIN_EDGE, "tick_pin": 3, "tick_on_rise": True,
    "default_byte": 250, "miss_policy": MissPolicy.TRAP, "miss_vector": 5,
    "pins": [
        {"physical": 4, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
        {"physical": 7, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 5, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": True},
        {"physical": 1, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": True},
    ],
    "events": [
        {"kind": EventKind.EDGE_RISE, "pin": 0, "qual_pin": 2, "latched": True, "trap": True, "vector": 27},
        {"kind": EventKind.QUAL_RISE_WHILE_HIGH, "pin": 2, "qual_pin": 1, "latched": False, "trap": True, "vector": 28},
        {"kind": EventKind.EDGE_RISE, "pin": 3, "qual_pin": 2, "latched": False, "trap": False, "vector": 33},
        {"kind": EventKind.QUAL_FALL_WHILE_HIGH, "pin": 0, "qual_pin": 3, "latched": False, "trap": False, "vector": 10},
    ],
}
HOST = [int(x, 16) for x in ["0x3fc", "0x7c", "0x56", "0x1c4", "0x3ee", "0x196", "0x234", "0x38"]]
EXT = [152, 148, 255, 18, 125, 60, 75, 166, 25, 5, 170, 19, 60, 144, 46, 54, 144, 44, 171, 246, 25, 161, 39, 235, 68, 165, 95, 254, 108, 72, 6, 10, 44, 189, 7, 43, 224, 172, 127, 47, 97, 4, 135, 119, 33, 5, 159, 143, 105, 81, 99, 39, 229, 13, 247, 174, 224, 44, 231, 183, 64, 233, 206, 214, 8, 232, 6, 99, 192, 5, 183, 219, 205, 213, 71, 191, 17, 225, 110, 11, 72, 124, 163, 106, 185, 205, 58, 183, 220, 140, 99, 163, 53, 12, 75, 206, 89, 205, 230, 3, 85, 172, 66, 174, 93, 53, 74, 62, 197, 168, 79, 67, 197, 77, 250, 115, 57, 125, 55, 114, 228, 241, 15, 110, 116, 153, 42, 31, 109, 244, 219, 199, 164, 12, 159, 150, 205, 145, 10, 54, 152, 209, 199, 34, 40, 200, 239, 175, 85, 216, 35, 122, 32, 201, 47, 255, 224, 13, 19, 222, 24, 61, 239, 106, 177, 161, 123, 38, 249, 161, 102, 183, 89, 233, 134, 15, 224, 97, 67, 62, 72, 164, 142, 238, 77, 64, 126, 163, 180, 249, 206, 242, 88, 0, 22, 166, 125, 196]


@cocotb.test(skip=RTL_ONLY)  # probes user_project.core
async def trial197_oe_lockstep(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    n = len(EXT)
    m = Machine()
    m.enable_trace = True
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    iss = []
    for cy in range(n):
        m.phys_ext = [(EXT[cy] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append(
            (out, oe, m.ctx[0].pc, m.ctx[0].drive_oe, bool(m.trace[-1]["tick0"]))
        )

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
    q = core.u_queue
    for cy in range(n):
        dut.uio_in.value = EXT[min(cy, n - 1)]
        await RisingEdge(dut.clk)
        i = cy
        io, ie, ipc, idoe, itick = iss[i]
        ro, re = rtl_pads(dut)
        rpc = int(core.dbg_pc.value)
        if i <= 10 or ipc != rpc or ie != re or (io & ie) != (ro & re):
            dut._log.info(
                f"cy={i} ISS pc={ipc} tick={int(itick)} RTL pc={rpc} "
                f"ak={int(core.dbg_a_kind.value)} rtick={int(core.dbg_tick.value)} "
                f"trun={int(core.dbg_timer_run.value)} miss={int(core.dbg_miss.value)} "
                f"oe ISS={ie:#04x} RTL={re:#04x}"
            )
        if ie != re or (io & ie) != (ro & re):
            raise AssertionError(f"oe cy={i}")
        if ipc != rpc:
            raise AssertionError(f"pc cy={i} iss={ipc} rtl={rpc}")
