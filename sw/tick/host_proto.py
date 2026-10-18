"""Pure SPI host-link encoding/decoding (no cocotb). docs/isa.md Host link."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

# Commands
CMD_NOP = 0x00
CMD_CFG_WRITE = 0x01
CMD_CFG_READ = 0x02
CMD_IMEM_WRITE = 0x03
CMD_IMEM_READ = 0x04
CMD_PUSH = 0x10  # | (cmd<<1) | last
CMD_PULL = 0x20

# STATUS bits
STATUS_RUN = 1 << 7
STATUS_IRQ = 1 << 6
STATUS_RX_AVAIL = 1 << 5
STATUS_TX_FULL = 1 << 4
STATUS_ERR = 1 << 3
STATUS_LINKERR = 1 << 2
STATUS_ALIVE = 0b01  # bit1=0 bit0=1

# LINKERR bits
LINKERR_BADCMD = 1 << 0
LINKERR_OVERFLOW = 1 << 1
LINKERR_IMEM_REJECTED = 1 << 2
LINKERR_ABORTED = 1 << 3

# Shared regs
ADDR_ENABLE = 0x00
ADDR_CTRL = 0x01
ADDR_TX_FREE = 0x02
ADDR_RX_COUNT = 0x03
ADDR_LINKERR = 0x04
ADDR_ID = 0x05

CTRL_RUN = 1 << 0
CTRL_SOFT_RESET = 1 << 1
CTRL_IRQ_EN_RX = 1 << 2
CTRL_IRQ_EN_ERR = 1 << 3

ID_VALUE = 0xA1


@dataclass(frozen=True)
class Status:
    raw: int

    @property
    def run(self) -> bool:
        return bool(self.raw & STATUS_RUN)

    @property
    def irq(self) -> bool:
        return bool(self.raw & STATUS_IRQ)

    @property
    def rx_avail(self) -> bool:
        return bool(self.raw & STATUS_RX_AVAIL)

    @property
    def tx_full(self) -> bool:
        return bool(self.raw & STATUS_TX_FULL)

    @property
    def err(self) -> bool:
        return bool(self.raw & STATUS_ERR)

    @property
    def linkerr(self) -> bool:
        return bool(self.raw & STATUS_LINKERR)

    @property
    def alive(self) -> bool:
        return (self.raw & 0x3) == STATUS_ALIVE


@dataclass(frozen=True)
class PullEntry:
    valid: bool
    tag: int
    data: int


def decode_status(b: int) -> Status:
    return Status(b & 0xFF)


def decode_pull_pair(tagbyte: int, data: int) -> PullEntry:
    return PullEntry(
        valid=bool(tagbyte & 0x80),
        tag=tagbyte & 0x3,
        data=data & 0xFF,
    )


def encode_nop() -> list[int]:
    return [CMD_NOP]


def encode_cfg_write(addr: int, data: Sequence[int]) -> list[int]:
    return [CMD_CFG_WRITE, addr & 0xFF, *[d & 0xFF for d in data]]


def encode_cfg_read(addr: int, count: int) -> list[int]:
    # CMD, ADDR, dummy, then `count` clocks for data (MOSI don't-care)
    return [CMD_CFG_READ, addr & 0xFF, 0x00, *([0x00] * count)]


def encode_imem_write(waddr: int, words: Sequence[int]) -> list[int]:
    out = [CMD_IMEM_WRITE, waddr & 0x3F]
    for w in words:
        out.append((w >> 8) & 0xFF)
        out.append(w & 0xFF)
    return out


def encode_imem_read(waddr: int, n_words: int) -> list[int]:
    return [CMD_IMEM_READ, waddr & 0x3F, 0x00, *([0x00] * (2 * n_words))]


def encode_push(data: Sequence[int], *, cmd: bool = False, last: bool = True) -> list[int]:
    """PUSH command: bit1=CMD on all bytes; bit0=LAST on final (via CS rise)."""
    c = CMD_PUSH | ((1 if cmd else 0) << 1) | (1 if last else 0)
    return [c, *[d & 0xFF for d in data]]


def encode_pull(n_entries: int) -> list[int]:
    # CMD, dummy, then 2 bytes per entry
    return [CMD_PULL, 0x00, *([0x00] * (2 * n_entries))]


def xfer_expect_miso_len(mosi: Sequence[int]) -> int:
    """MISO length equals MOSI length (STATUS during CMD, then zeros/data)."""
    return len(mosi)
