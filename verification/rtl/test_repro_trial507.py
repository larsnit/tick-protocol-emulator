"""Lockstep repro for fuzz trial=507 after TIME_L fix."""

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
from tick.isa import decode
from tick.host_link import HostLink
from rtl_only import RTL_ONLY
from lockstep_harness import start_run, rtl_pads

IMG = [int(x, 0) for x in [
    '0x4401', '0x350c', '0x4000', '0x3514', '0x4001', '0x5020', '0x5220', '0x5420',
    '0x5620', '0x5820', '0x5a20', '0x5c20', '0x5e20', '0x8c00', '0x5540', '0x7600',
    '0x4ce2', '0x5420', '0x3134', '0x3d3c', '0x88', '0x3d38', '0x3640', '0x910',
    '0x8200', '0x6c40', '0x3540', '0x3560', '0x9300', '0x1600', '0x2200', '0x1a00',
    '0x9ac0', '0x8400', '0x5420', '0x3338', '0x8800', '0x7200', '0x356c', '0x309c',
]]
CFG = {
    'per': 16.0, 'phase': 0, 'msb_first': True, 'clk_en': False, 'cpol': False, 'cpha': False,
    'dout_lp': 3, 'din_lp': 0, 'tick_source': TickSource.TIMER, 'default_byte': 104,
    'pins': [
        {'physical': 3, 'mode': PinMode.PUSHPULL, 'idle': 0, 'glitch_filter': False},
        {'physical': 5, 'mode': PinMode.PUSHPULL, 'idle': 0, 'glitch_filter': False},
        {'physical': 2, 'mode': PinMode.INPUT, 'idle': 1, 'glitch_filter': False},
        {'physical': 6, 'mode': PinMode.PUSHPULL, 'idle': 1, 'glitch_filter': False},
    ],
    'events': [{'kind': EventKind.HOST_DATA} for _ in range(4)],
}
HOST = [0x326, 0xd7, 0x2cc, 0x2d6, 0x250, 0x23f, 0x2d5, 0x28f]
# Truncated EXT from log — regenerate full length below if needed
EXT0 = [47, 11, 14, 50, 94, 157, 57, 150, 131, 149, 218, 60, 63, 153, 149, 187]
N_CYC = 360


def _iss_dump(ext):
    m = Machine()
    m.load(IMG, [CFG])
    for hw in HOST:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    tr = []
    for cy in range(N_CYC):
        c = m.ctx[0]
        pc = c.pc
        w = m.imem[c.base + pc]
        m.phys_ext = [(ext[min(cy, len(ext) - 1)] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        tr.append((out, oe, pc, w, c.regs[:], c.drive_val, c.overrun, c.time))
    return tr


@cocotb.test(skip=RTL_ONLY)  # probes user_project.core
async def repro_trial507(dut):
    # Rebuild same RNG stream as fuzz trial 507 for EXT — use log EXT prefix + zeros.
    # Full EXT was printed in the log; parse from env file if present.
    ext_path = Path("/tmp/fuzz_1k_timefix.log")
    ext = list(EXT0) + [0] * (N_CYC + 8)
    text = ext_path.read_text()
    import ast
    import re
    m = re.search(r"REPRO_EXT=(\[[^\]]+\])", text)
    if m:
        ext = ast.literal_eval(m.group(1))
        while len(ext) < N_CYC + 4:
            ext.append(0)

    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    iss = _iss_dump(ext)
    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, CFG, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(IMG)
    for hw in HOST:
        await host.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    dut.uio_in.value = ext[0] if ext else 0
    await start_run(host, dut)
    rtl = []
    q = dut.user_project.core.u_queue
    for cy in range(N_CYC):
        dut.uio_in.value = ext[min(cy, len(ext) - 1)]
        await RisingEdge(dut.clk)
        out = int(dut.uio_out.value) & 0xFF
        oe = int(dut.uio_oe.value) & 0xFF
        rtl.append((out, oe))
        if cy < N_CYC:
            def gv(n):
                try:
                    return int(getattr(q, n).value)
                except Exception:
                    return -1
            pc = int(dut.user_project.core.u_issue.pc_q.value)
            # After rtl cycle cy, compare to ISS PC after cycle (cy):
            # iss[] stores pre-step PC; post-step PC is ctx after that step ≈ next
            # entry's pre-PC when not the last, else decode from regs dump.
            iss_i = cy
            iss_post_pc = iss[iss_i + 1][2] if iss_i + 1 < len(iss) else iss[iss_i][2]
            if pc != iss_post_pc:
                print(
                    f"PC_DIVERT rtl_cy={cy} rtl_pc={pc} iss_after_cy={iss_i} "
                    f"iss_pc={iss_post_pc} a_k={gv('a_kind')} p_k={gv('p_kind')}"
                )
                if cy > 60:
                    # only first few after warm-up
                    pass
    for i in range(N_CYC):
        io, ie, pc, w, regs, dv, ov, tm = iss[i]
        ro, re = rtl[i]
        if ie != re or (io & ie) != (ro & re):
            print(
                f"MISMATCH cy={i} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x}) "
                f"pc={pc} {decode(w)} regs={regs} dv={dv:#x} ov={ov} time={tm}"
            )
            # Print nearby ISS
            for j in range(max(0, i - 5), min(N_CYC, i + 3)):
                a = iss[j]
                print(f"  iss {j}: out={a[0]:#04x} pc={a[2]} {decode(a[3])} r={a[4]} t={a[7]}")
            raise AssertionError(f"cy={i}")
