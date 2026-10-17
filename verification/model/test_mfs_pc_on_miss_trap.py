"""MFS PC on a MISS trap cycle returns the vector, not the pre-trap PC."""

from tick import Machine, MissPolicy, PinMode, TickSource
from tick.isa import JmpCond, Spr, encode_jmp, encode_mfs, encode_set


def test_mfs_pc_on_miss_trap_returns_vector():
    # SET.T arms the timer; after it fires the queue is empty → MISS trap.
    # Vector 10: MFS r1, PC.
    img = [
        encode_set(True, False, 0x1, 0x1),  # 0: SET.T LP0=1 (starts timer)
        encode_jmp(JmpCond.AL, 1),  # 1: hang until MISS
        *[encode_jmp(JmpCond.AL, 2) for _ in range(8)],  # 2..9
        encode_mfs(1, Spr.PC),  # 10
        encode_jmp(JmpCond.AL, 11),
    ]
    cfg = {
        "per": 4.0,
        "phase": 0,
        "tick_source": TickSource.TIMER,
        "miss_policy": MissPolicy.TRAP,
        "miss_vector": 10,
        "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
        "events": [],
    }
    m = Machine()
    m.load(img, [cfg])
    for _ in range(20):
        m.step()
        if m.ctx[0].pc >= 10:
            break
    assert m.ctx[0].pc >= 10, m.ctx[0].pc
    assert m.ctx[0].regs[1] == 10, m.ctx[0].regs[1]
