"""ISS constrained-random fuzzer: no crashes, queue invariant holds."""

from __future__ import annotations

import os
import random

from tick import Machine, PinMode, TickSource
from tick.isa import (
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

DEFAULT_SEED = 0x71C2_0F5A
N_PROG = 80
N_WORDS = 24
N_CYC = 200
ENV_SEED = "TICK_FUZZ_SEED"


def _seed() -> int:
    raw = os.environ.get(ENV_SEED)
    if raw is None or raw == "":
        return DEFAULT_SEED
    return int(raw, 0)


def gen_program(rng: random.Random, n: int = N_WORDS) -> list[int]:
    """Random program over the RTL-implemented instruction subset."""
    words: list[int] = []
    for i in range(n - 1):
        pick = rng.randrange(7)
        if pick == 0:
            words.append(encode_ldi(rng.randrange(4), rng.randrange(256)))
        elif pick == 1:
            words.append(encode_alu(rng.choice(list(AluFn)), rng.randrange(4), rng.randrange(4)))
        elif pick == 2:
            words.append(encode_set(True, False, 1, rng.randrange(2)))  # SET.T
        elif pick == 3:
            words.append(encode_xfer(0, rng.randint(1, 8), XferMode.OUT))
        elif pick == 4:
            words.append(encode_wait(WaitTc.NONE, 1 << 4))  # WAIT tick
        elif pick == 5:
            words.append(encode_pull(rng.randrange(4), nb=True))
        else:
            words.append(encode_jmp(JmpCond.AL, rng.randrange(max(1, i + 1))))
    words.append(encode_jmp(JmpCond.AL, n - 1))  # hang
    return words


def _cfg() -> list[dict]:
    return [
        {
            "per": 8.0,
            "phase": 0,
            "tick_source": TickSource.TIMER,
            "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
        }
    ]


def test_iss_random_programs_queue_invariant():
    seed = _seed()
    rng = random.Random(seed)
    try:
        for trial in range(N_PROG):
            img = gen_program(rng)
            m = Machine()
            m.load(img, _cfg())
            for i in range(4):
                try:
                    m.host_push(rng.randrange(256), last=(i == 3))
                except RuntimeError:
                    break
            for cy in range(N_CYC):
                m.step()
                c = m.ctx[0]
                if c.timed_pending is not None and c.timed_active is None:
                    raise AssertionError(
                        f"queue invariant broken at trial={trial} cycle={cy}: "
                        f"pending set, active empty (seed={seed:#x})"
                    )
    except Exception:
        print(f"TICK_FUZZ_SEED={seed:#x} (override via env {ENV_SEED})")
        raise
