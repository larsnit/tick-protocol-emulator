"""Effective tick pin: CLK_LP when CLK_EN && pin-edge, else TICK.pin (docs §2.1)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, PinMode, TickSource, assemble


def _cfg(*, tick_pin: int, clk_lp: int, clk_en: bool = False):
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


def test_mts_ecfg_clk_en_uses_clk_lp_not_tick_pin():
    """MTS ECFG sets CLK_EN while TICK.pin ≠ CLK_LP → ticks from CLK_LP.

    Clearing CLK_EN → ticks from TICK.pin again. No ERR.CFG for the mismatch.
    """
    # WAIT tick, stop — each pin tick completes one wait then we re-post.
    img = assemble(
        """
        wait: WAIT tick, stop
              LDI  r0, 0x01
              ALU  ADD r1, r0
              JMP  AL, wait
        """
    )
    # tick_pin=LP1 (phys1), clk_lp=LP2 (phys2) — deliberately different.
    m = Machine()
    m.load(img, [_cfg(tick_pin=1, clk_lp=2, clk_en=False)])
    assert m.ctx[0].tick_pin == 1
    assert m.ctx[0].clk_lp == 2
    assert not m.ctx[0].cfg_err

    # Settle sync; then toggle only TICK.pin (phys1) — should tick.
    m.phys_ext = [0, 0, 0, 1, 1, 1, 1, 1]
    for _ in range(8):
        m.step()
    before = m.ctx[0].regs[1]
    m.phys_ext[1] = 1  # rise on tick_pin
    for _ in range(4):
        m.step()
    assert m.ctx[0].regs[1] == (before + 1) & 0xFF

    # Enable CLK_EN via MTS ECFG (MSB=1 so nibble=0b0011 → bits CLK_EN|MSB).
    # ECFG: bit0 MSB, bit1 CLK_EN, bit2 CPHA, bit3 CPOL.
    img2 = assemble(
        """
              LDI  r2, 0x03
              MTS  ECFG, r2
        wait: WAIT tick, stop
              LDI  r0, 0x01
              ALU  ADD r1, r0
              JMP  AL, wait
        """
    )
    m2 = Machine()
    m2.load(img2, [_cfg(tick_pin=1, clk_lp=2, clk_en=False)])
    m2.phys_ext = [0, 0, 0, 1, 1, 1, 1, 1]
    for _ in range(8):
        m2.step()  # LDI + MTS
    assert m2.ctx[0].ecfg_clk_en
    assert m2.ctx[0].tick_pin == 1  # field not rewritten
    assert not m2.ctx[0].cfg_err

    before = m2.ctx[0].regs[1]
    # Rise on TICK.pin only — must NOT tick (CLK_EN uses CLK_LP).
    m2.phys_ext[1] = 1
    for _ in range(4):
        m2.step()
    assert m2.ctx[0].regs[1] == before

    # Both-edge tick on CLK_LP (phys2).
    m2.phys_ext[2] = 1
    for _ in range(4):
        m2.step()
    assert m2.ctx[0].regs[1] == (before + 1) & 0xFF

    # Clear CLK_EN → TICK.pin wins again.
    img3 = assemble(
        """
              LDI  r2, 0x01
              MTS  ECFG, r2
        wait: WAIT tick, stop
              LDI  r0, 0x01
              ALU  ADD r1, r0
              JMP  AL, wait
        """
    )
    m3 = Machine()
    m3.load(img3, [_cfg(tick_pin=1, clk_lp=2, clk_en=True)])
    m3.phys_ext = [0, 1, 0, 1, 1, 1, 1, 1]
    for _ in range(8):
        m3.step()
    assert not m3.ctx[0].ecfg_clk_en
    before = m3.ctx[0].regs[1]
    m3.phys_ext[2] = 1  # CLK_LP edge — ignored when CLK_EN off (rise-only on pin1)
    for _ in range(4):
        m3.step()
    assert m3.ctx[0].regs[1] == before
    m3.phys_ext[1] = 0
    for _ in range(4):
        m3.step()
    m3.phys_ext[1] = 1  # rise on TICK.pin
    for _ in range(4):
        m3.step()
    assert m3.ctx[0].regs[1] == (before + 1) & 0xFF
