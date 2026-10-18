"""Directed lockstep: MFS RX must not soft-wake on stale WAIT mask (trial 177).

After a host-data WAIT completes, wait_mask can remain set. MFS RX with no
result must stay blocked even while the host FIFO is non-empty. Pre-fix RTL
treated that as a soft WAIT completion, cleared waiting, and executed a later
SET that flipped a push-pull pin the ISS never drove.
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
from tick.isa import JmpCond, Spr, WaitTc, encode_jmp, encode_mfs, encode_set, encode_wait
from tick.host_link import HostLink
from lockstep_harness import start_run, rtl_pads

IMG = [
    encode_wait(WaitTc.NONE, 1 << 0),  # soft host WAIT → leaves wait_mask
    encode_mfs(0, Spr.RX),             # block forever (no XFER result)
    encode_set(False, False, 0x1, 0x1),  # LP0=1 — must not run while blocked
    encode_jmp(JmpCond.AL, 3),
]
CFG = {
    "per": 4.0,
    "phase": 0,
    "msb_first": False,
    "clk_en": False,
    "cpol": False,
    "cpha": False,
    "dout_lp": 0,
    "din_lp": 1,
    "tick_source": TickSource.TIMER,
    "default_byte": 0,
    "pins": [
        {"physical": 1, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
        {"physical": 2, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 3, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
        {"physical": 7, "mode": PinMode.INPUT, "idle": 0, "glitch_filter": False},
    ],
    "events": [{"kind": EventKind.HOST_DATA} for _ in range(4)],
}
HOST = [0x300 | 0x5C]  # non-empty host FIFO for soft WAIT / stale mask
N_CYC = 32


def _iss_trace():
    m = Machine()
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
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
async def repro_trial177_mfs_rx_no_soft_wake(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    iss = _iss_trace()
    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, CFG, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(IMG)
    for hw in HOST:
        await host.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
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
    # Phys1 must stay driven idle-0 (never SET to 1).
    for i in range(N_CYC):
        io, ie = iss[i]
        assert (ie & 0x02) != 0 and (io & 0x02) == 0, f"unexpected phys1 at cy={i}"
