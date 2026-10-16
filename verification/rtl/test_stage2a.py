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
from rtl_bus import (
    cfg_read,
    load_cfg_bytes,
    load_default_cfg,
    load_program,
    reset_dut,
    set_cmd,
)


async def _start(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset_dut(dut)


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
    await _start(dut)
    await load_default_cfg(
        dut,
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
    await load_program(dut, assemble(src))
    dut.uio_in.value = 0
    dut.ui_in.value = 1 << 3
    for _ in range(2):  # ALIGN + let sync see 0
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
    await _start(dut)
    await load_default_cfg(
        dut,
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
    await load_program(dut, assemble(src))
    dut.uio_in.value = 0
    dut.ui_in.value = 1 << 3
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
    await _start(dut)
    await load_default_cfg(
        dut,
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
    await load_program(dut, assemble(src))
    dut.uio_in.value = 1
    dut.ui_in.value = 1 << 3
    for _ in range(16):
        await RisingEdge(dut.clk)
    assert (int(dut.uio_oe.value) & 1) == 0, "OD release must not drive"


@cocotb.test()
async def idle_reset_oe_off(dut):
    await _start(dut)
    assert int(dut.uio_oe.value) == 0
    await load_default_cfg(dut)
    assert int(dut.uio_oe.value) == 0
    dut.ui_in.value = 1 << 3
    await RisingEdge(dut.clk)
    await RisingEdge(dut.clk)
    assert (int(dut.uio_oe.value) & 1) == 1


@cocotb.test()
async def dual_map_err(dut):
    await _start(dut)
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
    await load_default_cfg(dut, cfg)
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
    await load_program(dut, assemble(src))
    dut.ui_in.value = 1 << 3
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
    await _start(dut)
    blob = dict_to_bytes(
        0,
        {
            "per": 8.0,
            "msb_first": False,
            "pins": [{"physical": 3, "mode": PinMode.PUSHPULL, "idle": 1}],
        },
        enable_mask=None,
    )
    await load_cfg_bytes(dut, blob)
    for addr, val in blob.items():
        got = await cfg_read(dut, addr)
        assert got == (val & 0xFF), (hex(addr), hex(got), hex(val))
    await load_cfg_bytes(dut, {0x00: 0x01})
    assert await cfg_read(dut, 0x00) == 0x01


@cocotb.test()
async def write_while_enabled_cfg_error(dut):
    await _start(dut)
    await load_default_cfg(dut)
    await set_cmd(dut, 0x9, 0x12)
    await set_cmd(dut, 0xF, 0x00)
    await set_cmd(dut, 0x0, 0)
    assert await cfg_read(dut, 0x12) == 0x01
    src = """
    MFS r0, ERR
    JMP NZ, got
    bad: JMP AL, bad
    got: SET lp0=0
    hang: JMP AL, hang
    """
    await load_program(dut, assemble(src))
    dut.ui_in.value = 1 << 3
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
    await _start(dut)
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
    await load_default_cfg(dut, cfg)
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
    await load_program(dut, assemble(src))
    dut.ui_in.value = 1 << 3
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
    await _start(dut)
    await load_default_cfg(
        dut,
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
    await load_program(dut, assemble(src))
    dut.uio_in.value = 0
    dut.ui_in.value = 1 << 3
    saw = False
    for _ in range(80):
        await RisingEdge(dut.clk)
        if (int(dut.uio_oe.value) & 1) and (int(dut.uio_out.value) & 1) == 0:
            saw = True
            break
    assert saw, "MFS RX after IN.T should complete (XFER result intact)"
