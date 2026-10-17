"""Pin LEVEL traps suppressed on RUN rise; host traps still fire (2026-10-17).

Symptom: 1000×500 trial40 cy1 ISS out=0x08 RTL out=0x00 (same OE).
Root cause: ISS enable-snapped with default phys_ext=1 and took LEVEL_HIGH on
cy0; RTL suppressed pin traps on run_rise then took a different trap path on
cy1 (SET at vector cleared PP idle). Fix: ISS matches RTL — suppress pin traps
for one step after enable snap; harness sets phys_ext=ext[0] before load.
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

IMG = [
    0x4000,  # LDI r0, 0
    0x3004,  # JMP AL, 1
    0x3008,  # JMP AL, 2  (LEVEL trap vector)
    0x300C,  # JMP AL, 3
]
CFG = {
    "per": 8.0,
    "msb_first": False,
    "clk_en": False,
    "cpol": False,
    "cpha": True,
    "dout_lp": 3,
    "din_lp": 1,
    "clk_lp": 1,
    "tick_source": TickSource.TIMER,
    "default_byte": 0,
    "miss_policy": MissPolicy.FLAG,
    "miss_vector": 0,
    "pins": [
        {"physical": 4, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 1, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": False},
        {"physical": 6, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
        {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
    ],
    "events": [
        {"kind": EventKind.HOST_DATA, "trap": False, "vector": 0},
        {"kind": EventKind.LEVEL_HIGH, "pin": 1, "trap": True, "vector": 2},
        {"kind": EventKind.LEVEL_HIGH, "pin": 3, "trap": True, "vector": 3},
        {"kind": EventKind.HOST_SPACE, "trap": False, "vector": 0},
    ],
}
# phys1 high so LEVEL_HIGH is live after sync — but must not trap on cy0.
EXT = [0x02] * 16  # bit1 set
HOST = [0x10]


@cocotb.test()
async def pin_level_trap_not_on_run_rise_cycle(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    m = Machine()
    m.phys_ext = [(EXT[0] >> p) & 1 for p in range(8)]
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF)
    n = 8
    iss = []
    for cy in range(n):
        m.phys_ext = [(EXT[min(cy, len(EXT) - 1)] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((out, oe, m.ctx[0].pc))
    # cy0: pin trap suppressed → still at program (pc advanced from LDI).
    assert iss[0][2] != 2, f"ISS took LEVEL trap on cy0 pc={iss[0][2]}"
    # Later: LEVEL trap may fire once suppress clears.
    assert any(t[2] == 2 for t in iss[1:]), "LEVEL trap never fired after cy0"

    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, CFG, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, IMG)
    for hw in HOST:
        await push_host(dut, hw & 0xFF)
    dut.ui_in.value = 1 << 3
    core = dut.user_project.core
    for cy in range(n + ALIGN):
        dut.uio_in.value = EXT[min(cy, len(EXT) - 1)]
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
