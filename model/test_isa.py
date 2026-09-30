"""Unit tests for assembler and ISA property claims on the ISS."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import EventKind, Machine, MissPolicy, PinMode, TickSource, assemble
from model.opcodes import Op, decode


def test_assemble_uart_tx():
    words = assemble((ROOT / "programs" / "uart_tx.asm").read_text())
    assert len(words) == 10
    assert decode(words[0])["op"] == Op.WAIT
    assert decode(words[2])["op"] == Op.SET
    assert decode(words[2])["timed"] is True


def test_assemble_all_programs():
    for name in (
        "uart_tx.asm",
        "uart_rx.asm",
        "spi_target.asm",
        "spi_controller.asm",
        "i2c_controller.asm",
        "i2c_target.asm",
    ):
        words = assemble((ROOT / "programs" / name).read_text())
        assert 1 <= len(words) <= 64, name


def test_tick_spacing_integer_period():
    m = Machine()
    m.load(
        assemble("hang: JMP AL, hang\n"),
        [{"per": 5.0, "phase": 0, "tick_source": TickSource.TIMER}],
    )
    c = m.ctx[0]
    c.timer_running = True
    c.phase_left = 0
    tick_cycles = []
    for i in range(40):
        will = False
        if c.timer_running and c.phase_left == 0:
            will = (c.accum + (1 << 4)) >= c.per_fp
        elif c.timer_running and c.phase_left == 1:
            will = True
        m.step()
        if will:
            tick_cycles.append(i)
    deltas = [b - a for a, b in zip(tick_cycles, tick_cycles[1:])]
    assert deltas and all(d == 5 for d in deltas), (tick_cycles, deltas)


def test_kth_timed_op_on_kth_tick_independent_of_path():
    """Once both timed ops are posted, intervening NOPs do not move edges."""
    prog_nop = assemble(
        """
        SET.T tx=0
        SET.T tx=1
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
        hang: JMP AL, hang
        """
    )
    prog_tight = assemble(
        """
        SET.T tx=0
        SET.T tx=1
        hang: JMP AL, hang
        """
    )

    def run_edges(img):
        m = Machine()
        m.load(
            img,
            [
                {
                    "per": 4.0,
                    "phase": 0,
                    "tick_source": TickSource.TIMER,
                    "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
                }
            ],
        )
        edges = []
        prev = 1
        for _ in range(60):
            m.step()
            cur = m.phys_drive[0] if m.phys_oe[0] else 1
            if cur != prev:
                edges.append((m.cycle, cur))
                prev = cur
        return edges

    e1 = run_edges(prog_nop)
    e2 = run_edges(prog_tight)
    assert len(e1) >= 2 and len(e2) >= 2, (e1, e2)
    assert e1[0][0] == e2[0][0]
    assert e1[1][0] == e2[1][0]
    assert e1[1][0] - e1[0][0] == 4


def test_miss_iff_empty_queue_while_running():
    m = Machine()
    m.load(
        assemble("hang: JMP AL, hang\n"),
        [{"per": 3.0, "phase": 0, "miss_policy": MissPolicy.FLAG}],
    )
    c = m.ctx[0]
    c.timer_running = True
    c.phase_left = 0
    for _ in range(10):
        m.step()
    assert c.miss


def test_stopped_timer_empty_fifo_is_idle():
    m = Machine()
    m.load(
        assemble(
            """
        idle: WAIT ev0
              PULL r0
              JMP AL, idle
        """
        ),
        [
            {
                "per": 8.0,
                "events": [{"kind": EventKind.HOST_DATA, "trap": False}],
                "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
            }
        ],
    )
    for _ in range(20):
        m.step()
    assert not m.ctx[0].miss
    assert m.ctx[0].waiting


def test_trap_cancels_engine():
    words = assemble(
        """
        idle: WAIT ev1
              SET.E miso=on
        hang: JMP AL, hang
        desel: SET.E miso=off
               JMP AL, idle
        """
    )
    m = Machine()
    m.load(
        words,
        [
            {
                "pins": [
                    {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
                    {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
                ],
                "events": [
                    {"kind": EventKind.LEVEL_LOW, "pin": 1},
                    {"kind": EventKind.EDGE_RISE, "pin": 1, "trap": True, "vector": 3},
                ],
            }
        ],
    )
    from model.machine import Job, TimedOp
    from model.opcodes import XferMode

    c = m.ctx[0]
    c.timed_active = TimedOp("xfer", job=Job(XferMode.OUT, 8, 0xAA))
    m.phys_ext[1] = 0
    for _ in range(6):
        m.step()
    m.phys_ext[1] = 1
    for _ in range(6):
        m.step()
    assert c.timed_active is None
