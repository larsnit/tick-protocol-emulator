"""ISS↔RTL random comparison: config + pin ops, cycle-accurate uio out/oe."""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import Machine, PinMode, TickSource
from tick.cfg import dict_to_bytes
from tick.isa import (
    AluFn,
    JmpCond,
    WaitTc,
    XferMode,
    encode_alu,
    encode_in,
    encode_jmp,
    encode_ldi,
    encode_set,
    encode_wait,
    encode_xfer,
)
from rtl_bus import load_cfg_bytes, load_program, reset_dut

DEFAULT_SEED = 0xA11C_E2E2
ENV_SEED = "TICK_RTL_FUZZ_SEED"
ENV_N_PROG = "TICK_RTL_FUZZ_N"
ENV_N_CYC = "TICK_RTL_FUZZ_CYC"
N_PROG = 50
N_WORDS = 24
N_CYC = 80
ALIGN = 1

MODE_NAMES = {
    PinMode.INPUT: "input",
    PinMode.PUSHPULL: "pushpull",
    PinMode.OPENDRAIN: "opendrain",
}


def _seed() -> int:
    raw = os.environ.get(ENV_SEED)
    if raw is None or raw == "":
        return DEFAULT_SEED
    return int(raw, 0)


def _n_prog() -> int:
    raw = os.environ.get(ENV_N_PROG)
    if raw is None or raw == "":
        return N_PROG
    return int(raw, 0)


def _n_cyc() -> int:
    raw = os.environ.get(ENV_N_CYC)
    if raw is None or raw == "":
        return N_CYC
    return int(raw, 0)


def gen_legal_cfg(rng: random.Random) -> dict:
    """Random but legal single-context config (unique pin map, timer ticks)."""
    phys = list(range(8))
    rng.shuffle(phys)
    pinmap = phys[:4]
    modes = []
    pins = []
    for i in range(4):
        mode = rng.choice([PinMode.INPUT, PinMode.PUSHPULL, PinMode.OPENDRAIN])
        modes.append(mode)
        pins.append(
            {
                "physical": pinmap[i],
                "mode": mode,
                "idle": rng.randrange(2),
                "glitch_filter": bool(rng.randrange(2)),
            }
        )
    driveable = [i for i, m in enumerate(modes) if m != PinMode.INPUT]
    if not driveable:
        # Ensure at least one driveable pin for XFER/SET coverage.
        i = rng.randrange(4)
        modes[i] = PinMode.PUSHPULL
        pins[i]["mode"] = PinMode.PUSHPULL
        driveable = [i]
    dout = rng.choice(driveable)
    din_cands = [i for i in range(4) if i != dout]
    din = rng.choice(din_cands) if din_cands else dout
    return {
        "per": float(rng.choice([4.0, 8.0, 16.0])),
        "phase": 0,
        "msb_first": bool(rng.randrange(2)),
        "dout_lp": dout,
        "din_lp": din,
        "tick_source": TickSource.TIMER,
        "pins": pins,
    }


def gen_program(rng: random.Random, cfg: dict, n: int = N_WORDS) -> list[int]:
    dout = int(cfg["dout_lp"]) & 3
    words: list[int] = []
    for i in range(n - 1):
        pick = rng.randrange(10)
        if pick == 0:
            mask = 1 << rng.randrange(4)
            val = rng.randrange(16) & mask
            words.append(encode_set(False, False, mask, val))  # SET
        elif pick == 1:
            mask = 1 << rng.randrange(4)
            val = rng.randrange(16) & mask
            words.append(encode_set(True, False, mask, val))  # SET.T
        elif pick == 2:
            mask = 1 << rng.randrange(4)
            val = rng.randrange(16) & mask
            words.append(encode_set(False, True, mask, val))  # SET.E
        elif pick == 3:
            mask = 1 << rng.randrange(4)
            val = rng.randrange(16) & mask
            words.append(encode_set(True, True, mask, val))  # SET.T.E
        elif pick == 4:
            words.append(encode_in(False, rng.randrange(4)))  # IN
        elif pick == 5:
            words.append(encode_in(True, rng.randrange(4)))  # IN.T
        elif pick == 6:
            nbits = rng.randint(1, 8)
            mode = rng.choice([XferMode.OUT, XferMode.IN, XferMode.BOTH])
            words.append(encode_xfer(0, nbits, mode))
            _ = dout  # XFER uses configured dout/din
        elif pick == 7:
            words.append(encode_wait(WaitTc.NONE, 1 << 4))
        elif pick == 8:
            words.append(encode_ldi(rng.randrange(4), rng.randrange(256)))
        else:
            words.append(encode_alu(AluFn.MOV, rng.randrange(4), rng.randrange(4)))
        if rng.random() < 0.06:
            words[-1] = encode_jmp(JmpCond.AL, rng.randrange(max(1, i + 1)))
    words.append(encode_jmp(JmpCond.AL, n - 1))
    return words


def _cov_instr(cov: dict, w: int) -> None:
    op = (w >> 12) & 0xF
    if op == 0:
        timed = (w >> 11) & 1
        oe = (w >> 10) & 1
        if timed and oe:
            cov["set_t_e"] += 1
        elif timed:
            cov["set_t"] += 1
        elif oe:
            cov["set_e"] += 1
        else:
            cov["set"] += 1
    elif op == 1:
        if (w >> 11) & 1:
            cov["in_t"] += 1
        else:
            cov["in"] += 1
    elif op == 2:
        cov["wait"] += 1
    elif op == 6:
        cov["xfer"] += 1


def iss_pin_trace(img: list[int], cfg: dict, n_cyc: int, ext: list[int]) -> list[tuple[int, int]]:
    m = Machine()
    m.load(img, [cfg])
    trace = []
    for cy in range(n_cyc):
        m.phys_ext = [(ext[cy] >> p) & 1 for p in range(8)]
        m.step()
        out = 0
        oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        trace.append((out, oe))
    return trace


@cocotb.test()
async def iss_rtl_random_lockstep(dut):
    seed = _seed()
    n_prog = _n_prog()
    n_cyc = _n_cyc()
    rng = random.Random(seed)
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    mismatches = 0
    cov = {
        "set": 0,
        "set_t": 0,
        "set_e": 0,
        "set_t_e": 0,
        "in": 0,
        "in_t": 0,
        "xfer": 0,
        "wait": 0,
    }
    mode_cov = {name: 0 for name in MODE_NAMES.values()}
    try:
        for trial in range(n_prog):
            cfg = gen_legal_cfg(rng)
            for p in cfg["pins"]:
                mode_cov[MODE_NAMES[p["mode"]]] += 1
            img = gen_program(rng, cfg)
            for w in img:
                _cov_instr(cov, w)

            ext = [rng.randrange(256) for _ in range(n_cyc + ALIGN + 2)]
            iss_trace = iss_pin_trace(img, cfg, n_cyc, ext)

            cfg_bytes = dict_to_bytes(0, cfg, enable_mask=None)
            await reset_dut(dut)
            await load_cfg_bytes(dut, cfg_bytes)
            await load_cfg_bytes(dut, {0x00: 0x01})
            await load_program(dut, img)
            dut.ui_in.value = 1 << 3
            dut.uio_in.value = ext[0]

            rtl_trace = []
            for cy in range(n_cyc + ALIGN):
                dut.uio_in.value = ext[min(cy, len(ext) - 1)]
                await RisingEdge(dut.clk)
                out = int(dut.uio_out.value) & 0xFF
                oe = int(dut.uio_oe.value) & 0xFF
                rtl_trace.append((out, oe))

            bad = False
            for i in range(n_cyc):
                i_out, i_oe = iss_trace[i]
                r_out, r_oe = rtl_trace[i + ALIGN]
                if i_oe != r_oe or (i_out & i_oe) != (r_out & r_oe):
                    bad = True
                    dut._log.info(
                        f"trial {trial} cy {i}: ISS=({i_out:#04x},{i_oe:#04x}) "
                        f"RTL=({r_out:#04x},{r_oe:#04x})"
                    )
                    break
            if bad:
                mismatches += 1

        table = (
            f"opcodes={cov} pin_modes={mode_cov} "
            f"n_prog={n_prog} n_cyc={n_cyc}"
        )
        print(f"{ENV_SEED}={seed:#x}")
        print(f"coverage: {table}")
        if mismatches:
            raise AssertionError(
                f"{mismatches}/{n_prog} programs mismatched ISS vs RTL "
                f"(seed={seed:#x}; set {ENV_SEED} to reproduce); {table}"
            )
        dut._log.info(f"PASS {n_prog} programs seed={seed:#x} {table}")
        assert cov["set"] or cov["set_t"] or cov["set_e"]
        assert cov["in"] or cov["in_t"]
        assert mode_cov["pushpull"] > 0
    except AssertionError:
        print(f"{ENV_SEED}={seed:#x}")
        raise
