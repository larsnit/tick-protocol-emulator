"""uart_tx.asm bring-up via SPI host link: PUSH byte, ISS↔RTL pads, check_uart."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))
sys.path.insert(0, str(ROOT / "verification" / "model"))

from tick import EventKind, Machine, PinMode, TickSource, assemble
from tick.cfg import dict_to_bytes
from tick.host_link import HostLink
from check_uart import decode_uart_frame, falling_edges
from lockstep_harness import start_run, rtl_pads

PER = 8
N_CYC = 200


def _uart_tx_cfg(per: float = 8.0):
    return {
        "per": per,
        "phase": 0,
        "tick_source": TickSource.TIMER,
        "msb_first": False,
        "dout_lp": 0,
        "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
        "events": [{"kind": EventKind.HOST_DATA}],
    }


def _pin0_trace(pads: list[tuple[int, int]]) -> list[int]:
    """Idle-high when OE off (UART line released)."""
    return [(out & 1) if (oe & 1) else 1 for out, oe in pads]


@cocotb.test()
async def uart_tx_0x55_iss_rtl_check_uart(dut):
    """PUSH 0x55 LAST → ISS/RTL pad lockstep; both decode as 8N1 0x55."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "uart_tx.asm").read_text())
    cfg = _uart_tx_cfg(float(PER))
    host_word = 0x55 | 0x100  # LAST
    ext = [0x00] * N_CYC

    m = Machine()
    m.load(img, [cfg])
    m.host_push(host_word & 0xFF, last=True)
    iss_pads: list[tuple[int, int]] = []
    for cy in range(N_CYC):
        m.phys_ext = [(ext[cy] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss_pads.append((out, oe))

    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(img)
    await host.push(0x55, last=True)
    dut.uio_in.value = 0
    # Timer TX: registered pads match ISS on the same execute index (align=0).
    await start_run(host, dut)
    rtl_pads_t: list[tuple[int, int]] = []
    for cy in range(N_CYC):
        dut.uio_in.value = ext[cy]
        await RisingEdge(dut.clk)
        rtl_pads_t.append(rtl_pads(dut))

    for i, (io, ie) in enumerate(iss_pads):
        ro, re = rtl_pads_t[i]
        assert ie == re and (io & ie) == (ro & re), (
            f"cy={i} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x})"
        )

    iss_trace = _pin0_trace(iss_pads)
    rtl_trace = _pin0_trace(rtl_pads_t)
    for name, tr in (("ISS", iss_trace), ("RTL", rtl_trace)):
        edges = falling_edges(tr)
        assert edges, f"{name}: no UART start bit"
        assert decode_uart_frame(tr, edges[0], PER) == 0x55, name
