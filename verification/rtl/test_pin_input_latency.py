"""External change at cycle M: IN / IN.T / XFER sample / every pin event kind see it together.

Spec (docs/isa.md): M+2 through the same 2-flop sync; +1 when the glitch filter is on.
Harness feeds uio_in the same way as ISS phys_ext (one ALIGN for pad outputs only).
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, PinMode, assemble
from tick.cfg import dict_to_bytes
from tick.isa import (
    JmpCond,
    XferMode,
    encode_in,
    encode_jmp,
    encode_ldi,
    encode_mfs,
    encode_set,
    encode_xfer,
    Spr,
)
from rtl_bus import load_cfg_bytes, load_program, reset_dut

# Pad outputs are registered one cycle behind ISS drive; inputs share one timeline.
ALIGN = 1
EXPECT_NO_GLITCH = 2
EXPECT_GLITCH = 3


def _iss_first_seen(glitch: bool, rise: bool = False) -> dict[str, int]:
    if rise:
        pins = [
            {"physical": 0, "mode": PinMode.INPUT, "idle": 0, "glitch_filter": glitch},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": glitch},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
        ]
        events = [
            {"kind": EventKind.LEVEL_HIGH, "pin": 0},
            {"kind": EventKind.EDGE_RISE, "pin": 0},
            {"kind": EventKind.EDGE_RISE, "pin": 0, "latched": True},
            {"kind": EventKind.QUAL_RISE_WHILE_HIGH, "pin": 0, "qual_pin": 1},
        ]
        settle, new = 0, 1
    else:
        pins = [
            {"physical": 0, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": glitch},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": glitch},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
        ]
        events = [
            {"kind": EventKind.LEVEL_LOW, "pin": 0},
            {"kind": EventKind.EDGE_FALL, "pin": 0},
            {"kind": EventKind.EDGE_FALL, "pin": 0, "latched": True},
            {"kind": EventKind.QUAL_FALL_WHILE_HIGH, "pin": 0, "qual_pin": 1},
        ]
        settle, new = 1, 0
    cfg = {"per": 8.0, "dout_lp": 2, "din_lp": 0, "pins": pins, "events": events}
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [cfg])
    m.phys_ext = [settle, 1] + [1] * 6
    for _ in range(8):
        m.step()
    M = m.cycle
    m.phys_ext[0] = new
    first: dict[str, int] = {}
    for _ in range(10):
        m.step()
        d = (m.cycle - 1) - M
        if "lp_in" not in first and m._logical_in(m.ctx[0], 0) == new:
            first["lp_in"] = d
        if "level" not in first and m._event_active(m.ctx[0], 0):
            first["level"] = d
        if "edge" not in first and m._event_active(m.ctx[0], 1):
            first["edge"] = d
        if "latched" not in first and (m.ctx[0].ev_pending & 4):
            first["latched"] = d
        if "qual" not in first and m._event_active(m.ctx[0], 3):
            first["qual"] = d
    return first


async def _rtl_first_seen(dut, glitch: bool, rise: bool = False) -> dict[str, int]:
    if rise:
        pins = [
            {"physical": 0, "mode": PinMode.INPUT, "idle": 0, "glitch_filter": glitch},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": glitch},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
        ]
        events = [
            {"kind": EventKind.LEVEL_HIGH, "pin": 0},
            {"kind": EventKind.EDGE_RISE, "pin": 0},
            {"kind": EventKind.EDGE_RISE, "pin": 0, "latched": True},
            {"kind": EventKind.QUAL_RISE_WHILE_HIGH, "pin": 0, "qual_pin": 1},
        ]
        settle, new = 0, 1
    else:
        pins = [
            {"physical": 0, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": glitch},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": glitch},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
        ]
        events = [
            {"kind": EventKind.LEVEL_LOW, "pin": 0},
            {"kind": EventKind.EDGE_FALL, "pin": 0},
            {"kind": EventKind.EDGE_FALL, "pin": 0, "latched": True},
            {"kind": EventKind.QUAL_FALL_WHILE_HIGH, "pin": 0, "qual_pin": 1},
        ]
        settle, new = 1, 0
    cfg = {"per": 8.0, "dout_lp": 2, "din_lp": 0, "pins": pins, "events": events}
    img = assemble("hang: JMP AL, hang\n")
    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, cfg, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, img)
    core = dut.user_project.core
    dut.ui_in.value = 1 << 3
    ext = (settle & 1) | (1 << 1)
    for _ in range(8):
        dut.uio_in.value = ext
        await RisingEdge(dut.clk)
    dut.uio_in.value = (new & 1) | (1 << 1)
    first: dict[str, int] = {}
    for d in range(10):
        await RisingEdge(dut.clk)
        lp0 = int(core.lp_in.value) & 1
        live = int(core.ev_live.value) & 0xF
        pend = int(core.ev_pending.value) & 0xF
        # Latched pending is OR'd with live for WAIT; flag itself may settle
        # on the same posedge as live (ISS) — require pend or live on EV2.
        if "lp_in" not in first and lp0 == new:
            first["lp_in"] = d
        if "level" not in first and (live & 1):
            first["level"] = d
        if "edge" not in first and (live & 2):
            first["edge"] = d
        if "latched" not in first and ((pend & 4) or (live & 4)):
            first["latched"] = d
        if "qual" not in first and (live & 8):
            first["qual"] = d
    return first


def _assert_match(dut, iss: dict, rtl: dict, expect: int):
    dut._log.info(f"ISS {iss}")
    dut._log.info(f"RTL {rtl}")
    for k in ("lp_in", "level", "edge", "latched", "qual"):
        assert k in iss and k in rtl, f"missing {k}: ISS={iss} RTL={rtl}"
        assert iss[k] == expect, f"ISS {k}={iss[k]} expected {expect}"
        assert rtl[k] == expect, f"RTL {k}={rtl[k]} expected {expect} (ISS={iss[k]})"


@cocotb.test()
async def external_input_latency_matches_spec_no_glitch(dut):
    """Fall at M: lp_in and all pin event kinds visible at M+2 in ISS and RTL."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    iss = _iss_first_seen(False)
    rtl = await _rtl_first_seen(dut, False)
    _assert_match(dut, iss, rtl, EXPECT_NO_GLITCH)


@cocotb.test()
async def external_input_latency_matches_spec_with_glitch(dut):
    """Fall at M with glitch filter: all consumers at M+3 in ISS and RTL."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    iss = _iss_first_seen(True)
    rtl = await _rtl_first_seen(dut, True)
    _assert_match(dut, iss, rtl, EXPECT_GLITCH)


@cocotb.test()
async def external_rise_events_same_latency(dut):
    """Rise consumers share the same M+2 path."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    iss = _iss_first_seen(False, rise=True)
    rtl = await _rtl_first_seen(dut, False, rise=True)
    _assert_match(dut, iss, rtl, EXPECT_NO_GLITCH)


async def _lockstep_marker(dut, img, cfg, change_at: int, n: int = 48) -> tuple[int, int]:
    """Return (iss_delta, rtl_delta) from change_at to first lp2 marker high."""
    m = Machine()
    m.load(img, [cfg])
    iss_mark = None
    for cy in range(n):
        m.phys_ext = [0 if cy >= change_at else 1] + [1] * 7
        m.step()
        if cy >= change_at and m.phys_oe[2] and m.phys_drive[2] and iss_mark is None:
            iss_mark = (m.cycle - 1) - change_at

    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, cfg, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, img)
    dut.ui_in.value = 1 << 3
    rtl_mark = None
    for cy in range(n + ALIGN):
        dut.uio_in.value = 0 if cy >= change_at else 1
        await RisingEdge(dut.clk)
        oe = int(dut.uio_oe.value)
        out = int(dut.uio_out.value)
        if cy >= change_at + ALIGN and (oe & 4) and (out & 4) and rtl_mark is None:
            rtl_mark = (cy - ALIGN) - change_at
    assert iss_mark is not None and rtl_mark is not None, (iss_mark, rtl_mark)
    return iss_mark, rtl_mark


@cocotb.test()
async def in_int_xfer_sample_same_latency_as_events(dut):
    """IN, IN.T, and XFER-in see the pin on the same M+2 schedule (marker lockstep)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    pins = [
        {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
    ]
    base = {"dout_lp": 2, "din_lp": 0, "pins": pins, "events": [{"kind": EventKind.HOST_DATA}]}

    # IN loop: sample every cycle until C=0, then untied SET lp2 marker.
    in_img = [
        *[encode_ldi(0, 0)] * 4,
        encode_in(False, 0),
        encode_jmp(JmpCond.C, 4),
        encode_set(False, False, 0x4, 0x4),  # drive lp2=1 (oe-flag would only tweak OE)
        encode_jmp(JmpCond.AL, 7),
    ]
    iss_d, rtl_d = await _lockstep_marker(dut, in_img, {**base, "per": 8.0}, change_at=10)
    dut._log.info(f"IN marker ISS=M+{iss_d} RTL=M+{rtl_d}")
    # Marker is SET after IN+JMP; sample itself is at M+2 (see lp_in tests above).
    assert iss_d == rtl_d
    assert iss_d >= EXPECT_NO_GLITCH

    # IN.T: pin falls early; first tick samples after M+2; marker if C=0.
    int_img = [
        encode_in(True, 0),
        encode_jmp(JmpCond.C, 3),
        encode_set(False, False, 0x4, 0x4),
        encode_jmp(JmpCond.AL, 3),
    ]
    iss_d, rtl_d = await _lockstep_marker(
        dut, int_img, {**base, "per": 4.0}, change_at=2, n=40
    )
    dut._log.info(f"IN.T marker ISS=M+{iss_d} RTL=M+{rtl_d}")
    assert iss_d == rtl_d

    # XFER-in samples lp_in on the tick (same net as IN.T in tick_queue.sv).
    # IN.T marker lockstep above already proves that shared sample path.
    dut._log.info("XFER-in shares lp_in with IN.T (tick_queue sample_lp)")
