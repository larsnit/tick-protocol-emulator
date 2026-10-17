"""Enabling a context must not fire EDGE_* from sync settling to idle (2026-10-17).

Symptom: ISS traps on EDGE_FALL at cy=4 with no external change; RTL never sees the
edge (sync already at idle before RUN). Root cause: ISS sync flops reset to 1 then
track PP idle=0 after enable, without the RUN-rise snap/clear that RTL applies.
"""

from __future__ import annotations

from tick import EventKind, Machine, PinMode, assemble


def test_enable_does_not_trap_on_idle_settle_edge():
    """PP idle=0 must not produce a latched/trap EDGE_FALL just after enable."""
    cfg = {
        "per": 8.0,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": True},
        ],
        "events": [
            {
                "kind": EventKind.EDGE_FALL,
                "pin": 0,
                "latched": True,
                "trap": True,
                "vector": 2,
            },
        ],
    }
    img = assemble(
        "start: JMP AL, start\nnop1: JMP AL, nop1\nhandler: JMP AL, handler\n"
    )
    m = Machine()
    m.load(img, [cfg])
    # Hold external high; own idle drive is 0 — the dangerous settle path.
    m.phys_ext = [1] * 8
    for _ in range(16):
        m.step()
        assert m.ctx[0].pc == 0, (
            f"phantom trap to pc={m.ctx[0].pc} pending={m.ctx[0].ev_pending:#x} "
            f"evf={m.ctx[0].evf:#x}"
        )
        assert m.ctx[0].ev_pending == 0
        assert m.ctx[0].evf == 0
