#!/usr/bin/env python3
"""Minimize a REPRO_IMG that mismatches ISS vs a second pin oracle.

Oracles:
  time_skew=-1  — ISS with TIME read back-dated by 1 (old RTL MFS TIME bug)
  no_clk_en     — ISS that stores ECFG but clears CLK_EN/CPHA/CPOL after MTS
                  (models Stage 2b RTL: isa.md §4 — engine clock is Stage 2d)

Also usable as a delete/binary-search skeleton for cocotb pin traces.

Usage:
  PYTHONPATH=sw python3 verification/rtl/minimize_fuzz_mismatch.py
  PYTHONPATH=sw python3 verification/rtl/minimize_fuzz_mismatch.py --oracle no_clk_en
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, PinMode, TickSource  # noqa: E402
from tick.isa import JmpCond, Op, Spr, XferMode, decode, encode_jmp  # noqa: E402
from tick.isa import encode_ldi, encode_mts, encode_xfer  # noqa: E402


def pin_trace(img, cfg, n_cyc, ext, host, time_skew: int = 0, no_clk_en: bool = False):
    """ISS pin trace with optional TIME skew or CLK_EN-ignored (RTL Stage 2b)."""
    m = Machine()
    m.load(img, [cfg])
    for hw in host:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))

    if time_skew != 0:
        orig = m._read_spr

        def skewed(c, spr):
            if spr == Spr.TIME_L:
                c.time_latch = (c.time + time_skew) & 0xFFFF
                return c.time_latch & 0xFF
            if spr == Spr.TIME_H:
                return (c.time_latch >> 8) & 0xFF
            return orig(c, spr)

        m._read_spr = skewed  # type: ignore[method-assign]

    if no_clk_en:
        orig_w = m._write_spr

        def store_ecfg_no_engine_clock(c, spr, val):
            orig_w(c, spr, val)
            if spr == Spr.ECFG:
                # Match RTL until Stage 2d: fields visible, ticks not split, no CLK drive.
                c.ecfg_clk_en = False
                c.ecfg_cpha = False
                c.ecfg_cpol = False

        m._write_spr = store_ecfg_no_engine_clock  # type: ignore[method-assign]

    trace = []
    for cy in range(n_cyc):
        m.phys_ext = [(ext[min(cy, len(ext) - 1)] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        trace.append((out, oe))
    return trace


def first_mismatch(img, cfg, n_cyc, ext, host, oracle: str = "time_skew"):
    ta = pin_trace(img, cfg, n_cyc, ext, host)
    if oracle == "time_skew":
        tb = pin_trace(img, cfg, n_cyc, ext, host, time_skew=-1)
    elif oracle == "no_clk_en":
        tb = pin_trace(img, cfg, n_cyc, ext, host, no_clk_en=True)
    else:
        raise ValueError(oracle)
    for i, ((oa, oea), (ob, oeb)) in enumerate(zip(ta, tb)):
        if oea != oeb or (oa & oea) != (ob & oeb):
            return i, (oa, oea), (ob, oeb)
    return None, None, None


def minimize(img, cfg, ext, host, n_cyc, oracle: str):
    best = list(img)
    cy, _, _ = first_mismatch(best, cfg, n_cyc, ext, host, oracle=oracle)
    assert cy is not None, f"no {oracle} pin mismatch to minimize"

    lo, hi = 2, len(best)
    while lo < hi:
        mid = (lo + hi) // 2
        cand = best[:mid]
        cand[-1] = encode_jmp(JmpCond.AL, len(cand) - 1)
        c2, _, _ = first_mismatch(cand, cfg, n_cyc, ext, host, oracle=oracle)
        if c2 is not None:
            best, hi = cand, mid
        else:
            lo = mid + 1

    changed = True
    while changed:
        changed = False
        for i in range(len(best) - 1):
            cand = best[:i] + best[i + 1 :]
            if len(cand) < 2:
                continue
            out = []
            for w in cand:
                d = decode(w)
                if d["op"] == Op.JMP and d["addr"] >= len(cand):
                    out.append(encode_jmp(JmpCond.AL, max(0, len(out))))
                else:
                    out.append(w)
            out[-1] = encode_jmp(JmpCond.AL, len(out) - 1)
            c2, _, _ = first_mismatch(out, cfg, n_cyc, ext, host, oracle=oracle)
            if c2 is not None:
                best = out
                changed = True
                break
    return best


def _trial46():
    """Fuzz trial 46 (seed 0xb22df2b2): MTS ECFG from r1=0xff enables CLK_EN."""
    n_cyc = 268
    img = [
        0x6100, 0x4416, 0x3508, 0x6120, 0x4416, 0x3514, 0x6140, 0x441a, 0x3520,
        0x6160, 0x441a, 0x352c, 0x6180, 0x441e, 0x3538, 0x61a0, 0x441e, 0x3544,
        0x61c0, 0x4422, 0x3550, 0x61e0, 0x4422, 0x355c, 0x4001, 0x840, 0x1c00,
        0x1000, 0x8200, 0xa6c0, 0x6290, 0x3c70, 0x6250, 0xc40, 0x7800, 0x1600,
        0x3590, 0x8100, 0x5420, 0x309c,
    ]
    cfg = {
        "per": 4.0,
        "phase": 0,
        "msb_first": True,
        "clk_en": False,
        "cpol": False,
        "cpha": False,
        "dout_lp": 2,
        "din_lp": 3,
        "tick_source": TickSource.TIMER,
        "default_byte": 40,
        "pins": [
            {"physical": 4, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": True},
            {"physical": 2, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": True},
            {"physical": 1, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
            {"physical": 6, "mode": PinMode.INPUT, "idle": 0, "glitch_filter": False},
        ],
        "events": [{"kind": EventKind.HOST_DATA} for _ in range(4)],
    }
    host = [0x345, 0x7a, 0x12b, 0x20e, 0x368, 0xcb, 0x1bf, 0x100]
    ext = [
        172, 225, 176, 16, 57, 217, 184, 237, 92, 157, 80, 221, 113, 61, 112, 237,
        249, 209, 181, 13, 188, 52, 133, 63, 133, 232, 137, 191, 17, 92, 160, 125,
        204, 104, 20, 197, 72, 54, 164, 168, 187, 213, 99, 109, 66, 96, 28, 101, 40,
        0, 81, 38, 212, 213, 133, 188, 9, 35, 252, 193, 0, 14, 21, 157, 241, 161, 73,
        189, 240, 93, 233, 213, 107, 252, 105, 245, 153, 96, 176, 152, 12, 1, 21, 13,
        236, 75, 105, 237, 200, 253, 9, 217, 217, 113, 32, 68, 51, 85, 96, 33, 201,
        201, 144, 56, 60, 189, 117, 97, 237, 97, 200, 216, 28, 160, 221, 192, 141,
        140, 76, 52, 152, 205, 205, 177, 129, 57, 56, 240, 171, 129, 224, 63, 197,
        244, 72, 96, 21, 20, 49, 9, 83, 20, 236, 233, 37, 96, 211, 183, 89, 109, 84,
        92, 153, 32, 148, 157, 112, 9, 192, 200, 186, 77, 93, 88, 136, 132, 72, 76,
        0, 162, 123, 229, 137, 41, 232, 36, 192, 69, 24, 24, 201, 149, 184, 249, 93,
        14, 223, 113, 34, 208, 131, 193, 225, 109, 76, 144, 77, 201, 152, 18, 164,
        101, 57, 196, 68, 223, 33, 12, 31, 245, 69, 69, 44, 49, 240, 24, 220, 140,
        235, 184, 216, 36, 64, 216, 105, 112, 65, 124, 28, 192, 33, 44, 108, 9, 172,
        108, 233, 105, 5, 241, 20, 91, 61, 248, 206, 137, 25, 29, 158, 33, 153, 146,
        189, 12, 113, 13, 83, 68, 17, 106, 4, 189, 202, 125, 76, 237, 40, 5,
    ]
    return img, cfg, ext, host, n_cyc


def _minimal_clk_en():
    img = [
        encode_ldi(1, 0x0F),
        encode_mts(1, Spr.ECFG),
        encode_xfer(0, 1, XferMode.IN),
        encode_jmp(JmpCond.AL, 3),
    ]
    cfg = {
        "per": 4.0,
        "phase": 0,
        "msb_first": True,
        "clk_en": False,
        "cpol": False,
        "cpha": False,
        "dout_lp": 2,
        "din_lp": 3,
        "tick_source": TickSource.TIMER,
        "default_byte": 0,
        "pins": [
            {"physical": 4, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
            {"physical": 2, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
            {"physical": 1, "mode": PinMode.PUSHPULL, "idle": 1, "glitch_filter": False},
            {"physical": 6, "mode": PinMode.INPUT, "idle": 0, "glitch_filter": False},
        ],
        "events": [{"kind": EventKind.HOST_DATA} for _ in range(4)],
    }
    return img, cfg, [0] * 40, [0x300], 24


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--oracle",
        choices=("time_skew", "no_clk_en"),
        default="no_clk_en",
        help="Second pin oracle (default: no_clk_en for trial46 class)",
    )
    ap.add_argument(
        "--case",
        choices=("trial46", "minimal"),
        default="minimal",
    )
    args = ap.parse_args()

    if args.case == "trial46":
        img, cfg, ext, host, n_cyc = _trial46()
    else:
        img, cfg, ext, host, n_cyc = _minimal_clk_en()

    cy, iss, rtl_model = first_mismatch(img, cfg, n_cyc, ext, host, oracle=args.oracle)
    print(f"FULL first_mismatch cy={cy} ISS={iss} oracle={args.oracle}={rtl_model}")

    if cy is None:
        return

    short = minimize(img, cfg, ext, host, n_cyc, oracle=args.oracle)
    cy2, a2, b2 = first_mismatch(short, cfg, n_cyc, ext, host, oracle=args.oracle)
    print(f"MIN_LEN={len(short)} cy={cy2}")
    print(f"MIN_IMG={[hex(w) for w in short]}")
    for i, w in enumerate(short):
        print(f"  {i:02d}: {w:#06x} {decode(w)}")
    print(f"MIN ISS={a2} oracle={b2}")


if __name__ == "__main__":
    main()
