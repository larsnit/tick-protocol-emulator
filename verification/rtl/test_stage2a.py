"""Directed Stage 2a tests: sync latency, OD, OE, dual-map, cfg, IN.T."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import Machine, PinMode, assemble
from tick.cfg import dict_to_bytes
from tick.host_link import HostLink
from lockstep_harness import start_run, rtl_pads


async def _start(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    host = HostLink(dut)
    await host.reset()
    return host


def _iss_own_latency_ok() -> bool:
    """SET; 2×NOP; IN should see own drive (READBACK_LATENCY=3)."""
    m = Machine()
    m.load(
        assemble(
            """
            SET lp0=1
            LDI r0, 0
            LDI r0, 0
            IN lp0
            JMP C, ok
            SET lp0=0
            bad: JMP AL, bad
            ok: JMP AL, ok
            """
        ),
        [
            {
                "per": 8.0,
                "msb_first": False,
                "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0}],
            }
        ],
    )
    for _ in range(12):
        m.step()
    return bool(m.ctx[0].c) and (m.phys_drive[0] == 1)


@cocotb.test()
async def readback_latency_external_2(dut):
    """External pin change during cycle M is visible to IN in cycle M+2."""
    host = await _start(dut)
    await host.load_default_cfg(
        {
            "per": 8.0,
            "msb_first": False,
            "pins": [
                {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
                {"physical": 1, "mode": PinMode.PUSHPULL, "idle": 0},
                {"physical": 2, "mode": PinMode.INPUT, "idle": 1},
                {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
            ],
        },
    )
    # Settle sync on 0, then raise; two LDI so IN is 2 cycles after the rise edge.
    src = """
    LDI r0, 0
    LDI r0, 0
    LDI r0, 0
    LDI r0, 0
    IN lp0
    JMP C, saw1
    SET lp1=0
    hang0: JMP AL, hang0
    saw1: SET lp1=1
    hang1: JMP AL, hang1
    """
    await host.load_program(assemble(src))
    dut.uio_in.value = 0
    await start_run(host, dut)
    # let sync see 0 one execute cycle before raising pin
    await RisingEdge(dut.clk)
    dut.uio_in.value = 1  # rise at M; IN two instr later → M+2
    saw = False
    for _ in range(20):
        await RisingEdge(dut.clk)
        if (int(dut.uio_oe.value) >> 1) & 1 and (int(dut.uio_out.value) >> 1) & 1:
            saw = True
            break
    assert saw, "IN should see external 1 after 2-cycle sync"


@cocotb.test()
async def readback_latency_own_3(dut):
    """Own drive from SET in cycle N is first visible to IN in cycle N+3."""
    assert _iss_own_latency_ok(), "ISS reference for own latency broken"
    host = await _start(dut)
    await host.load_default_cfg(
        {
            "per": 8.0,
            "msb_first": False,
            "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0}],
        },
    )
    src = """
    SET lp0=1
    LDI r0, 0
    LDI r0, 0
    IN lp0
    JMP C, ok
    SET lp0=0
    bad: JMP AL, bad
    ok: JMP AL, ok
    """
    await host.load_program(assemble(src))
    dut.uio_in.value = 0
    await start_run(host, dut)
    pin_trace = []
    for _ in range(20):
        await RisingEdge(dut.clk)
        oe = int(dut.uio_oe.value) & 1
        pin = int(dut.uio_out.value) & 1
        pin_trace.append(pin if oe else 0)
    assert pin_trace[-1] == 1, pin_trace
    assert 0 not in pin_trace[4:], pin_trace


@cocotb.test()
async def opendrain_release_reads_1(dut):
    host = await _start(dut)
    await host.load_default_cfg(
        {
            "per": 8.0,
            "msb_first": False,
            "pins": [{"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1}],
        },
    )
    src = """
    SET lp0=1
    LDI r0, 0
    LDI r0, 0
    IN lp0
    JMP C, ok
    bad: JMP AL, bad
    ok: JMP AL, ok
    """
    await host.load_program(assemble(src))
    dut.uio_in.value = 1
    await start_run(host, dut)
    for _ in range(16):
        await RisingEdge(dut.clk)
    assert (int(dut.uio_oe.value) & 1) == 0, "OD release must not drive"


@cocotb.test()
async def idle_reset_oe_off(dut):
    host = await _start(dut)
    assert int(dut.uio_oe.value) == 0
    await host.load_default_cfg()
    assert int(dut.uio_oe.value) == 0
    dut.uio_in.value = 0
    await start_run(host, dut)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    assert (int(dut.uio_oe.value) & 1) == 1


@cocotb.test()
async def dual_map_err(dut):
    host = await _start(dut)
    cfg = {
        "per": 8.0,
        "msb_first": False,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1},
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
        ],
    }
    await host.load_default_cfg( cfg)
    # err_map_set is registered → sticky MAP one cycle later; burn 2 cycles.
    src = """
    LDI r0, 0
    LDI r0, 0
    MFS r0, ERR
    JMP NZ, got
    bad: JMP AL, bad
    got: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    dut.uio_in.value = 0
    await start_run(host, dut)
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    oe = int(dut.uio_oe.value)
    out = int(dut.uio_out.value)
    assert (oe & 1) and (out & 1) == 1, (oe, out)
    saw = False
    for _ in range(24):
        await RisingEdge(dut.clk)
        if (int(dut.uio_oe.value) >> 2) & 1 and (int(dut.uio_out.value) >> 2) & 1:
            saw = True
            break
    assert saw, "ERR.MAP should be visible via MFS ERR"


@cocotb.test()
async def config_readback_roundtrip(dut):
    host = await _start(dut)
    blob = dict_to_bytes(
        0,
        {
            "per": 8.0,
            "msb_first": False,
            "pins": [{"physical": 3, "mode": PinMode.PUSHPULL, "idle": 1}],
        },
        enable_mask=None,
    )
    await host.cfg_write_map(blob)
    for addr, val in blob.items():
        got = await host.cfg_read(addr)
        assert got == (val & 0xFF), (hex(addr), hex(got), hex(val))
    await host.cfg_write_map({0x00: 0x01})
    assert await host.cfg_read(0x00) == 0x01


@cocotb.test()
async def write_while_enabled_cfg_error(dut):
    host = await _start(dut)
    await host.load_default_cfg()
    await host.cfg_write(0x12, 0x00)  # while ENABLE: sticky ERR.CFG, write ignored
    assert await host.cfg_read(0x12) == 0x01
    src = """
    MFS r0, ERR
    JMP NZ, got
    bad: JMP AL, bad
    got: SET lp0=0
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    dut.uio_in.value = 0
    await start_run(host, dut)
    saw_low = False
    for _ in range(24):
        await RisingEdge(dut.clk)
        if (int(dut.uio_oe.value) & 1) and (int(dut.uio_out.value) & 1) == 0:
            saw_low = True
            break
    assert saw_low, "ERR.CFG sticky after write while enabled"


@cocotb.test()
async def jmp_err_on_map(dut):
    """JMP ERR takes when ERR.MAP is set (pin-only; gate-level safe)."""
    host = await _start(dut)
    cfg = {
        "per": 8.0,
        "msb_first": False,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1},
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
        ],
    }
    await host.load_default_cfg( cfg)
    # Dual-map sticky is registered; burn 2 cycles so ERR.MAP is live for JMP.
    src = """
    LDI r0, 0
    LDI r0, 0
    JMP ERR, got
    bad: SET lp2=1
    hang: JMP AL, hang
    got: SET lp0=0
    hang2: JMP AL, hang2
    """
    await host.load_program(assemble(src))
    dut.uio_in.value = 0
    await start_run(host, dut)
    saw = False
    for _ in range(24):
        await RisingEdge(dut.clk)
        oe = int(dut.uio_oe.value)
        out = int(dut.uio_out.value)
        if (oe & 1) and (out & 1) == 0:
            saw = True
            break
    assert saw, "JMP ERR must take on ERR.MAP"


@cocotb.test()
async def in_t_with_xfer_pending_result_unchanged(dut):
    """IN.T must not set res_valid; XFER result remains available to MFS RX."""
    host = await _start(dut)
    await host.load_default_cfg(
        {
            "per": 8.0,
            "msb_first": False,
            "dout_lp": 0,
            "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
        },
    )
    src = """
    LDI r0, 0xA5
    XFER r0, 1, out
    IN.T lp0
    MFS r1, RX
    SET lp0=0
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    dut.uio_in.value = 0
    await start_run(host, dut)
    saw = False
    for _ in range(80):
        await RisingEdge(dut.clk)
        if (int(dut.uio_oe.value) & 1) and (int(dut.uio_out.value) & 1) == 0:
            saw = True
            break
    assert saw, "MFS RX after IN.T should complete (XFER result intact)"
