"""Timed-queue order sweep — posts on completing ticks must not strand."""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))
from tick import assemble
from test_uart_tx import load_program


async def run_prog(dut, src, cycles=120):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)
    await load_program(dut, assemble(src))
    dut.ui_in.value = 1 << 3  # run
    edges, prev, miss = [], None, None
    for cy in range(cycles):
        await RisingEdge(dut.clk)
        pin = int(dut.uio_out.value) & 1
        oe = int(dut.uio_oe.value) & 1
        cur = pin if oe else 1
        if prev is not None and cur != prev:
            edges.append((cy, cur))
        prev = cur
        try:
            m = int(dut.user_project.core.miss.value)
            if miss is None and m:
                miss = cy
        except Exception:
            pass
    return edges, miss


@cocotb.test()
async def queue_order_sweep(dut):
    """Queue-ordering regression: late posts must not drop edges; may MISS but not strand."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    for k in range(0, 21):
        nops = "\n".join(["ALU MOV r0, r0"] * k)
        src = f"SET.T tx=0\n{nops}\nSET.T tx=1\nSET.T tx=0\nSET.T tx=1\nhang: JMP AL, hang\n"
        edges, miss = await run_prog(dut, src)
        dut._log.info(f"k={k:2d} edges={edges} miss_at={miss}")
        # Forbid the stranded-pending signature (two edges with a 16-cycle hole at 9/25)
        assert edges != [(9, 0), (25, 1)], (k, edges)
        if k < 15:
            # Posts stay ahead of draining the 2-deep queue → four clean edges
            assert len(edges) == 4, (k, edges)
            assert [e[1] for e in edges] == [0, 1, 0, 1], (k, edges)
            assert all(b[0] - a[0] == 8 for a, b in zip(edges, edges[1:])), (k, edges)
        else:
            # Late second post: allow MISS + shifted grid, but keep program order
            assert len(edges) >= 2, (k, edges)
            vals = [e[1] for e in edges]
            assert vals[0] == 0
            for a, b in zip(vals, vals[1:]):
                assert a != b
