"""Compare ISS UART TX pin edges against a golden period model (lockstep helper)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model import EventKind, Machine, PinMode, TickSource, assemble


def main() -> int:
    img = assemble((ROOT / "programs" / "uart_tx.asm").read_text())
    m = Machine()
    per = 8.0
    m.load(
        img,
        [
            {
                "per": per,
                "phase": 0,
                "msb_first": False,
                "tick_source": TickSource.TIMER,
                "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
                "events": [{"kind": EventKind.HOST_DATA}],
            }
        ],
    )
    m.host_push(0xA5, last=True)
    trace = []
    for _ in range(250):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else 1
        trace.append(cur)
    start = next(i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0)
    bits = [trace[start + k * 8 + 4] for k in range(10)]
    data = sum(bits[1 + i] << i for i in range(8))
    ok = bits[0] == 0 and bits[9] == 1 and data == 0xA5
    print(f"start={start} bits={bits} data=0x{data:02x} ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
