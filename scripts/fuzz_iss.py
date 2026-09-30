"""Constrained-random program generator + ISS lockstep smoke test."""

from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import Machine, PinMode, TickSource, assemble
from model.opcodes import (
    encode_alu,
    encode_jmp,
    encode_ldi,
    encode_set,
    encode_wait,
    AluFn,
    JmpCond,
    WaitTc,
)


def random_program(rng: random.Random, n: int = 16) -> list[int]:
    words = []
    for i in range(n - 1):
        pick = rng.randrange(5)
        if pick == 0:
            words.append(encode_ldi(rng.randrange(4), rng.randrange(256)))
        elif pick == 1:
            words.append(encode_alu(rng.choice(list(AluFn)), rng.randrange(4), rng.randrange(4)))
        elif pick == 2:
            words.append(encode_set(False, False, 1, rng.randrange(2)))
        elif pick == 3:
            words.append(encode_jmp(JmpCond.AL, rng.randrange(max(1, i + 1))))
        else:
            words.append(encode_wait(WaitTc.NONE, 0))  # sleep forever-ish
    words.append(encode_jmp(JmpCond.AL, 0))
    return words


def main() -> int:
    rng = random.Random(0x71C2)
    failures = 0
    for trial in range(50):
        img = random_program(rng)
        m = Machine()
        m.load(
            img,
            [
                {
                    "per": 8.0,
                    "tick_source": TickSource.TIMER,
                    "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
                }
            ],
        )
        try:
            m.run(200)
        except Exception as e:
            print(f"trial {trial} crashed: {e}")
            failures += 1
            continue
        if m.double_drive:
            print(f"trial {trial} double drive")
            failures += 1
    print(f"fuzzer done: {50 - failures}/50 clean")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
