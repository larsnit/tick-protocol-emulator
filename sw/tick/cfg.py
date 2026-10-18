"""Configuration register map (docs/isa.md §2.1) — pack/unpack for ISS and RTL."""

from __future__ import annotations

from typing import Any

from .isa import MissPolicy, PinMode, TickSource

# Shared
ADDR_ENABLE = 0x00
ADDR_CTRL = 0x01
ADDR_TX_FREE = 0x02
ADDR_RX_COUNT = 0x03
ADDR_LINKERR = 0x04
ADDR_ID = 0x05

CTRL_RUN = 1 << 0
CTRL_SOFT_RESET = 1 << 1
CTRL_IRQ_EN_RX = 1 << 2
CTRL_IRQ_EN_ERR = 1 << 3

LINKERR_BADCMD = 1 << 0
LINKERR_OVERFLOW = 1 << 1
LINKERR_IMEM_REJECTED = 1 << 2
LINKERR_ABORTED = 1 << 3

# Context block bases
CTX0_BASE = 0x10
CTX1_BASE = 0x30
CTX_STRIDE = 0x20

# Offsets within a context block
OFF_PINMAP_LO = 0x00
OFF_PINMAP_HI = 0x01
OFF_PINMODE = 0x02
OFF_PINIDLE = 0x03
OFF_ENGINE = 0x04
OFF_CLKCFG = 0x05
OFF_TICK = 0x06
OFF_MISS = 0x07
OFF_DEFAULT = 0x08
OFF_PER_L = 0x09
OFF_PER_M = 0x0A
OFF_PER_H = 0x0B
OFF_PHASE_L = 0x0C
OFF_PHASE_H = 0x0D
OFF_BASE = 0x0E
OFF_BOUND = 0x0F
OFF_EV0_CFG = 0x10
OFF_EV0_TRAP = 0x11
# EV1..EV3 at +2 each
OFF_GLITCH = 0x18

ERR_MISS = 0
ERR_UNDER = 1
ERR_OVERRUN = 2
ERR_ARB = 3
ERR_MAP = 4
ERR_CFG = 5


def ctx_base(ci: int) -> int:
    return CTX0_BASE if ci == 0 else CTX1_BASE


def dict_to_bytes(ci: int, cfg: dict[str, Any], enable_mask: int | None = None) -> dict[int, int]:
    """Produce {abs_addr: byte} for one context dict (Machine.configure style)."""
    base = ctx_base(ci)
    out: dict[int, int] = {}
    if enable_mask is not None:
        out[ADDR_ENABLE] = enable_mask & 3

    pins = cfg.get("pins", [])
    pinmap = [i & 7 for i in range(4)]
    modes = [0] * 4
    idle = [1] * 4
    glitch = 0
    for i, p in enumerate(pins[:4]):
        pinmap[i] = int(p.get("physical", i)) & 7
        modes[i] = int(p.get("mode", PinMode.INPUT)) & 3
        idle[i] = int(p.get("idle", 1)) & 1
        if p.get("glitch_filter"):
            glitch |= 1 << i
    out[base + OFF_PINMAP_LO] = (pinmap[0] & 7) | ((pinmap[1] & 7) << 4)
    out[base + OFF_PINMAP_HI] = (pinmap[2] & 7) | ((pinmap[3] & 7) << 4)
    out[base + OFF_PINMODE] = (
        (modes[0] & 3)
        | ((modes[1] & 3) << 2)
        | ((modes[2] & 3) << 4)
        | ((modes[3] & 3) << 6)
    )
    out[base + OFF_PINIDLE] = (
        (idle[0] & 1) | ((idle[1] & 1) << 1) | ((idle[2] & 1) << 2) | ((idle[3] & 1) << 3)
    )
    out[base + OFF_GLITCH] = glitch & 0xF

    dout = int(cfg.get("dout_lp", 0)) & 3
    din = int(cfg.get("din_lp", 1)) & 3
    clk = int(cfg.get("clk_lp", 2)) & 3
    msb = 1 if cfg.get("msb_first", True) else 0
    clk_en = 1 if cfg.get("clk_en", False) else 0
    out[base + OFF_ENGINE] = dout | (din << 2) | (clk << 4) | (msb << 6) | (clk_en << 7)
    out[base + OFF_CLKCFG] = (1 if cfg.get("cpol", False) else 0) | (
        (1 if cfg.get("cpha", False) else 0) << 1
    )

    src = int(cfg.get("tick_source", TickSource.TIMER)) & 1
    rise = 1 if cfg.get("tick_on_rise", True) else 0
    tpin = int(cfg.get("tick_pin", 2)) & 3
    out[base + OFF_TICK] = src | (rise << 1) | (tpin << 2)

    pol = int(cfg.get("miss_policy", MissPolicy.FLAG)) & 3
    mvec = int(cfg.get("miss_vector", 0)) & 0x3F
    out[base + OFF_MISS] = pol | (mvec << 2)
    out[base + OFF_DEFAULT] = int(cfg.get("default_byte", 0xFF)) & 0xFF

    per = cfg.get("per", 8.0)
    per_fp = int(round(per * 16)) if isinstance(per, float) else int(per)
    out[base + OFF_PER_L] = per_fp & 0xFF
    out[base + OFF_PER_M] = (per_fp >> 8) & 0xFF
    out[base + OFF_PER_H] = (per_fp >> 16) & 0xF
    phase = int(cfg.get("phase", 0))
    out[base + OFF_PHASE_L] = phase & 0xFF
    out[base + OFF_PHASE_H] = (phase >> 8) & 0xFF
    out[base + OFF_BASE] = int(cfg.get("base", 0)) & 0x3F
    bound = int(cfg.get("bound", 64))
    out[base + OFF_BOUND] = 0 if bound >= 64 else (bound & 0x3F)

    events = cfg.get("events", [])
    for ei in range(4):
        e = events[ei] if ei < len(events) else {}
        # Default EV0 to HOST_DATA (6): matches uart_*.asm / Stage 2b soft WAIT bit0.
        # Other selectors default to LEVEL_HIGH (1).
        default_kind = 6 if ei == 0 else 1
        kind = int(e.get("kind", default_kind)) & 0xF
        pin = int(e.get("pin", 0)) & 3
        qual = int(e.get("qual_pin", 1)) & 3
        out[base + OFF_EV0_CFG + 2 * ei] = kind | (pin << 4) | (qual << 6)
        trap = 1 if e.get("trap", False) else 0
        vec = int(e.get("vector", 0)) & 0x3F
        latch = 1 if e.get("latched", False) else 0
        out[base + OFF_EV0_TRAP + 2 * ei] = trap | (vec << 1) | (latch << 7)

    return out
