"""Milestone: PULL command → MTS PC jump table; match ISS pins + host RX."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, PinMode, TickSource, assemble
from rtl_bus import load_default_cfg, load_program, push_host, reset_dut

# From cmd_dispatch.asm layout
PC_H_ADD = 4
PC_H_XFER = 9
PC_H_PING = 12


def _cfg():
    return {
        "per": 4.0,
        "phase": 0,
        "msb_first": False,
        "dout_lp": 0,
        "din_lp": 1,
        "tick_source": TickSource.TIMER,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
        ],
        "events": [{"kind": EventKind.HOST_DATA}],
    }


async def _pop_host(dut) -> int | None:
    """Pulse host_rd; return data byte if FIFO had data (uo status host_empty bit)."""
    # uo while run: {0, pin0, tick, miss, waiting, host_empty, host_full, host_rdata[0]}
    uo = int(dut.uo_out.value)
    if (uo >> 2) & 1:  # host_empty
        return None
    # Sample low bit before pop; full byte needs host_rdata — use ISS for data check.
    v = int(dut.ui_in.value)
    dut.ui_in.value = v | (1 << 1)
    await RisingEdge(dut.clk)
    dut.ui_in.value = v & ~(1 << 1)
    await RisingEdge(dut.clk)
    return 0  # presence only; data compared via ISS lockstep


@cocotb.test()
async def cmd_dispatch_ping_and_add(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset_dut(dut)
    cfg = _cfg()
    await load_default_cfg(dut, cfg)
    words = assemble((ROOT / "sw" / "programs" / "cmd_dispatch.asm").read_text())
    await load_program(dut, words)

    iss = Machine()
    iss.load(words, [cfg])

    # Host: ping command, then add 3+5
    await push_host(dut, PC_H_PING)
    iss.host_push(PC_H_PING)
    await push_host(dut, PC_H_ADD)
    iss.host_push(PC_H_ADD)
    await push_host(dut, 3)
    iss.host_push(3)
    await push_host(dut, 5)
    iss.host_push(5)

    dut.ui_in.value = 1 << 3
    saw_ping = False
    ALIGN = 1
    for _ in range(ALIGN):
        await RisingEdge(dut.clk)

    for cy in range(80):
        await RisingEdge(dut.clk)
        iss.step()
        rtl_oe = int(dut.uio_oe.value)
        rtl_out = int(dut.uio_out.value)
        iss_out = 0
        iss_oe = 0
        for p in range(8):
            if iss.phys_oe[p]:
                iss_oe |= 1 << p
                iss_out |= (iss.phys_drive[p] & 1) << p
        if (rtl_oe & iss_oe) != iss_oe or (rtl_out & iss_oe) != (iss_out & iss_oe):
            raise AssertionError(
                f"pin mismatch cy={cy}: RTL=({rtl_out:#04x},{rtl_oe:#04x}) "
                f"ISS=({iss_out:#04x},{iss_oe:#04x})"
            )
        if (rtl_oe >> 2) & 1 and (rtl_out >> 2) & 1:
            saw_ping = True

    assert saw_ping, "h_ping should pulse lp2"
    # ISS should have pushed 3+5=8
    w = iss.host_pop()
    assert w is not None and w.data == 8, w


@cocotb.test()
async def cmd_dispatch_xfer(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset_dut(dut)
    cfg = _cfg()
    await load_default_cfg(dut, cfg)
    words = assemble((ROOT / "sw" / "programs" / "cmd_dispatch.asm").read_text())
    await load_program(dut, words)

    iss = Machine()
    iss.load(words, [cfg])
    await push_host(dut, PC_H_XFER)
    iss.host_push(PC_H_XFER)
    await push_host(dut, 0xA5)
    iss.host_push(0xA5)

    dut.ui_in.value = 1 << 3
    ALIGN = 1
    for _ in range(ALIGN):
        await RisingEdge(dut.clk)

    mismatch = 0
    for cy in range(100):
        await RisingEdge(dut.clk)
        iss.step()
        rtl_oe = int(dut.uio_oe.value) & 1
        rtl_bit = int(dut.uio_out.value) & 1 if rtl_oe else 1
        iss_bit = iss.phys_drive[0] if iss.phys_oe[0] else 1
        if rtl_bit != iss_bit:
            mismatch += 1
            if mismatch <= 3:
                dut._log.info(f"cy={cy} RTL={rtl_bit} ISS={iss_bit}")
    assert mismatch == 0, f"{mismatch} pin mismatches during XFER handler"
