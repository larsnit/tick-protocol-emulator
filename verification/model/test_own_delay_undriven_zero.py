"""Own-drive delay tracks map_out: undriven pins shift 0 (match RTL own_d)."""

from tick import EventKind, Machine, MissPolicy, PinMode, TickSource
from tick.isa import encode_set


def test_oe_clear_then_restore_edge_not_early():
    """After SET.E clears OE, re-enable must not invent an early rise in sync."""
    img = [
        encode_set(False, True, 0x1, 0x1),  # OE on
        encode_set(False, True, 0x1, 0x0),  # OE off
        encode_set(False, True, 0x1, 0x1),  # OE on again (idle restore class)
    ]
    cfg = {
        "per": 8.0,
        "tick_source": TickSource.TIMER,
        "miss_policy": MissPolicy.FLAG,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
        ],
        "events": [
            {"kind": EventKind.EDGE_RISE, "pin": 0, "trap": True, "vector": 0},
        ],
    }
    m = Machine()
    m.phys_ext = [0] * 8
    m.load(img, [cfg])
    # Run past OE restore; EDGE_RISE may fire once sync sees 0→1, but not
    # before READBACK_LATENCY after the re-enable instruction.
    edges = []
    for cy in range(12):
        pre = m.ctx[0].pc
        m.step()
        if m.ctx[0].pc == 0 and pre != 0:
            edges.append(cy)
    # First rise visibility: OE re-enable at cy2 → own_d gets 1 next sample →
    # sync depth 2 → edge around cy5+, never at cy2/3.
    assert not any(e < 4 for e in edges), edges
