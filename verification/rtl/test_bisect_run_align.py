"""Bisect mts_ecfg + IN marker vs ISS."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, PinMode, TickSource
from tick.cfg import dict_to_bytes
from tick.isa import JmpCond, Spr, XferMode, encode_jmp, encode_ldi, encode_mts, encode_xfer
from tick.host_link import HostLink
from rtl_only import RTL_ONLY
from lockstep_harness import _uo_run, rtl_pads, start_run

IMG = [
    encode_ldi(1, 0x0F),
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
        {"physical": 4, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 2, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 1, "mode": PinMode.PUSHPULL, "idle": 1},
        {"physical": 6, "mode": PinMode.INPUT, "idle": 0},
    ],
    "events": [{"kind": EventKind.HOST_DATA} for _ in range(4)],
}


@cocotb.test(skip=RTL_ONLY)  # probes user_project.core
async def bisect_mts(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    m = Machine()
    m.load(IMG, [CFG])
    m.host_push(0, last=False, cmd=True)
    iss = []
    for cy in range(16):
        m.phys_ext = [0] * 8
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((m.ctx[0].pc, out, oe, int(m.ctx[0].timer_running)))

    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, CFG, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(IMG)
    await host.push(0, last=False, cmd=True)
    dut.uio_in.value = 0
    await start_run(host, dut)
    core = dut.user_project.core
    for cy in range(16):
        await FallingEdge(dut.clk)
        dut.uio_in.value = 0
        await RisingEdge(dut.clk)
        out, oe = rtl_pads(dut)
        pc = int(core.dbg_pc.value)
        tr = int(core.dbg_timer_run.value)
        tick = int(core.dbg_tick.value)
        ip, io, ie, it = iss[cy]
        dut._log.info(
            f"cy={cy:02d} RTL pc={pc} out={out:02x} oe={oe:02x} tr={tr} tick={tick} | "
            f"ISS pc={ip} out={io:02x} oe={ie:02x} tr={it}"
        )
