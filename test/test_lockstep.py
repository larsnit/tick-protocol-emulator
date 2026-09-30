"""W5: cycle-level ISS ↔ RTL lockstep for the single-context subset."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import EventKind, Machine, PinMode, TickSource, assemble
from test import load_program, push_host, set_cmd

# RTL needs one rising edge after `run` is driven before the first issue.
# ISS step 0 lines up with that first issuing edge.
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


@cocotb.test()
async def lockstep_uart_tx(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

    words = assemble((ROOT / "programs" / "uart_tx.asm").read_text())
    await load_program(dut, words)
    await push_host(dut, 0x55, last=True)

    iss = Machine()
    iss.load(words, [_iss_cfg(8.0)])
    iss.host_push(0x55, last=True)

    dut.ui_in.value = 1 << 3  # run
    core = dut.user_project.core

    # Align: first rising edge after run may be needed for RTL to sample run.
    # ISS step N corresponds to RTL after (N + LOCKSTEP_DELTA) run cycles.
    for _ in range(LOCKSTEP_DELTA):
        await RisingEdge(dut.clk)

    for cy in range(120):
        await RisingEdge(dut.clk)
        iss.step()

        rtl_pc = int(core.pc.value)
        iss_pc = iss.ctx[0].pc
        rtl_pin = int(dut.uio_out.value) & 1 if int(dut.uio_oe.value) & 1 else 1
        iss_pin = iss.phys_drive[0] if iss.phys_oe[0] else 1
        rtl_miss = int(core.miss.value)
        iss_miss = int(iss.ctx[0].miss)
        rtl_wait = int(core.waiting.value)
        iss_wait = int(iss.ctx[0].waiting)
        rtl_ak = int(core.a_kind.value)
        ta = iss.ctx[0].timed_active
        if ta is None:
            iss_ak = 0
        elif ta.kind == "set":
            iss_ak = 1
        elif ta.kind == "xfer":
            iss_ak = 2
        elif ta.kind == "wait":
            iss_ak = 3
        else:
            iss_ak = 2  # in.t maps near xfer for subset

        if (rtl_pc, rtl_pin, rtl_miss, rtl_wait, rtl_ak) != (
            iss_pc,
            iss_pin,
            iss_miss,
            iss_wait,
            iss_ak,
        ):
            raise AssertionError(
                f"mismatch cy={cy + LOCKSTEP_DELTA}: "
                f"RTL pc={rtl_pc} pin={rtl_pin} miss={rtl_miss} wait={rtl_wait} ak={rtl_ak} | "
                f"ISS pc={iss_pc} pin={iss_pin} miss={iss_miss} wait={iss_wait} ak={iss_ak}"
            )
