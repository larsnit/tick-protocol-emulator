"""Unit tests for assembler and ISA property claims on the ISS."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))
sys.path.insert(0, str(ROOT / "verification" / "model"))

from tick import EventKind, Machine, MissPolicy, PinMode, TickSource, assemble
from tick.isa import Op, decode


def test_assemble_uart_tx():
    words = assemble((ROOT / "sw" / "programs" / "uart_tx.asm").read_text())
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
        "ws2812.asm",
    ):
        words = assemble((ROOT / "sw" / "programs" / name).read_text())
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


def _run_edge_sweep(src: str, per: float = 8.0, cycles: int = 120):
    """RTL-aligned: edge cycle = step index; return (edges, first_miss_cycle)."""
    m = Machine()
    m.load(assemble(src), [_cfg_pushpull(float(per))])
    assert m.ctx[0].enabled and not m.ctx[1].enabled
    edges, prev, miss = [], None, None
    for cy in range(cycles):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else 1
        if prev is not None and cur != prev:
            edges.append((cy, cur))
        prev = cur
        if miss is None and m.ctx[0].miss:
            miss = cy
    return edges, miss


def test_kth_timed_op_padding_sweep():
    """Path-independence: padding must not reorder edges while posts stay ahead of the drain.

    Single-context ISS matches RTL queue_order_sweep: clean 8-cycle grid for
    k=0..14; first late-post / MISS break at k=15 (not k=7).
    """
    per = 8.0
    ref_deltas = None
    for k in range(0, 15):
        nops = "\n".join(["ALU MOV r0, r0"] * k)
        src = f"SET.T tx=0\n{nops}\nSET.T tx=1\nSET.T tx=0\nSET.T tx=1\nhang: JMP AL, hang\n"
        edges, miss_cy = _run_edge_sweep(src, per=per)
        assert len(edges) == 4, (k, edges)
        assert [e[1] for e in edges] == [0, 1, 0, 1], (k, edges)
        assert all(b[0] - a[0] == int(per) for a, b in zip(edges, edges[1:])), (k, edges)
        assert miss_cy is None or miss_cy > edges[-1][0], (k, miss_cy, edges)
        deltas = [e[0] - edges[0][0] for e in edges]
        if ref_deltas is None:
            ref_deltas = deltas
        else:
            assert deltas == ref_deltas, (k, edges, ref_deltas)

    # k=15 is the first late-post break (same k as RTL).
    nops = "\n".join(["ALU MOV r0, r0"] * 15)
    src = f"SET.T tx=0\n{nops}\nSET.T tx=1\nSET.T tx=0\nSET.T tx=1\nhang: JMP AL, hang\n"
    edges15, miss15 = _run_edge_sweep(src, per=per)
    assert miss15 is not None, edges15
    assert edges15[0][0] + int(per) not in [e[0] for e in edges15[1:]], edges15
    assert edges15[1][0] - edges15[0][0] == 2 * int(per), edges15


def test_kth_timed_op_branching_paths():
    """Path-independence: unequal path lengths into the same timed posts still hit the tick grid."""
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
    """Path-independence: posting after the tick has passed sets MISS; edge stays on the grid."""
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
    from tick.iss import Job, TimedOp
    from tick.isa import XferMode

    c = m.ctx[0]
    c.timed_active = TimedOp("xfer", job=Job(XferMode.OUT, 8, 0xAA))
    m.phys_ext[1] = 0
    for _ in range(6):
        m.step()
    m.phys_ext[1] = 1
    for _ in range(6):
        m.step()
    assert c.timed_active is None


def test_wait_tick_is_timed_op_no_miss_after_stop():
    """Tick-consuming WAIT occupies a queue slot; stop-bit WAIT consumes its tick (no MISS)."""
    src = """
        SET.T tx=0
        SET.T tx=1
        WAIT  tick, stop
        hang: JMP AL, hang
    """
    per = 8.0
    edges, m = _run_edges(src, per=per, cycles=80)
    assert len(edges) == 2
    assert edges[1][0] - edges[0][0] == int(per)
    # After the WAIT consumes the tick following the second SET, timer is stopped.
    assert not m.ctx[0].timer_running
    assert not m.ctx[0].miss
    assert m.ctx[0].evf & 0x10


def test_wait_tick_between_sets_takes_middle_tick():
    """SET.T; tick-WAIT; SET.T — three timed ops on three consecutive ticks."""
    src = """
        SET.T tx=0
        WAIT  tick
        SET.T tx=1
        hang: JMP AL, hang
    """
    per = 8.0
    edges, m = _run_edges(src, per=per, cycles=80)
    assert len(edges) == 2
    # Middle WAIT consumed a tick, so edges are 2*PER apart.
    assert edges[1][0] - edges[0][0] == 2 * int(per), edges


def test_wait_timeout_event_first():
    """WAIT ev0|tick — host data before timeout dequeues wait; no MISS on that tick."""
    src = """
        WAIT  ev0|tick, stop
        LDI   r0, 0xA5
        hang: JMP AL, hang
    """
    m = Machine()
    m.load(
        assemble(src),
        [
            {
                "per": 8.0,
                "phase": 0,
                "tick_source": TickSource.TIMER,
                "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
                "events": [{"kind": EventKind.HOST_DATA}],
            }
        ],
    )
    c = m.ctx[0]
    # Let WAIT post and timer start; push host data before first tick.
    for _ in range(3):
        m.step()
    assert c.waiting
    assert c.timed_active is not None and c.timed_active.kind == "wait"
    m.host_push(0x11)
    for _ in range(4):
        m.step()
        if not c.waiting:
            break
    assert not c.waiting
    assert c.regs[0] == 0xA5
    assert c.evf & 0x01
    assert not (c.evf & 0x10)


def test_xfer_out_width_limit():
    """XFER width limits: out/both capped at 8; in may be 9–16."""
    import pytest
    from tick.isa import encode_xfer, XferMode

    encode_xfer(0, 8, XferMode.OUT)
    encode_xfer(0, 9, XferMode.IN)
    with pytest.raises(ValueError):
        encode_xfer(0, 9, XferMode.OUT)
    with pytest.raises(ValueError):
        encode_xfer(0, 9, XferMode.BOTH)


def test_engine_clk_two_ticks_per_bit_cpha1():
    """Engine clock: with clk_en, each bit takes 2 ticks; CPHA=1 changes data on leading."""
    src = """
        LDI r0, 0x80
        XFER r0, 2, out
        hang: JMP AL, hang
    """
    m = Machine()
    m.load(
        assemble(src),
        [
            {
                "per": 4.0,
                "msb_first": True,
                "clk_en": True,
                "cpha": True,
                "cpol": False,
                "dout_lp": 0,
                "clk_lp": 2,
                "pins": [
                    {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
                    {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
                    {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
                ],
            }
        ],
    )
    trace_d, trace_c = [], []
    for _ in range(40):
        m.step()
        trace_d.append(m.phys_drive[0] if m.phys_oe[0] else 0)
        trace_c.append(m.phys_drive[2] if m.phys_oe[2] else 0)
    # Clock should rise twice (2 bits × leading edges)
    rises = [i for i in range(1, len(trace_c)) if trace_c[i - 1] == 0 and trace_c[i] == 1]
    assert len(rises) >= 2, (rises, trace_c[:30])
    # Spacing between leading edges ≈ 2*PER
    assert rises[1] - rises[0] == 8, rises


def test_mfs_rx_always_sets_c_from_bit8():
    """MFS RX always does C := result[8], even when high bits are zero."""
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [{"per": 8.0}])
    c = m.ctx[0]
    c.result = 0x0055
    c.result_valid = True
    c.c = True  # sticky wrong value must be overwritten
    from tick.isa import Spr

    val = m._read_spr(c, Spr.RX)
    assert val == 0x55
    assert c.c is False

    c.result = 0x0155
    c.result_valid = True
    val = m._read_spr(c, Spr.RX)
    assert val == 0x55
    assert c.c is True
