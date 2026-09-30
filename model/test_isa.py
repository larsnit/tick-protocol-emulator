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


def _cfg_pushpull(per: float = 8.0):
    return {
        "per": per,
        "phase": 0,
        "tick_source": TickSource.TIMER,
        "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
    }


def _run_edges(src: str, per: float = 8.0, cycles: int = 200):
    m = Machine()
    m.load(assemble(src), [_cfg_pushpull(float(per))])
    edges = []
    prev = 1
    for _ in range(cycles):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else 1
        if cur != prev:
            edges.append((m.cycle, cur))
            prev = cur
    return edges, m


def test_kth_timed_op_padding_sweep():
    """W7: padding between posts must not reorder edges while posts stay ahead of ticks."""
    per = 8.0
    # With PER=8, keep k < 7 so the second post lands before the first tick.
    ref_deltas = None
    for k in range(0, 7):
        nops = "\n".join(["ALU MOV r0, r0"] * k)
        src = f"SET.T tx=0\n{nops}\nSET.T tx=1\nSET.T tx=0\nSET.T tx=1\nhang: JMP AL, hang\n"
        edges, m = _run_edges(src, per=per)
        assert len(edges) == 4, (k, edges)
        assert [e[1] for e in edges] == [0, 1, 0, 1], (k, edges)
        assert all(b[0] - a[0] == int(per) for a, b in zip(edges, edges[1:])), (k, edges)
        # Timer may MISS after the burst drains (W3); edges themselves must be clean.
        deltas = [e[0] - edges[0][0] for e in edges]
        if ref_deltas is None:
            ref_deltas = deltas
        else:
            assert deltas == ref_deltas, (k, edges, ref_deltas)


def test_kth_timed_op_branching_paths():
    """W7: unequal path lengths into the same timed posts still hit the tick grid."""
    src_a = """
        LDI r0, 1
        JMP NZ, burst
        ALU MOV r0, r0
    burst:
        SET.T tx=0
        SET.T tx=1
        SET.T tx=0
        SET.T tx=1
        hang: JMP AL, hang
    """
    src_b = """
        LDI r0, 0
        JMP NZ, burst
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
    burst:
        SET.T tx=0
        SET.T tx=1
        SET.T tx=0
        SET.T tx=1
        hang: JMP AL, hang
    """
    per = 8.0
    ea, _ = _run_edges(src_a, per=per)
    eb, _ = _run_edges(src_b, per=per)
    assert len(ea) == 4 and len(eb) == 4, (ea, eb)
    assert [e[1] for e in ea] == [0, 1, 0, 1]
    assert [e[1] for e in eb] == [0, 1, 0, 1]
    assert all(b[0] - a[0] == int(per) for a, b in zip(ea, ea[1:]))
    assert all(b[0] - a[0] == int(per) for a, b in zip(eb, eb[1:]))


def test_late_post_miss_and_shift():
    """W7: posting after the tick has passed sets MISS; edge stays on the grid."""
    src = """
        SET.T tx=0
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
        ALU MOV r0, r0
        SET.T tx=1
        hang: JMP AL, hang
    """
    per = 4.0
    edges, m = _run_edges(src, per=per, cycles=80)
    assert m.ctx[0].miss
    assert len(edges) >= 2
    assert (edges[1][0] - edges[0][0]) % int(per) == 0
    assert edges[1][0] - edges[0][0] >= 2 * int(per)


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
