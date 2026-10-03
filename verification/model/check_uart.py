"""Shared UART TX waveform helpers for ISS checkers."""

from __future__ import annotations


def decode_uart_frame(trace: list[int], start: int, per: int) -> int:
    """Decode one 8N1 frame starting at falling-edge index `start`."""
    bits = [trace[start + k * per + per // 2] for k in range(10)]
    if bits[0] != 0 or bits[9] != 1:
        raise AssertionError(f"framing at {start}: {bits}")
    data = 0
    for i, b in enumerate(bits[1:9]):
        data |= b << i
    return data


def falling_edges(trace: list[int]) -> list[int]:
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]
