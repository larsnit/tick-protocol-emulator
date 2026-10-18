"""Directed lockstep: JMP ERR must see same-cycle MISS (fuzz trial 1 class).

When the timer runs with an empty timed queue, a tick sets MISS. ISS applies
that tick before issuing JMP, so JMP ERR takes in the same cycle. Pre-fix RTL
fed registered miss into err_bits, so JMP fell through once and a later SET
drove an open-drain pin the ISS never drove.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, PinMode, TickSource
from tick.cfg import dict_to_bytes
from tick.isa import JmpCond, WaitTc, encode_jmp, encode_ldi, encode_set, encode_wait
from tick.host_link import HostLink
from lockstep_harness import start_run, rtl_pads

# WAIT tick (per=4) → 4× LDI so the next miss tick coincides with JMP ERR.
# If JMP misses same-cycle MISS it falls through and SETs OD LP1 low (phys7).
IMG = [
    encode_wait(WaitTc.NONE, 1 << 4),
    encode_ldi(0, 0),
    encode_ldi(0, 1),
    encode_ldi(0, 2),
    encode_ldi(0, 3),
    encode_jmp(JmpCond.ERR, 5),  # self
    encode_set(False, False, 0x2, 0x0),
    encode_jmp(JmpCond.AL, 5),
]
CFG = {
    "per": 4.0,
    "phase": 0,
    "msb_first": False,
    "clk_en": False,
    "cpol": False,
    "cpha": False,
    "dout_lp": 1,
    "din_lp": 0,
    "tick_source": TickSource.TIMER,
    "default_byte": 0,
    "pins": [
        {"physical": 0, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 7, "mode": PinMode.OPENDRAIN, "idle": 1, "glitch_filter": False},
        {"physical": 2, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 3, "mode": PinMode.INPUT, "idle": 0, "glitch_filter": False},
    ],
    "events": [{"kind": EventKind.HOST_DATA} for _ in range(4)],
}
N_CYC = 40


def _iss_trace():
    m = Machine()
    m.load(IMG, [CFG])
    tr = []
    for _ in range(N_CYC):
        m.phys_ext = [0] * 8
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        tr.append((out, oe))
    return tr


@cocotb.test()
async def repro_trial1_jmp_err_same_cycle_miss(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    iss = _iss_trace()
    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, CFG, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(IMG)
    dut.uio_in.value = 0
    await start_run(host, dut)
    rtl = []
    for cy in range(N_CYC):
        dut.uio_in.value = 0
        await RisingEdge(dut.clk)
        rtl.append(rtl_pads(dut))
    for i in range(N_CYC):
        io, ie = iss[i]
        ro, re = rtl[i]
        if ie != re or (io & ie) != (ro & re):
            raise AssertionError(
                f"mismatch cy={i} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x})"
            )
    for i in range(N_CYC):
        _, ie = iss[i]
        assert (ie & 0x80) == 0, f"ISS unexpectedly drove phys7 at cy={i}"
