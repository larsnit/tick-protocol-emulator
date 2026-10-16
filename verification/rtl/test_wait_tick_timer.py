"""Tick-WAIT must not restart a running timer (path-independent first edge)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import Machine, PinMode, TickSource, assemble
from test_uart_tx import load_program

K_VALUES = (0, 1, 3, 5)


def _cfg():
    return [
        {
            "per": 8.0,
            "phase": 0,
            "msb_first": False,
            "tick_source": TickSource.TIMER,
            "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
        }
    ]


def _src(k: int) -> str:
    nops = "\n".join(["ALU MOV r0, r0"] * k)
    return f"SET.T tx=0\n{nops}\nWAIT tick\nSET.T tx=1\nhang: JMP AL, hang\n"


def iss_first_edge(k: int) -> int:
    m = Machine()
    m.load(assemble(_src(k)), _cfg())
    prev = None
    for cy in range(80):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else 1
        if prev is not None and cur != prev:
            return cy
        prev = cur
    raise AssertionError(f"ISS: no edge for k={k}")


async def rtl_first_edge(dut, k: int) -> int:
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)
    await load_program(dut, assemble(_src(k)))
    dut.ui_in.value = 1 << 3
    prev = None
    for cy in range(80):
        await RisingEdge(dut.clk)
        pin = int(dut.uio_out.value) & 1
        oe = int(dut.uio_oe.value) & 1
        cur = pin if oe else 1
        if prev is not None and cur != prev:
            return cy
        prev = cur
    raise AssertionError(f"RTL: no edge for k={k}")


@cocotb.test()
async def wait_tick_timer_guard(dut):
    """SET.T; k×NOP; WAIT tick; SET.T — first edge matches ISS for every k."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    iss_edges = {k: iss_first_edge(k) for k in K_VALUES}
    # Path-independence on the ISS itself.
    assert len(set(iss_edges.values())) == 1, iss_edges
    ref = next(iter(iss_edges.values()))

    rtl_edges = {}
    for k in K_VALUES:
        rtl_edges[k] = await rtl_first_edge(dut, k)
        dut._log.info(f"k={k} ISS={iss_edges[k]} RTL={rtl_edges[k]}")

    assert len(set(rtl_edges.values())) == 1, (
        f"RTL first edge moved with padding: {rtl_edges} (ISS stays at {ref})"
    )
    # Align ISS→RTL: cocotb RisingEdge after run is +1 vs ISS step index.
    assert rtl_edges[0] == ref + 1, (rtl_edges, ref)
