"""WAIT ev|tick: same-cycle event and tick → both EVF bits, tick consumed, no MISS."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, PinMode, assemble


def test_wait_event_and_tick_same_cycle_both_evf_no_miss():
    """Event and tick same cycle: EVF has both bits, tick consumed, no MISS (2026-10-17)."""
    # EDGE_FALL delayed through the 2-flop sync so the live edge lands on the
    # first timer tick after WAIT posts (PER=4; drop phys at cycle 2).
    m = Machine()
    m.load(
        assemble(
            """
            WAIT  ev0|tick, stop
            LDI   r0, 0x5A
            PUSH  r0, DATA
            hang: JMP AL, hang
            """
        ),
        [
            {
                "per": 4.0,
                "pins": [{"physical": 0, "mode": PinMode.INPUT, "idle": 1}],
                "events": [{"kind": EventKind.EDGE_FALL, "pin": 0}],
            }
        ],
    )
    m.phys_ext = [1] * 8
    for cy in range(20):
        if cy == 2:
            m.phys_ext[0] = 0
        m.step()
        if m.core_to_host:
            break
    assert m.ctx[0].evf & 0x01, f"EVF missing EV0: {m.ctx[0].evf:#x}"
    assert m.ctx[0].evf & 0x10, f"EVF missing TICK: {m.ctx[0].evf:#x}"
    assert not m.ctx[0].miss
    w = m.host_pop()
    assert w is not None and w.data == 0x5A
