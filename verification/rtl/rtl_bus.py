"""Shared cocotb helpers for the parallel host/cfg/imem bus."""

from __future__ import annotations

import sys
from pathlib import Path

from cocotb.triggers import ClockCycles, RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, PinMode, TickSource  # noqa: E402
from tick.cfg import dict_to_bytes  # noqa: E402


DEFAULT_CFG = {
    "per": 8.0,
    "phase": 0,
    "msb_first": False,
    "dout_lp": 0,
    "din_lp": 1,
    "tick_source": TickSource.TIMER,
    "pins": [
        {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1},
        {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 2, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
    ],
    "events": [{"kind": EventKind.HOST_DATA}],
}


async def set_cmd(dut, nibble: int, data: int = 0):
    dut.ui_in.value = (nibble & 0xF) << 4
    dut.uio_in.value = data & 0xFF
    await ClockCycles(dut.clk, 1)


async def pulse_imem_we(dut):
    v = int(dut.ui_in.value)
    dut.ui_in.value = v | (1 << 2)
    await ClockCycles(dut.clk, 1)
    dut.ui_in.value = v & ~(1 << 2)
    await ClockCycles(dut.clk, 1)


async def pulse_host_wr(dut):
    v = int(dut.ui_in.value)
    dut.ui_in.value = v | (1 << 0)
    await ClockCycles(dut.clk, 1)
    dut.ui_in.value = v & ~(1 << 0)
    await ClockCycles(dut.clk, 1)


async def reset_dut(dut, cycles: int = 5):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, cycles)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def load_program(dut, words):
    for addr, w in enumerate(words):
        await set_cmd(dut, 0xA, addr)
        await set_cmd(dut, 0xB, w & 0xFF)
        await set_cmd(dut, 0xC, (w >> 8) & 0xFF)
        await pulse_imem_we(dut)


async def push_host(dut, data: int, last: bool = False, cmd: bool = False):
    word = (data & 0xFF) | ((1 if last else 0) << 8) | ((1 if cmd else 0) << 9)
    await set_cmd(dut, 0xD, word & 0xFF)
    await set_cmd(dut, 0xE, (word >> 8) & 0x3)
    await pulse_host_wr(dut)


async def load_cfg_bytes(dut, mapping: dict[int, int]):
    """Write config bytes via CFG_ADDR/CFG_WR (edge-pulsed)."""
    for addr, val in sorted(mapping.items()):
        await set_cmd(dut, 0x9, addr & 0xFF)
        await set_cmd(dut, 0xF, val & 0xFF)
        await set_cmd(dut, 0x0, 0)  # drop nibble so next 0xF edges


async def load_default_cfg(dut, cfg: dict | None = None, enable_mask: int = 1):
    blob = dict_to_bytes(0, cfg or DEFAULT_CFG, enable_mask=None)
    # Context bytes first while disabled, then ENABLE.
    for addr, val in sorted(blob.items()):
        if addr == 0x00:
            continue
        await set_cmd(dut, 0x9, addr)
        await set_cmd(dut, 0xF, val)
        await set_cmd(dut, 0x0, 0)
    await set_cmd(dut, 0x9, 0x00)
    await set_cmd(dut, 0xF, enable_mask & 3)
    await set_cmd(dut, 0x0, 0)


async def cfg_read(dut, addr: int) -> int:
    await set_cmd(dut, 0x9, addr & 0xFF)
    await set_cmd(dut, 0x8, 0)
    await set_cmd(dut, 0x0, 0)  # allow latch after cfg_re
    await RisingEdge(dut.clk)
    return int(dut.uo_out.value) & 0xFF


def default_cfg_bytes(cfg: dict | None = None, enable_mask: int = 1) -> dict[int, int]:
    c = dict(cfg or DEFAULT_CFG)
    blob = dict_to_bytes(0, c, enable_mask=None)
    blob[0x00] = enable_mask & 3
    return blob
