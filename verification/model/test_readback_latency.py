"""Read-back latency: 2-flop sync on inputs; own outputs visible at N+READBACK_LATENCY."""

from __future__ import annotations

from tick import Machine, PinMode, assemble
from tick.isa import READBACK_LATENCY


def _cfg_out():
    return {
        "per": 8.0,
        "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
    }


def _cfg_in():
    return {
        "pins": [{"physical": 0, "mode": PinMode.INPUT, "idle": 0}],
    }


def test_own_output_visible_at_readback_latency():
    """SET in cycle N: first IN that sees the new level is in cycle N+READBACK_LATENCY."""
    assert READBACK_LATENCY == 3
    # SET once, then a chain of IN; first JMP C to 'seen' when C=0 (we drove 0).
    # Idle is 1; SET lp0=0.
    lines = ["SET lp0=0"]
    for i in range(READBACK_LATENCY + 2):
        lines.append("IN lp0")
        lines.append(f"JMP NC, seen{i}")  # C clear means saw 0
    for i in range(READBACK_LATENCY + 2):
        lines.append(f"seen{i}: JMP AL, hang")
    lines.append("hang: JMP AL, hang")
    m = Machine()
    m.load(assemble("\n".join(lines)), [_cfg_out()])

    # Record which 'seen' label we hit by watching PC after each cycle.
    # Simpler API: after each step, sample what IN would see.
    m2 = Machine()
    m2.load(assemble("SET lp0=0\nhang: JMP AL, hang\n"), [_cfg_out()])
    first = None
    for cy in range(READBACK_LATENCY + 3):
        m2.step()
        # Observation point: value available to logic *during* this completed cycle
        # equals sync1 after the step's sync update — same as IN would sample if issued here.
        # For cycle index: instruction SET executed in cycle 0.
        if m2._logical_in(m2.ctx[0], 0) == 0 and first is None:
            first = cy
    assert first == READBACK_LATENCY, (
        f"own output visible at cycle {first}, expected {READBACK_LATENCY} "
        f"(SET in cycle 0)"
    )


def test_external_pin_visible_after_two_sync_flops():
    """External change during cycle M is first visible to logic in cycle M+2."""
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [_cfg_in()])
    # Settle high
    m.phys_ext[0] = 1
    for _ in range(4):
        m.step()
    assert m._logical_in(m.ctx[0], 0) == 1

    # Change during cycle M: we alter phys_ext mid-window, then complete cycle M.
    # Model: change is present when cycle M's sync samples at the start of M+1
    # after the change occurred during M. Equivalent: set before step M, but the
    # architectural claim is visible in M+2 relative to change cycle M.
    # Operationalize: after settling, set ext=0, then the next step is cycle M
    # (change coincided with entering M). First sync sample of 0 is at start of M;
    # visible in sync1 after 2 flops → during cycle M+1 if sampled at start...
    # Spec: "change during cycle M … visible in cycle M+2".
    # Implementation: record change_cycle = current cycle, apply ext, step until seen.
    M = m.cycle
    m.phys_ext[0] = 0
    first = None
    for _ in range(5):
        m.step()
        if m._logical_in(m.ctx[0], 0) == 0 and first is None:
            first = m.cycle - 1  # cycle index of the step that just completed
    assert first == M + 2, (
        f"external change at M={M} visible at cycle {first}, expected {M + 2}"
    )
