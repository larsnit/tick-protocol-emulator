"""HOST_DATA trap must fire on the RUN-rising cycle (2026-10-17).

Symptom: 1000×500 trial26 cy0 ISS OE=0x30 RTL OE=0x31 (extra phys0).
Root cause: RTL suppressed *all* event traps while run & ~run_q (load-bus
pin-level fix). ISS still takes HOST_DATA traps on enable/RUN rise, then
issues the vector insn (SET.E clear OE) same cycle. Pin traps stay suppressed
on that cycle; host-data / host-space must not be.
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
from rtl_bus import load_cfg_bytes, load_program, push_host, reset_dut

ALIGN = 1

# Trap vector 2: SET.E LP0 OE off. Without same-cycle host trap, idle PP keeps OE.
IMG = [
    0x3004,  # JMP AL, 1
    0x3004,  # JMP AL, 1
    0x0440,  # SET.E mask=1 val=0  (clear OE on LP0)
    0x300C,  # JMP AL, 3
]
CFG = {
    "per": 16.0,
    "msb_first": False,
    "clk_en": False,
    "cpol": True,
    "cpha": False,
    "dout_lp": 3,
    "din_lp": 0,
    "clk_lp": 2,
    "tick_source": TickSource.TIMER,
    "default_byte": 0,
    "miss_policy": MissPolicy.FLAG,
    "miss_vector": 0,
    "pins": [
        {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
        {"physical": 4, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
        {"physical": 5, "mode": PinMode.OPENDRAIN, "idle": 0, "glitch_filter": False},
        {"physical": 6, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": False},
    ],
    "events": [
        {"kind": EventKind.LEVEL_LOW, "pin": 3, "trap": False, "vector": 0},
        {"kind": EventKind.LEVEL_LOW, "pin": 0, "trap": False, "vector": 0},
        {"kind": EventKind.LEVEL_HIGH, "pin": 0, "trap": False, "vector": 0},
        {"kind": EventKind.HOST_DATA, "trap": True, "vector": 2},
    ],
}
HOST = [0x47]


@cocotb.test()
async def host_data_trap_fires_on_run_rise(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    m = Machine()
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    n = 8
    iss = []
    for cy in range(n):
        m.phys_ext = [1] * 8
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((out, oe, m.ctx[0].pc))
    # cy0: trap + SET.E → phys0 OE cleared (bit0 off).
    assert (iss[0][1] & 1) == 0, f"ISS cy0 still driving phys0 oe={iss[0][1]:#x}"
    assert iss[0][2] == 3, f"ISS cy0 pc={iss[0][2]} expected 3 after vector SET.E"

    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, CFG, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, IMG)
    for hw in HOST:
        await push_host(dut, hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    dut.ui_in.value = 1 << 3
    core = dut.user_project.core
    for cy in range(n + ALIGN):
        dut.uio_in.value = 0xFF
        await RisingEdge(dut.clk)
        if cy < ALIGN:
            continue
        i = cy - ALIGN
        io, ie, ipc = iss[i]
        ro = int(dut.uio_out.value) & 0xFF
        re = int(dut.uio_oe.value) & 0xFF
        rpc = int(core.dbg_pc.value)
        assert ie == re and (io & ie) == (ro & re), (
            f"cy={i} ISS=({io:#04x},{ie:#04x}) pc={ipc} "
            f"RTL=({ro:#04x},{re:#04x}) pc={rpc}"
        )
        assert ipc == rpc, f"cy={i} pc ISS={ipc} RTL={rpc}"
