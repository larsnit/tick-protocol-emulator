"""W5: constrained-random programs for the RTL-implemented subset; ISS smoke."""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import Machine, PinMode, TickSource
from model.opcodes import (
    AluFn,
    JmpCond,
    WaitTc,
    XferMode,
    encode_alu,
    encode_jmp,
    encode_ldi,
    encode_pull,
    encode_set,
    encode_wait,
    encode_xfer,
)

SEED = 0x71C2_0F5A


def gen_program(rng: random.Random, n: int = 24) -> list[int]:
    words = []
    for i in range(n - 1):
        pick = rng.randrange(6)
        if pick == 0:
            words.append(encode_ldi(rng.randrange(4), rng.randrange(256)))
        elif pick == 1:
            words.append(encode_alu(AluFn.MOV, rng.randrange(4), rng.randrange(4)))
        elif pick == 2:
            words.append(encode_set(True, False, 1, rng.randrange(2)))
        elif pick == 3:
            words.append(encode_xfer(0, rng.randint(1, 8), XferMode.OUT))
        elif pick == 4:
            words.append(encode_wait(WaitTc.NONE, 1 << 4))  # WAIT tick
        else:
            words.append(encode_jmp(JmpCond.AL, rng.randrange(max(1, i + 1))))
    words.append(encode_jmp(JmpCond.AL, 0))
    return words


def main() -> int:
    rng = random.Random(SEED)
    print(f"seed={SEED:#x}")
    failures = 0
    n_prog, n_cyc = 200, 300
    for trial in range(n_prog):
        img = gen_program(rng)
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
        # Bias: feed host so PULL-less programs still exercise posts
        for _ in range(4):
            try:
                m.host_push(rng.randrange(256), last=(_ == 3))
            except RuntimeError:
                break
        try:
            m.run(n_cyc)
        except Exception as e:
            print(f"trial {trial} crash: {e}")
            failures += 1
    print(f"fuzzer: {n_prog - failures}/{n_prog} clean")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
