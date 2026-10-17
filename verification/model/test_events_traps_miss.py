"""ISS: stretch clock-only, trap pending clear, trap priority (Stage 2c decisions)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, MissPolicy, PinMode, assemble
from tick.iss import EventKind as EK


def test_miss_stretch_holds_only_clock_pin_low():
    """Stretch must OD-drive only CLK_LP low; other OD pins stay released (2026-10-17)."""
    m = Machine()
    m.load(
        assemble(
            """
            SET.T lp0=1
            hang: JMP AL, hang
            """
        ),
        [
            {
                "per": 4.0,
                "clk_lp": 2,
                "dout_lp": 0,
                "miss_policy": MissPolicy.STRETCH,
                "pins": [
                    {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1},
                    {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
                    {"physical": 2, "mode": PinMode.OPENDRAIN, "idle": 1},
                    {"physical": 3, "mode": PinMode.OPENDRAIN, "idle": 1},
                ],
            }
        ],
    )
    # Run until first MISS (tick with empty queue after SET.T completes).
    for _ in range(20):
        m.step()
        if m.ctx[0].stretching:
            break
    assert m.ctx[0].stretching
    c = m.ctx[0]
    # CLK_LP=2 held low by stretch; LP3 (OD, never written) must remain released.
    assert (c.drive_oe & (1 << 2)) and ((c.drive_val >> 2) & 1) == 0
    assert (c.drive_oe & (1 << 3)) == 0
    # LP0 may still be driven by SET.T=1 (released OD); stretch must not force it low.
    assert not ((c.drive_oe & (1 << 0)) and ((c.drive_val >> 0) & 1) == 0)


def test_miss_stretch_ends_when_timed_job_consumed():
    """Stretch must clear (and release CLK_LP) when IN.T is ticked after a MISS stretch (2026-10-17)."""
    m = Machine()
    # SET.T then a long r1-- drain so the queue stays empty (MISS stretch) before IN.T.
    m.load(
        assemble(
            """
            SET.T lp0=1
            LDI   r1, 30
            drain: JMP r1--, drain
            IN.T  lp1
            hang: JMP AL, hang
            """
        ),
        [
            {
                "per": 4.0,
                "clk_lp": 2,
                "dout_lp": 0,
                "miss_policy": MissPolicy.STRETCH,
                "pins": [
                    {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1},
                    {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
                    {"physical": 2, "mode": PinMode.OPENDRAIN, "idle": 1},
                    {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
                ],
            }
        ],
    )
    saw_stretch = False
    saw_in_posted = False
    for _ in range(200):
        m.step()
        c = m.ctx[0]
        if c.stretching:
            saw_stretch = True
        act = c.timed_active
        if act is not None and act.kind == "in":
            saw_in_posted = True
            # After the tick that consumes IN.T, stretch must already be clear.
            # (Same-cycle observe: waiting cleared, IN.T promoted away.)
        if saw_stretch and saw_in_posted and act is None and not c.waiting:
            assert not c.stretching, "IN.T consume must end stretch before next miss"
            assert (c.drive_oe & (1 << 2)) == 0
            break
    else:
        pytest.fail("never saw stretch then IN.T completion")
    assert saw_stretch and saw_in_posted


def test_event_trap_clears_only_winning_pending():
    """Event trap clears only that event's latched pending; others stay (2026-10-17)."""
    m = Machine()
    m.load(
        assemble("hang: JMP AL, hang\n"),
        [
            {
                "per": 8.0,
                "pins": [
                    {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
                    {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
                ],
                "events": [
                    {
                        "kind": EventKind.EDGE_FALL,
                        "pin": 0,
                        "latched": True,
                        "trap": True,
                        "vector": 0,
                    },
                    {
                        "kind": EventKind.EDGE_FALL,
                        "pin": 1,
                        "latched": True,
                        "trap": False,
                        "vector": 0,
                    },
                ],
            }
        ],
    )
    # Settle sync high, then fall both pins → both pending; EV0 traps.
    m.phys_ext = [1, 1, 1, 1, 1, 1, 1, 1]
    for _ in range(4):
        m.step()
    m.phys_ext = [0, 0, 1, 1, 1, 1, 1, 1]
    for _ in range(4):
        m.step()
        if m.ctx[0].evf & 1:
            break
    assert m.ctx[0].evf & 0x01
    # EV0 pending cleared by its trap; EV1 pending must remain.
    assert (m.ctx[0].ev_pending & 0x1) == 0
    assert (m.ctx[0].ev_pending & 0x2) != 0


def test_miss_trap_clears_no_pending():
    """MISS trap must not clear latched pending flags (2026-10-17)."""
    m = Machine()
    m.load(
        assemble(
            """
            SET.T lp0=1
            hang: JMP AL, hang
            trapv: JMP AL, trapv
            """
        ),
        [
            {
                "per": 4.0,
                "miss_policy": MissPolicy.TRAP,
                "miss_vector": 2,
                "pins": [
                    {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1},
                    {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
                ],
                "events": [
                    {
                        "kind": EventKind.EDGE_FALL,
                        "pin": 1,
                        "latched": True,
                        "trap": False,
                    }
                ],
            }
        ],
    )
    m.phys_ext = [1] * 8
    for _ in range(4):
        m.step()
    m.phys_ext = [1, 0] + [1] * 6
    for _ in range(4):
        m.step()
    assert m.ctx[0].ev_pending & 1
    # Drain SET.T then hit empty-queue MISS → trap to vector 2.
    for _ in range(40):
        m.step()
        if m.ctx[0].pc == 2:
            break
    assert m.ctx[0].pc == 2
    assert m.ctx[0].ev_pending & 1


def test_same_cycle_event_traps_lower_index_wins():
    """Two live trap edges same cycle: lower event index wins; EVF = that bit."""
    m = Machine()
    m.load(
        assemble("hang: JMP AL, hang\nv1: JMP AL, v1\nv2: JMP AL, v2\n"),
        [
            {
                "per": 8.0,
                "pins": [
                    {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
                    {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
                ],
                "events": [
                    {
                        "kind": EventKind.EDGE_FALL,
                        "pin": 0,
                        "trap": True,
                        "vector": 1,
                    },
                    {
                        "kind": EventKind.EDGE_FALL,
                        "pin": 1,
                        "trap": True,
                        "vector": 2,
                    },
                ],
            }
        ],
    )
    m.phys_ext = [1, 1, 1, 1, 1, 1, 1, 1]
    for _ in range(4):
        m.step()
    m.phys_ext = [0, 0, 1, 1, 1, 1, 1, 1]
    for _ in range(4):
        m.step()
        if m.ctx[0].pc == 1:
            break
    assert m.ctx[0].pc == 1
    assert m.ctx[0].evf == 0x01


def test_assembler_rejects_tick_wait_with_rearm_or_idle():
    with pytest.raises(ValueError, match="[Tt]ick"):
        assemble("WAIT tick, rearm\nhang: JMP AL, hang\n")
    with pytest.raises(ValueError, match="[Tt]ick"):
        assemble("WAIT tick, idle\nhang: JMP AL, hang\n")
