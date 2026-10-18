"""Transaction-level reference model of the SPI host link."""

from __future__ import annotations

from dataclasses import dataclass, field

from .host_proto import (
    ADDR_CTRL,
    ADDR_ENABLE,
    ADDR_ID,
    ADDR_LINKERR,
    ADDR_RX_COUNT,
    ADDR_TX_FREE,
    CMD_CFG_READ,
    CMD_CFG_WRITE,
    CMD_IMEM_READ,
    CMD_IMEM_WRITE,
    CMD_NOP,
    CMD_PULL,
    CMD_PUSH,
    CTRL_IRQ_EN_ERR,
    CTRL_IRQ_EN_RX,
    CTRL_RUN,
    CTRL_SOFT_RESET,
    ID_VALUE,
    LINKERR_ABORTED,
    LINKERR_BADCMD,
    LINKERR_IMEM_REJECTED,
    LINKERR_OVERFLOW,
    STATUS_ALIVE,
    STATUS_ERR,
    STATUS_IRQ,
    STATUS_LINKERR,
    STATUS_RUN,
    STATUS_RX_AVAIL,
    STATUS_TX_FULL,
)


@dataclass
class HostLinkModel:
    imem: list[int] = field(default_factory=lambda: [0] * 64)
    cfg: dict[int, int] = field(default_factory=dict)
    tx: list[int] = field(default_factory=list)  # host→program 10-bit words
    rx: list[int] = field(default_factory=list)  # program→host
    linkerr: int = 0
    err_cfg: int = 0  # sticky ERR.CFG bit
    err_other: int = 0
    run: int = 0
    irq_en_rx: int = 0
    irq_en_err: int = 0
    soft_reset_count: int = 0

    FIFO_DEPTH = 8

    def enable0(self) -> bool:
        return bool(self.cfg.get(ADDR_ENABLE, 0) & 1)

    def err_any(self) -> bool:
        return bool(self.err_cfg or self.err_other)

    def status(self) -> int:
        rx_avail = 1 if self.rx else 0
        tx_full = 1 if len(self.tx) >= self.FIFO_DEPTH else 0
        link = 1 if self.linkerr else 0
        irq = (self.irq_en_rx and rx_avail) or (
            self.irq_en_err and (self.err_any() or link)
        )
        return (
            (STATUS_RUN if self.run else 0)
            | (STATUS_IRQ if irq else 0)
            | (STATUS_RX_AVAIL if rx_avail else 0)
            | (STATUS_TX_FULL if tx_full else 0)
            | (STATUS_ERR if self.err_any() else 0)
            | (STATUS_LINKERR if link else 0)
            | STATUS_ALIVE
        )

    def soft_reset(self) -> None:
        self.tx.clear()
        self.rx.clear()
        self.soft_reset_count += 1
        # keeps imem + cfg; clears run? Spec: clears queues/FIFOs/PC/flags —
        # RUN is CTRL, not auto-cleared. Leave run as-is unless caller clears.

    def _cfg_write(self, addr: int, data: int) -> None:
        if addr == ADDR_CTRL:
            self.run = 1 if data & CTRL_RUN else 0
            self.irq_en_rx = 1 if data & CTRL_IRQ_EN_RX else 0
            self.irq_en_err = 1 if data & CTRL_IRQ_EN_ERR else 0
            if data & CTRL_SOFT_RESET:
                self.soft_reset()
            return
        if addr == ADDR_LINKERR:
            self.linkerr &= ~(data & 0xF)
            return
        if addr in (ADDR_TX_FREE, ADDR_RX_COUNT, ADDR_ID):
            return  # read-only
        if addr == ADDR_ENABLE or addr >= 0x10:
            # enabled-context reject
            if 0x10 <= addr < 0x30 and self.enable0():
                self.err_cfg = 1
                return
            if 0x30 <= addr < 0x50 and (self.cfg.get(ADDR_ENABLE, 0) & 2):
                self.err_cfg = 1
                return
            self.cfg[addr] = data & 0xFF

    def _cfg_read(self, addr: int) -> int:
        if addr == ADDR_CTRL:
            return (
                (CTRL_RUN if self.run else 0)
                | (CTRL_IRQ_EN_RX if self.irq_en_rx else 0)
                | (CTRL_IRQ_EN_ERR if self.irq_en_err else 0)
            )
        if addr == ADDR_TX_FREE:
            return self.FIFO_DEPTH - len(self.tx)
        if addr == ADDR_RX_COUNT:
            return len(self.rx)
        if addr == ADDR_LINKERR:
            return self.linkerr & 0xF
        if addr == ADDR_ID:
            return ID_VALUE
        return self.cfg.get(addr, 0) & 0xFF

    def _push_word(self, data: int, *, last: bool, cmd: bool) -> None:
        if len(self.tx) >= self.FIFO_DEPTH:
            self.linkerr |= LINKERR_OVERFLOW
            return
        w = (data & 0xFF) | ((1 if last else 0) << 8) | ((1 if cmd else 0) << 9)
        self.tx.append(w)

    def apply(
        self,
        mosi: list[int],
        *,
        abort_after_bits: int | None = None,
    ) -> list[int]:
        """Apply one CS frame. Returns MISO bytes (same length as MOSI consumed).

        abort_after_bits: if set, CS rises after that many bits (partial byte
        discarded; open multi-byte unit → ABORTED).
        """
        miso: list[int] = []
        if not mosi:
            return miso

        total_bits = len(mosi) * 8
        if abort_after_bits is not None:
            total_bits = min(total_bits, abort_after_bits)

        def take_byte(i: int) -> int | None:
            if (i + 1) * 8 > total_bits:
                return None  # partial
            return mosi[i] & 0xFF

        status = self.status()
        cmd_b = take_byte(0)
        if cmd_b is None:
            return [status]  # aborted mid-CMD → discard
        miso.append(status)

        i = 1
        unit_open = False
        hold_valid = False
        hold_data = 0
        push_cmd = False
        push_last_en = False

        def abort_rest():
            nonlocal unit_open, hold_valid
            if hold_valid:
                self._push_word(hold_data, last=push_last_en, cmd=push_cmd)
                hold_valid = False
            if unit_open:
                self.linkerr |= LINKERR_ABORTED
                unit_open = False

        if cmd_b == CMD_NOP:
            abort_rest()
            return miso

        if cmd_b == CMD_CFG_WRITE:
            addr_b = take_byte(i)
            if addr_b is None:
                abort_rest()
                return miso
            miso.append(0)
            i += 1
            addr = addr_b
            while True:
                d = take_byte(i)
                if d is None:
                    break
                miso.append(0)
                self._cfg_write(addr, d)
                addr = (addr + 1) & 0xFF
                i += 1
            abort_rest()
            return miso

        if cmd_b == CMD_CFG_READ:
            addr_b = take_byte(i)
            if addr_b is None:
                abort_rest()
                return miso
            miso.append(0)
            i += 1
            dummy = take_byte(i)
            if dummy is None:
                abort_rest()
                return miso
            miso.append(0)
            i += 1
            addr = addr_b
            while True:
                d = take_byte(i)
                if d is None:
                    break
                miso.append(self._cfg_read(addr))
                addr = (addr + 1) & 0xFF
                i += 1
            abort_rest()
            return miso

        if cmd_b == CMD_IMEM_WRITE:
            addr_b = take_byte(i)
            if addr_b is None:
                abort_rest()
                return miso
            miso.append(0)
            i += 1
            addr = addr_b & 0x3F
            hi = None
            while True:
                d = take_byte(i)
                if d is None:
                    if hi is not None:
                        unit_open = True
                    break
                miso.append(0)
                if hi is None:
                    hi = d
                    unit_open = True
                else:
                    if self.enable0():
                        self.linkerr |= LINKERR_IMEM_REJECTED
                    else:
                        self.imem[addr] = ((hi & 0xFF) << 8) | (d & 0xFF)
                    addr = (addr + 1) & 0x3F
                    hi = None
                    unit_open = False
                i += 1
            abort_rest()
            return miso

        if cmd_b == CMD_IMEM_READ:
            addr_b = take_byte(i)
            if addr_b is None:
                abort_rest()
                return miso
            miso.append(0)
            i += 1
            if self.enable0():
                self.linkerr |= LINKERR_IMEM_REJECTED
                abort_rest()
                return miso
            dummy = take_byte(i)
            if dummy is None:
                abort_rest()
                return miso
            miso.append(0)
            i += 1
            addr = addr_b & 0x3F
            phase = 0  # 0=HI, 1=LO
            while True:
                d = take_byte(i)
                if d is None:
                    if phase == 1:
                        unit_open = True
                    break
                w = self.imem[addr] & 0xFFFF
                if phase == 0:
                    miso.append((w >> 8) & 0xFF)
                    phase = 1
                    unit_open = True
                else:
                    miso.append(w & 0xFF)
                    addr = (addr + 1) & 0x3F
                    phase = 0
                    unit_open = False
                i += 1
            abort_rest()
            return miso

        if (cmd_b & 0xFC) == CMD_PUSH:
            push_cmd = bool(cmd_b & 0x02)
            push_last_en = bool(cmd_b & 0x01)
            while True:
                d = take_byte(i)
                if d is None:
                    break
                miso.append(0)
                if hold_valid:
                    self._push_word(hold_data, last=False, cmd=push_cmd)
                hold_data = d
                hold_valid = True
                i += 1
            abort_rest()  # flushes hold with LAST
            return miso

        if cmd_b == CMD_PULL:
            dummy = take_byte(i)
            if dummy is None:
                abort_rest()
                return miso
            miso.append(0)
            i += 1
            phase = 0
            lat_valid = False
            lat_tag = 0
            lat_data = 0
            while True:
                d = take_byte(i)
                if d is None:
                    if phase == 1:
                        unit_open = True  # mid-pair: keep entry
                    break
                if phase == 0:
                    if self.rx:
                        lat_valid = True
                        lat_tag = (self.rx[0] >> 8) & 3
                        lat_data = self.rx[0] & 0xFF
                        miso.append(0x80 | lat_tag)
                    else:
                        lat_valid = False
                        miso.append(0x00)
                    phase = 1
                    unit_open = True
                else:
                    miso.append(lat_data if lat_valid else 0)
                    if lat_valid and self.rx:
                        self.rx.pop(0)
                    phase = 0
                    unit_open = False
                i += 1
            abort_rest()
            return miso

        # unknown
        self.linkerr |= LINKERR_BADCMD
        while take_byte(i) is not None:
            miso.append(0)
            i += 1
        abort_rest()
        return miso
