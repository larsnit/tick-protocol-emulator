"""ISS↔RTL random comparison over the RTL-supported instruction subset."""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import Machine, PinMode, TickSource
from tick.isa import (
    AluFn,
    JmpCond,
    WaitTc,
    XferMode,
    encode_alu,
    encode_jmp,
    encode_ldi,
    encode_set,
    encode_wait,
    encode_xfer,
)
from test_uart_tx import load_program

DEFAULT_SEED = 0xA11C_E2E2
ENV_SEED = "TICK_RTL_FUZZ_SEED"
ENV_N_PROG = "TICK_RTL_FUZZ_N"
N_PROG = 50
N_WORDS = 20
N_CYC = 80
# First rising edge after run aligns ISS step 0 to RTL cycle 1.
ALIGN = 1


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


def gen_program(rng: random.Random, n: int = N_WORDS) -> list[int]:
    words: list[int] = []
    for i in range(n - 1):
        pick = rng.randrange(6)
        if pick == 0:
            words.append(encode_set(True, False, 1, rng.randrange(2)))
        elif pick == 1:
            words.append(encode_xfer(0, rng.randint(1, 8), XferMode.OUT))
        elif pick == 2:
            words.append(encode_wait(WaitTc.NONE, 1 << 4))
        elif pick == 3:
            words.append(encode_ldi(rng.randrange(4), rng.randrange(256)))
        elif pick == 4:
            words.append(encode_alu(AluFn.MOV, rng.randrange(4), rng.randrange(4)))
        else:
            words.append(encode_jmp(JmpCond.AL, rng.randrange(max(1, i + 1))))
    words.append(encode_jmp(JmpCond.AL, n - 1))
    return words


def _cfg():
    return [
        {
            "per": 8.0,
            "phase": 0,
            "msb_first": False,  # match hard-wired RTL
            "tick_source": TickSource.TIMER,
            "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
        }
    ]


def iss_pin_trace(img: list[int], n_cyc: int) -> list[int]:
    m = Machine()
    m.load(img, _cfg())
    trace = []
    for _ in range(n_cyc):
        m.step()
        trace.append(m.phys_drive[0] if m.phys_oe[0] else 1)
    return trace


@cocotb.test()
async def iss_rtl_random_lockstep(dut):
    seed = _seed()
    n_prog = _n_prog()
    rng = random.Random(seed)
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    mismatches = 0
    try:
        for trial in range(n_prog):
            img = gen_program(rng)
            iss_trace = iss_pin_trace(img, N_CYC)

            dut.ena.value = 1
            dut.ui_in.value = 0
            dut.uio_in.value = 0
            dut.rst_n.value = 0
            await ClockCycles(dut.clk, 3)
            dut.rst_n.value = 1
            await ClockCycles(dut.clk, 2)
            await load_program(dut, img)
            dut.ui_in.value = 1 << 3

            rtl_trace = []
            for cy in range(N_CYC + ALIGN):
                await RisingEdge(dut.clk)
                pin = int(dut.uio_out.value) & 1
                oe = int(dut.uio_oe.value) & 1
                rtl_trace.append(pin if oe else 1)

            # Compare ISS[i] to RTL[i + ALIGN]
            bad = False
            for i in range(N_CYC):
                if iss_trace[i] != rtl_trace[i + ALIGN]:
                    bad = True
                    break
            if bad:
                mismatches += 1
                dut._log.info(f"trial {trial} mismatch")

        if mismatches:
            raise AssertionError(
                f"{mismatches}/{n_prog} programs mismatched ISS vs RTL "
                f"(seed={seed:#x}; set {ENV_SEED} to reproduce)"
            )
        dut._log.info(f"PASS {n_prog} programs seed={seed:#x}")
    except AssertionError:
        print(f"{ENV_SEED}={seed:#x}")
        raise
