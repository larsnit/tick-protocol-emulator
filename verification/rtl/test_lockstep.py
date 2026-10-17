"""Cycle-level ISS ↔ RTL lockstep for the single-context subset (pin + status)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, PinMode, TickSource, assemble
from rtl_bus import load_default_cfg, load_program, push_host, reset_dut

LOCKSTEP_DELTA = 1


def _iss_cfg(per: float = 8.0):
    return {
        "per": per,
        "phase": 0,
        "msb_first": False,
        "tick_source": TickSource.TIMER,
        "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
        "events": [{"kind": EventKind.HOST_DATA}],
    }


@cocotb.test(skip=os.environ.get("GATES") == "yes")
async def lockstep_uart_tx(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset_dut(dut)
    cfg = _iss_cfg(8.0)
    await load_default_cfg(dut, cfg)

    words = assemble((ROOT / "sw" / "programs" / "uart_tx.asm").read_text())
    await load_program(dut, words)
    await push_host(dut, 0x55, last=True)

    iss = Machine()
    iss.load(words, [cfg])
    iss.host_push(0x55, last=True)

    dut.ui_in.value = 1 << 3

    for _ in range(LOCKSTEP_DELTA):
        await RisingEdge(dut.clk)

    for cy in range(120):
        await RisingEdge(dut.clk)
        iss.step()

        rtl_pin = int(dut.uio_out.value) & 1 if int(dut.uio_oe.value) & 1 else 1
        iss_pin = iss.phys_drive[0] if iss.phys_oe[0] else 1
        uo = int(dut.uo_out.value)
        rtl_miss = (uo >> 4) & 1
        rtl_wait = (uo >> 3) & 1
        iss_miss = int(iss.ctx[0].miss)
        iss_wait = int(iss.ctx[0].waiting)

        if (rtl_pin, rtl_miss, rtl_wait) != (iss_pin, iss_miss, iss_wait):
            raise AssertionError(
                f"mismatch cy={cy + LOCKSTEP_DELTA}: "
                f"RTL pin={rtl_pin} miss={rtl_miss} wait={rtl_wait} | "
                f"ISS pin={iss_pin} miss={iss_miss} wait={iss_wait}"
            )
