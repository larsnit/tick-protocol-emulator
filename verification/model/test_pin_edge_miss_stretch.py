"""Pin-edge timed posts arm the timer so MISS/STRETCH can fire (docs §2 rules 4–5)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import Machine, MissPolicy, PinMode, TickSource, assemble


def test_pin_edge_xfer_miss_stretch_holds_clk_lp():
    """After a pin-edge XFER drains, the next edge with empty queue stretches CLK_LP.

    Timed posts must start the timer even when tick source is pin-edge: MISS is
    gated on timer_run (docs rule 5), and stretch is how an I2C target holds SCL.
    """
    m = Machine()
    m.load(
        assemble(
            """
            LDI   r0, 0xA5
            XFER  r0, 1, out
            hang: JMP AL, hang
            """
        ),
        [
            {
                "per": 16.0,
                "tick_source": TickSource.PIN_EDGE,
                "tick_pin": 1,
                "tick_on_rise": False,
                "clk_en": False,
                "clk_lp": 1,
                "dout_lp": 0,
                "din_lp": 2,
                "miss_policy": MissPolicy.STRETCH,
                "pins": [
                    {"physical": 2, "mode": PinMode.OPENDRAIN, "idle": 1},
                    {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1},
                    {"physical": 5, "mode": PinMode.INPUT, "idle": 1},
                    {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
                ],
            }
        ],
    )
    # Square-wave phys0 (tick LP1) on falling edges after sync settle.
    for cy in range(40):
        bit = 1 if (cy // 2) % 2 else 0
        m.phys_ext = [bit, 0, 0, 0, 0, 0, 0, 0]
        m.step()
        if m.ctx[0].stretching:
            break
    assert m.ctx[0].timer_running, "timed XFER post must arm timer under pin-edge"
    assert m.ctx[0].stretching, "empty queue + pin tick + timer_run → MISS stretch"
    c = m.ctx[0]
    assert (c.drive_oe & (1 << 1)) and ((c.drive_val >> 1) & 1) == 0
