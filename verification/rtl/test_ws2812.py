"""ws2812.asm bring-up via SPI host link: PUSH byte, ISS↔RTL pads, check_ws2812."""

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
from check_ws2812 import decode_ws2812_byte
from lockstep_harness import start_run, rtl_pads

PER = 4
N_CYC = 400
PAYLOAD = 0xA5


def _ws2812_cfg(per: float = 4.0):
    return {
        "per": per,
        "phase": 0,
        "msb_first": True,
        "tick_source": TickSource.TIMER,
        "dout_lp": 0,
        "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0}],
        "events": [{"kind": EventKind.HOST_DATA}],
    }


def _pin0_trace(pads: list[tuple[int, int]]) -> list[int]:
    """Idle-low when OE off (WS2812 line released)."""
    return [(out & 1) if (oe & 1) else 0 for out, oe in pads]


@cocotb.test()
async def ws2812_0xa5_iss_rtl_check_ws2812(dut):
    """PUSH 0xA5 LAST → ISS/RTL pad lockstep; both decode as WS2812 0xA5."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "ws2812.asm").read_text())
    cfg = _ws2812_cfg(float(PER))
    ext = [0x00] * N_CYC

    m = Machine()
    m.load(img, [cfg])
    m.host_push(PAYLOAD, last=True)
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
    await host.push(PAYLOAD, last=True)
    dut.uio_in.value = 0
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
    assert decode_ws2812_byte(iss_trace, PER) == PAYLOAD
    assert decode_ws2812_byte(rtl_trace, PER) == PAYLOAD
    assert not m.ctx[0].miss
