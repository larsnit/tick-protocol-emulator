"""Soft WAIT must not wake on a false latched edge from load-bus sampling before run (2026-10-17).

Symptom: ISS stays in WAIT EV0; RTL completes WAIT, starts timer, SEND_DEFAULT releases OD DOUT.
Root cause: tick_queue left map_oe=0 while !run so sync sampled uio load traffic; run then
looked like EDGE_RISE on idle-high PP pins and latched EV pending. Found 2026-10-17.
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
from tick.isa import encode_jmp, encode_set, encode_wait, JmpCond, WaitTc
from rtl_bus import load_cfg_bytes, load_program, reset_dut

ALIGN = 1


@cocotb.test()
async def idle_drive_before_run_no_false_latched_edge(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    # Minimal: soft WAIT EV0 (latched rise on PP idle-high), hang. MISS send-default
    # must not run — timer never starts if WAIT stays blocked.
    img = [
        encode_wait(WaitTc.NONE, 1 << 0),
        encode_set(True, False, 0x4, 0x4),  # would start timer if WAIT woke
        encode_jmp(JmpCond.AL, 2),
    ]
    cfg = {
        "per": 4.0,
        "msb_first": False,
        "dout_lp": 2,
        "din_lp": 1,
        "clk_lp": 0,
        "tick_source": TickSource.TIMER,
        "miss_policy": MissPolicy.SEND_DEFAULT,
        "default_byte": 0xCB,
        "pins": [
            {"physical": 2, "mode": PinMode.OPENDRAIN, "idle": 0, "glitch_filter": True},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 0},
            {"physical": 6, "mode": PinMode.PUSHPULL, "idle": 1},
        ],
        "events": [
            {
                "kind": EventKind.EDGE_RISE,
                "pin": 3,
                "qual_pin": 2,
                "latched": True,
                "trap": False,
                "vector": 8,
            },
        ],
    }
    n = 40
    # Load traffic on uio while !run (random-ish bytes) to stress pre-run sync.
    ext = [0x00] * (n + ALIGN + 2)

    m = Machine()
    m.load(img, [cfg])
    iss = []
    for cy in range(n):
        m.phys_ext = [(ext[cy] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((out, oe, m.ctx[0].waiting, m.ctx[0].timer_running, m.ctx[0].pc))

    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, cfg, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, img)  # uio carries imem bytes while !run
    dut.ui_in.value = 1 << 3
    rtl = []
    for cy in range(n + ALIGN):
        dut.uio_in.value = ext[min(cy, len(ext) - 1)]
        await RisingEdge(dut.clk)
        core = dut.user_project.core
        rtl.append(
            (
                int(dut.uio_out.value) & 0xFF,
                int(dut.uio_oe.value) & 0xFF,
                int(core.dbg_waiting.value),
                int(core.dbg_timer_run.value),
                int(core.dbg_pc.value),
            )
        )

    for i in range(n):
        io, ie, iw, it, ipc = iss[i]
        ro, re, rw, rt, rpc = rtl[i + ALIGN]
        assert ie == re and (io & ie) == (ro & re), (
            f"cy={i} pin ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x})"
        )
        assert bool(iw) == bool(rw), f"cy={i} waiting ISS={iw} RTL={rw}"
        assert bool(it) == bool(rt), f"cy={i} timer ISS={it} RTL={rt}"
        assert ipc == rpc, f"cy={i} pc ISS={ipc} RTL={rpc}"
    assert iss[-1][2], "ISS should still be waiting on EV0"
    assert not iss[-1][3], "timer must stay stopped"
