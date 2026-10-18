"""Deprecated wrappers — prefer ``tick.host_link.HostLink``.

Kept so one-off scripts importing old names still work; cocotb tests must use
HostLink and must not touch ``ui_in`` / ``uio`` for host access.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick.host_link import (  # noqa: E402
    DEFAULT_CFG,
    HostLink,
    default_cfg_bytes,
)

__all__ = [
    "DEFAULT_CFG",
    "HostLink",
    "default_cfg_bytes",
    "reset_dut",
    "load_program",
    "push_host",
    "load_cfg_bytes",
    "load_default_cfg",
    "cfg_read",
]


async def reset_dut(dut, cycles: int = 5):
    await HostLink(dut).reset(cycles)


async def load_program(dut, words):
    await HostLink(dut).load_program(words)


async def push_host(dut, data: int, last: bool = False, cmd: bool = False):
    await HostLink(dut).push(data, last=last, cmd=cmd)


async def load_cfg_bytes(dut, mapping: dict[int, int]):
    await HostLink(dut).cfg_write_map(mapping)


async def load_default_cfg(dut, cfg: dict | None = None, enable_mask: int = 1):
    await HostLink(dut).load_default_cfg(cfg, enable_mask=enable_mask)


async def cfg_read(dut, addr: int) -> int:
    return await HostLink(dut).cfg_read(addr)
