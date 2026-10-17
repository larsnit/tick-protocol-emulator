"""MFS PC on MISS trap returns the vector — ISS↔RTL PC lockstep.

After the fix, trap-vector MFS PC matches ISS (vector, not pre-trap pc_q).
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import Machine, MissPolicy, PinMode, TickSource
from tick.cfg import dict_to_bytes
from tick.isa import JmpCond, Spr, encode_jmp, encode_mfs, encode_set
from rtl_bus import load_cfg_bytes, load_program, reset_dut

ALIGN = 1
MISS_VEC = 10
IMG = [
    encode_set(True, False, 0x1, 0x1),
    encode_jmp(JmpCond.AL, 1),
    *[encode_jmp(JmpCond.AL, 2) for _ in range(8)],
    encode_mfs(1, Spr.PC),
    encode_jmp(JmpCond.AL, 11),
]
CFG = {
    "per": 4.0,
    "phase": 0,
    "tick_source": TickSource.TIMER,
    "miss_policy": MissPolicy.TRAP,
    "miss_vector": MISS_VEC,
    "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
    "events": [],
}


@cocotb.test()
async def mfs_pc_on_miss_trap_lockstep(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    m = Machine()
    m.load(IMG, [CFG])
    iss = []
    for _ in range(24):
        m.step()
        iss.append((m.ctx[0].pc, m.ctx[0].regs[1]))
    assert any(pc >= MISS_VEC and r1 == MISS_VEC for pc, r1 in iss), iss

    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, CFG, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, IMG)
    dut.ui_in.value = 1 << 3
    core = dut.user_project.core
    for cy in range(24 + ALIGN):
        await RisingEdge(dut.clk)
        if cy < ALIGN:
            continue
        i = cy - ALIGN
        ipc, _ = iss[i]
        rpc = int(core.dbg_pc.value)
        assert ipc == rpc, f"pc cy={i} ISS={ipc} RTL={rpc}"
