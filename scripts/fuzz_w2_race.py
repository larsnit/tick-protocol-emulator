#!/usr/bin/env python3
"""1000×500 tick-biased ISS fuzzer + pre-W2 RTL W2-race check.

Prints the seed. For --rtl-pre-w2: swaps in tick_core from 69c7e27^,
runs cocotb queue_order_sweep (expects FAIL at k=7 stranded edges), restores.
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import Machine, PinMode, TickSource
from model.opcodes import (
    AluFn,
    JmpCond,
    XferMode,
    encode_alu,
    encode_jmp,
    encode_ldi,
    encode_set,
    encode_xfer,
)

SEED = 0xA11C_E2E2


def gen_program_tick_biased(rng: random.Random, n: int = 32) -> list[int]:
    words: list[int] = []
    for i in range(n - 1):
        pick = rng.randrange(10)
        if pick < 5:
            words.append(encode_set(True, False, 1, rng.randrange(2)))
        elif pick < 7:
            words.append(encode_xfer(0, rng.randint(1, 8), XferMode.OUT))
        elif pick < 8:
            words.append(encode_ldi(0, rng.randrange(256)))
        elif pick < 9:
            words.append(encode_alu(AluFn.MOV, 0, 0))
        else:
            words.append(encode_jmp(JmpCond.AL, rng.randrange(max(1, i + 1))))
    words.append(encode_jmp(JmpCond.AL, n - 1))
    return words


def iss_fuzz(n_prog: int, n_cyc: int, seed: int) -> int:
    rng = random.Random(seed)
    print(f"seed={seed:#x} programs={n_prog} cycles={n_cyc}")
    failures = 0
    for trial in range(n_prog):
        img = gen_program_tick_biased(rng)
        m = Machine()
        m.load(
            img,
            [
                {
                    "per": 8.0,
                    "phase": 0,
                    "tick_source": TickSource.TIMER,
                    "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
                }
            ],
        )
        try:
            m.run(n_cyc)
            c = m.ctx[0]
            if c.timed_pending is not None and c.timed_active is None:
                print(f"trial {trial}: ISS broke queue invariant")
                failures += 1
        except Exception as e:
            print(f"trial {trial} crash: {e}")
            failures += 1
    print(f"iss_fuzzer: {n_prog - failures}/{n_prog} clean")
    return failures


def rtl_pre_w2_queue_order() -> None:
    core = ROOT / "src" / "tick_core.sv"
    backup = ROOT / "src" / "tick_core.sv.bak"
    shutil.copy2(core, backup)
    pre = subprocess.check_output(["git", "show", "69c7e27^:src/tick_core.sv"], cwd=ROOT)
    # expose dbg_p_kind so current top still elaborates
    text = pre.decode()
    text = text.replace(
        "output wire [1:0]  dbg_a_kind\n",
        "output wire [1:0]  dbg_a_kind,\n    output wire [1:0]  dbg_p_kind\n",
    )
    text = text.replace(
        "assign dbg_a_kind = a_kind;",
        "assign dbg_a_kind = a_kind;\n  assign dbg_p_kind = p_kind;",
    )
    core.write_text(text)
    print("installed pre-W2 tick_core (69c7e27^)")
    try:
        sim_build = ROOT / "test" / "sim_build"
        if sim_build.exists():
            shutil.rmtree(sim_build)
        env = os.environ.copy()
        env["PWD"] = str(ROOT / "test")
        r = subprocess.run(
            ["make", "COCOTB_TEST_MODULES=test_queue_order", f"SRC_DIR={ROOT / 'src'}"],
            cwd=ROOT / "test",
            env=env,
            capture_output=True,
            text=True,
        )
        out = r.stdout + r.stderr
        print("--- cocotb excerpt ---")
        for line in out.splitlines():
            if "k=" in line or "FAIL" in line or "PASS" in line or "Assertion" in line or "TESTS=" in line:
                print(line)
        stranded = "[(9, 0), (25, 1)]" in out
        if stranded and r.returncode != 0:
            print("W2_RACE_DETECTED: pre-W2 RTL k=7 stranded edges [(9,0),(25,1)]")
        else:
            print("ERROR: expected pre-W2 FAIL with stranded k=7 edges")
            raise SystemExit(2)
    finally:
        shutil.move(str(backup), str(core))
        print("restored current tick_core")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--programs", type=int, default=1000)
    ap.add_argument("--cycles", type=int, default=500)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--rtl-pre-w2", action="store_true")
    args = ap.parse_args()
    fails = iss_fuzz(args.programs, args.cycles, args.seed)
    if args.rtl_pre_w2:
        rtl_pre_w2_queue_order()
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
