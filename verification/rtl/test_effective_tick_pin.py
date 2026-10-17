"""RTL: effective tick pin = CLK_LP when CLK_EN && pin-edge (docs §2.1)."""

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
from rtl_bus import load_cfg_bytes, load_program, reset_dut

ALIGN = 1


def _cfg(*, tick_pin: int, clk_lp: int, clk_en: bool):
    return {
        "per": 8.0,
        "tick_source": TickSource.PIN_EDGE,
        "tick_pin": tick_pin,
        "tick_on_rise": True,
        "clk_en": clk_en,
        "cpol": False,
        "cpha": False,
        "dout_lp": 0,
        "din_lp": 0,
        "clk_lp": clk_lp,
        "msb_first": True,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 2, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
        ],
        "events": [{"kind": EventKind.LEVEL_HIGH, "pin": 0}],
    }


@cocotb.test()
async def mts_ecfg_clk_en_ticks_from_clk_lp(dut):
    """MTS ECFG sets CLK_EN; ticks come from CLK_LP, then again from TICK.pin when cleared."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble(
        """
              LDI  r2, 0x03
              MTS  ECFG, r2
        wait: WAIT tick, stop
              LDI  r0, 0x01
              ALU  ADD r1, r0
              JMP  AL, wait
        """
    )
    # tick_pin=LP1 (phys1), clk_lp=LP2 (phys2)
    cfg = _cfg(tick_pin=1, clk_lp=2, clk_en=False)
    n = 48
    # After ECFG: only CLK_LP rises should tick. Early tick_pin rise must not count.
    ext = []
    for cy in range(n):
        v = 0
        if cy >= 8:
            v |= 1 << 1  # tick_pin high (ignored while CLK_EN)
        if cy >= 20:
            v |= 1 << 2  # CLK_LP rise → tick
        ext.append(v)

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
        iss.append((out, oe, m.ctx[0].regs[1]))

    assert iss[12][2] == 0, "tick_pin rise must not count before/without CLK_LP"
    assert max(r[2] for r in iss) >= 1, "CLK_LP rise must tick after ECFG"

    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, cfg, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, img)
    dut.ui_in.value = 1 << 3
    for cy in range(n + ALIGN):
        dut.uio_in.value = ext[min(cy, n - 1)]
        await RisingEdge(dut.clk)
        if cy < ALIGN:
            continue
        i = cy - ALIGN
        io, ie, ir1 = iss[i]
        ro = int(dut.uio_out.value) & 0xFF
        re = int(dut.uio_oe.value) & 0xFF
        assert ie == re and (io & ie) == (ro & re), (
            f"cy={i} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x}) r1={ir1}"
        )
