"""External pin change at cycle M: every input consumer sees it at M+2 (M+3 with glitch)."""

from __future__ import annotations

from tick import EventKind, Machine, PinMode, assemble
from tick.isa import READBACK_LATENCY


def _settle_and_fall(glitch: bool) -> tuple[Machine, int]:
    cfg = {
        "per": 8.0,
        "dout_lp": 2,
        "din_lp": 0,
        "pins": [
            {"physical": 0, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": glitch},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": glitch},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
        ],
        "events": [
            {"kind": EventKind.LEVEL_LOW, "pin": 0},
            {"kind": EventKind.LEVEL_HIGH, "pin": 0},
            {"kind": EventKind.EDGE_FALL, "pin": 0},
            {"kind": EventKind.EDGE_RISE, "pin": 0},
            # replaced below — only 4 selectors; rebuild per check
        ],
    }
    # Four selectors covering level/edge/qualified/latched edge.
    cfg["events"] = [
        {"kind": EventKind.LEVEL_LOW, "pin": 0},
        {"kind": EventKind.EDGE_FALL, "pin": 0},
        {"kind": EventKind.EDGE_FALL, "pin": 0, "latched": True},
        {"kind": EventKind.QUAL_FALL_WHILE_HIGH, "pin": 0, "qual_pin": 1},
    ]
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [cfg])
    m.phys_ext = [1] * 8
    for _ in range(6):
        m.step()
    M = m.cycle
    m.phys_ext[0] = 0  # fall during cycle M; pin1 stays high for qualified
    return m, M


def _first_deltas(glitch: bool) -> dict[str, int]:
    m, M = _settle_and_fall(glitch)
    first: dict[str, int] = {}
    for _ in range(8):
        m.step()
        d = (m.cycle - 1) - M
        if "IN" not in first and m._logical_in(m.ctx[0], 0) == 0:
            first["IN"] = d
        if "LEVEL_LOW" not in first and m._event_active(m.ctx[0], 0):
            first["LEVEL_LOW"] = d
        if "EDGE_FALL" not in first and m._event_active(m.ctx[0], 1):
            first["EDGE_FALL"] = d
        if "LATCHED_PEND" not in first and (m.ctx[0].ev_pending & (1 << 2)):
            first["LATCHED_PEND"] = d
        if "QUAL_FALL" not in first and m._event_active(m.ctx[0], 3):
            first["QUAL_FALL"] = d
    return first


def test_external_fall_visible_m_plus_2_no_glitch():
    """All pin consumers see an external change at M+2 with the glitch filter off."""
    assert READBACK_LATENCY == 3
    expect = 2
    got = _first_deltas(False)
    for name, d in got.items():
        assert d == expect, f"{name}: visible at M+{d}, expected M+{expect}"


def test_external_fall_visible_m_plus_3_with_glitch():
    """Glitch filter (3-sample majority after sync) adds one cycle → M+3."""
    expect = 3
    got = _first_deltas(True)
    for name, d in got.items():
        assert d == expect, f"{name}: visible at M+{d}, expected M+{expect}"


def test_level_high_and_edge_rise_same_path():
    """Rise consumers share the same M+2 path as fall/IN."""
    cfg = {
        "pins": [
            {"physical": 0, "mode": PinMode.INPUT, "idle": 0},
        ],
        "events": [
            {"kind": EventKind.LEVEL_HIGH, "pin": 0},
            {"kind": EventKind.EDGE_RISE, "pin": 0},
            {"kind": EventKind.EDGE_RISE, "pin": 0, "latched": True},
            {"kind": EventKind.QUAL_RISE_WHILE_HIGH, "pin": 0, "qual_pin": 0},
        ],
    }
    # qual_pin == pin: rise-while-high on same pin is vacuous for qual high-after-rise;
    # use pin1 as qual held high instead.
    cfg["pins"].append({"physical": 1, "mode": PinMode.INPUT, "idle": 1})
    cfg["events"][3] = {
        "kind": EventKind.QUAL_RISE_WHILE_HIGH,
        "pin": 0,
        "qual_pin": 1,
    }
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [cfg])
    m.phys_ext = [0, 1] + [1] * 6
    for _ in range(6):
        m.step()
    M = m.cycle
    m.phys_ext[0] = 1
    first: dict[str, int] = {}
    for _ in range(6):
        m.step()
        d = (m.cycle - 1) - M
        if "IN" not in first and m._logical_in(m.ctx[0], 0) == 1:
            first["IN"] = d
        if "LEVEL_HIGH" not in first and m._event_active(m.ctx[0], 0):
            first["LEVEL_HIGH"] = d
        if "EDGE_RISE" not in first and m._event_active(m.ctx[0], 1):
            first["EDGE_RISE"] = d
        if "LATCHED" not in first and (m.ctx[0].ev_pending & 4):
            first["LATCHED"] = d
        if "QUAL_RISE" not in first and m._event_active(m.ctx[0], 3):
            first["QUAL_RISE"] = d
    for name, d in first.items():
        assert d == 2, f"{name}: M+{d}, expected M+2"
