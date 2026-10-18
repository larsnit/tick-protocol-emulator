"""Milestone: uart_rx.asm on RTL vs ISS — normal, back-to-back, framing, glitch."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, PinMode, TickSource, assemble
from tick.cfg import dict_to_bytes
from tick.host_link import HostLink

PER = 8


def _uart_rx_cfg(per: float = 8.0):
    return {
        "per": per,
        "phase": int(per) // 2,
        "tick_source": TickSource.TIMER,
        "msb_first": False,
        "dout_lp": 0,
        "din_lp": 0,
        "pins": [{"physical": 0, "mode": PinMode.INPUT, "idle": 1}],
        "events": [
            {"kind": EventKind.EDGE_FALL, "pin": 0, "latched": True},
            {"kind": EventKind.LEVEL_HIGH, "pin": 0},
        ],
    }


def _frame_levels(byte: int, per: int, *, stop: int = 1) -> list[int]:
    bits = [0] + [((byte >> i) & 1) for i in range(8)] + [stop]
    levels = []
    for b in bits:
        levels.extend([b] * per)
    return levels


async def _pop_rx(host: HostLink) -> int | None:
    """Pop one core→host word (10-bit) via HostLink."""
    got = await host.pull()
    if got is None:
        return None
    tag, data = got
    return (data & 0xFF) | ((tag & 3) << 8)


def _iss_word(w) -> int:
    return (w.data & 0xFF) | ((int(w.tag) & 3) << 8)


@cocotb.test()
async def uart_rx_normal_and_back_to_back(dut):
    """uart_rx.asm: normal + back-to-back PER=8 frames match ISS host FIFO."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "uart_rx.asm").read_text())
    cfg = _uart_rx_cfg(float(PER))
    payload = [0x55, 0x00, 0xFF, 0xA5]
    levels = [1] * 16
    for b in payload:
        levels.extend(_frame_levels(b, PER))
    levels.extend([1] * (PER * 8))

    m = Machine()
    m.load(img, [cfg])
    for lv in levels:
        m.phys_ext[0] = lv
        m.step()
    iss_got = []
    while True:
        w = m.host_pop()
        if w is None:
            break
        iss_got.append(_iss_word(w))

    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(img)
    await host.run()
    for lv in levels:
        dut.uio_in.value = lv & 1
        await RisingEdge(dut.clk)
    for _ in range(PER * 4):
        dut.uio_in.value = 1
        await RisingEdge(dut.clk)

    rtl_got = []
    for _ in range(8):
        w = await _pop_rx(host)
        if w is None:
            break
        rtl_got.append(w)

    assert [w & 0xFF for w in iss_got] == payload, iss_got
    assert rtl_got == iss_got, (rtl_got, iss_got)


@cocotb.test()
async def uart_rx_framing_error(dut):
    """uart_rx.asm: stop=0 → PUSH ERR; RTL host FIFO matches ISS."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "uart_rx.asm").read_text())
    cfg = _uart_rx_cfg(float(PER))
    levels = [1] * 8 + _frame_levels(0xFF, PER, stop=0) + [1] * (PER * 16)

    m = Machine()
    m.load(img, [cfg])
    for lv in levels:
        m.phys_ext[0] = lv
        m.step()
    iss_got = []
    while True:
        w = m.host_pop()
        if w is None:
            break
        iss_got.append(_iss_word(w))

    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(img)
    await host.run()
    for lv in levels:
        dut.uio_in.value = lv & 1
        await RisingEdge(dut.clk)
    for _ in range(PER * 4):
        dut.uio_in.value = 1
        await RisingEdge(dut.clk)

    rtl_got = []
    for _ in range(4):
        w = await _pop_rx(host)
        if w is None:
            break
        rtl_got.append(w)

    assert iss_got, "ISS expected ERR push"
    assert (iss_got[0] >> 8) & 3 == 2, iss_got  # PushTag.ERR
    assert rtl_got == iss_got, (rtl_got, iss_got)


@cocotb.test()
async def uart_rx_glitch_shorter_than_half_bit(dut):
    """Glitch shorter than PER/2 must not produce a host word."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "uart_rx.asm").read_text())
    cfg = _uart_rx_cfg(float(PER))
    levels = [1] * 16 + [0, 0] + [1] * (PER * 20)

    m = Machine()
    m.load(img, [cfg])
    for lv in levels:
        m.phys_ext[0] = lv
        m.step()
    assert m.host_pop() is None

    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(img)
    await host.run()
    for lv in levels:
        dut.uio_in.value = lv & 1
        await RisingEdge(dut.clk)
    assert await _pop_rx(host) is None
