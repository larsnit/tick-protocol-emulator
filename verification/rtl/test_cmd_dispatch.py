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
from tick.host_link import HostLink
from lockstep_harness import start_run, rtl_pads

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


async def _pop_host(host: HostLink) -> int | None:
    """Pop via HostLink; return 0 if data present (presence-only; ISS checks values)."""
    got = await host.pull()
    if got is None:
        return None
    return 0


@cocotb.test()
async def cmd_dispatch_ping_and_add(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    host = HostLink(dut)
    await host.reset()
    cfg = _cfg()
    await host.load_default_cfg( cfg)
    words = assemble((ROOT / "sw" / "programs" / "cmd_dispatch.asm").read_text())
    await host.load_program(words)

    iss = Machine()
    iss.load(words, [cfg])

    # Host: ping command, then add 3+5
    await host.push(PC_H_PING)
    iss.host_push(PC_H_PING)
    await host.push(PC_H_ADD)
    iss.host_push(PC_H_ADD)
    await host.push(3)
    iss.host_push(3)
    await host.push(5)
    iss.host_push(5)

    dut.uio_in.value = 0
    await start_run(host, dut, iss)
    saw_ping = False

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
    host = HostLink(dut)
    await host.reset()
    cfg = _cfg()
    await host.load_default_cfg( cfg)
    words = assemble((ROOT / "sw" / "programs" / "cmd_dispatch.asm").read_text())
    await host.load_program(words)

    iss = Machine()
    iss.load(words, [cfg])
    await host.push(PC_H_XFER)
    iss.host_push(PC_H_XFER)
    await host.push(0xA5)
    iss.host_push(0xA5)

    dut.uio_in.value = 0
    await start_run(host, dut, iss)

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
