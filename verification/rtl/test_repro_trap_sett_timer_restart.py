"""Trap stops the timer; same-cycle SET.T must restart it (trial83 class).

Docs: a trap stops the timer (phase/accum cleared). A timed post after that
restart sets tick 0 = post + PHASE (PHASE=0 → first tick after one PER).
Bug: RTL tick_timer ignored start when stop cleared a still-running timer in
the same cycle (`start && !timer_run_q`), so trap+SET.T left the timer stopped
and later SET.T commits skewed vs ISS (fuzz trial83).
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, MissPolicy, PinMode, TickSource
from tick.cfg import dict_to_bytes
from tick.isa import JmpCond, encode_jmp, encode_set
from rtl_bus import load_cfg_bytes, load_program, reset_dut

ALIGN = 1

# 0: SET.T LP0=1  → starts timer; commits on tick 0
# 1: spin
# 2: miss-trap vector: SET.T LP1=1  (stop+start same cycle)
# 3: spin
IMG = [
    encode_set(True, False, 1, 1),
    encode_jmp(JmpCond.AL, 1),
    encode_set(True, False, 2, 2),
    encode_jmp(JmpCond.AL, 3),
]


def _cfg(phase: int) -> dict:
    return {
        "per": 4.0,
        "phase": phase,
        "msb_first": False,
        "clk_en": False,
        "cpol": False,
        "cpha": False,
        "dout_lp": 0,
        "din_lp": 1,
        "clk_lp": 2,
        "tick_source": TickSource.TIMER,
        "default_byte": 0,
        "miss_policy": MissPolicy.TRAP,
        "miss_vector": 2,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
            {"physical": 1, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
            {"physical": 2, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
            {"physical": 3, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        ],
        "events": [{"kind": EventKind.HOST_SPACE, "trap": False, "vector": 0}] * 4,
    }


async def _lockstep_phase(dut, phase: int) -> None:
    cfg = _cfg(phase)
    # PHASE>0: tick0 = post+PHASE; PHASE=0: tick0 = post+PER.
    expect_delta = phase if phase > 0 else 4

    m = Machine()
    m.load(IMG, [cfg])
    n = 40
    iss = []
    post2 = commit2 = None
    for cy in range(n):
        m.phys_ext = [0] * 8
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        c = m.ctx[0]
        if c.miss and c.timed_active and c.timed_active.mask == 2 and post2 is None:
            post2 = cy
            assert c.timer_running, "ISS must restart timer on trap-vector SET.T"
        if post2 is not None and (out & 2) and commit2 is None:
            commit2 = cy
        iss.append((out, oe, c.pc, c.timer_running))

    assert post2 is not None, "MISS trap + SET.T never posted"
    assert commit2 is not None, "SET.T after trap never committed"
    assert commit2 - post2 == expect_delta, (
        f"ISS PHASE={phase}: commit delta {commit2 - post2} want {expect_delta}"
    )

    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, cfg, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, IMG)
    dut.ui_in.value = 1 << 3
    core = dut.user_project.core
    for cy in range(n + ALIGN):
        dut.uio_in.value = 0
        await RisingEdge(dut.clk)
        if cy < ALIGN:
            continue
        i = cy - ALIGN
        io, ie, ipc, irun = iss[i]
        ro = int(dut.uio_out.value) & 0xFF
        re = int(dut.uio_oe.value) & 0xFF
        rpc = int(core.dbg_pc.value)
        rrun = int(core.dbg_timer_run.value)
        assert ie == re and (io & ie) == (ro & re), (
            f"PHASE={phase} cy={i} ISS=({io:#04x},{ie:#04x}) pc={ipc} run={irun} "
            f"RTL=({ro:#04x},{re:#04x}) pc={rpc} run={rrun}"
        )
        assert ipc == rpc, f"PHASE={phase} cy={i} pc ISS={ipc} RTL={rpc}"
        # After the trap-vector SET.T posts, both sides must be running.
        if post2 is not None and i == post2:
            assert rrun == 1, (
                f"PHASE={phase} cy={i}: RTL timer still stopped after trap+SET.T "
                f"(ISS run={irun})"
            )


@cocotb.test()
async def trap_then_sett_restarts_timer_phase0(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await _lockstep_phase(dut, 0)


@cocotb.test()
async def trap_then_sett_restarts_timer_phase2(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await _lockstep_phase(dut, 2)
