"""WS2812 ISS checker: MSB-first bits with 1/2 vs 2/1 high/low tick pattern."""

from __future__ import annotations


def decode_ws2812_byte(trace: list[int], per: int, start: int | None = None) -> int:
    """Decode one byte from a dense pin trace. High run of ~2*per → 1, ~1*per → 0."""
    i = start if start is not None else next(
        (k for k in range(1, len(trace)) if trace[k - 1] == 0 and trace[k] == 1),
        None,
    )
    if i is None:
        raise AssertionError("no rising edge")
    value = 0
    for bit_i in range(8):
        # measure high run
        if i >= len(trace) or trace[i] != 1:
            raise AssertionError(f"bit {bit_i}: expected high at {i}")
        j = i
        while j < len(trace) and trace[j] == 1:
            j += 1
        high = j - i
        # then low run
        k = j
        while k < len(trace) and trace[k] == 0:
            k += 1
        low = k - j
        # Classify: bit1 ≈ 2 high + 1 low; bit0 ≈ 1 high + 2 low (in PER units)
        if high >= int(1.5 * per):
            bit = 1
        else:
            bit = 0
        value = (value << 1) | bit
        if low < per // 2:
            raise AssertionError(f"bit {bit_i}: low too short ({low})")
        i = k
    return value
