"""High-level host API for Tick — SPI transport (docs/isa.md Host link).

Encoding lives in ``host_proto`` (no cocotb). This module drives the chip
via ui[0]=SCLK, ui[1]=MOSI, ui[2]=CS_n and samples uo[0]=MISO.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from cocotb.triggers import ClockCycles, RisingEdge, Timer

from . import EventKind, PinMode, TickSource
from .cfg import dict_to_bytes
from .host_proto import (
    ADDR_CTRL,
    ADDR_ENABLE,
    CMD_CFG_READ,
    CMD_CFG_WRITE,
    CTRL_IRQ_EN_ERR,
    CTRL_IRQ_EN_RX,
    CTRL_RUN,
    CTRL_SOFT_RESET,
    STATUS_ALIVE,
    STATUS_ERR,
    STATUS_IRQ,
    STATUS_LINKERR,
    STATUS_RUN,
    STATUS_RX_AVAIL,
    STATUS_TX_FULL,
    decode_pull_pair,
    decode_status,
    encode_cfg_read,
    encode_cfg_write,
    encode_imem_read,
    encode_imem_write,
    encode_nop,
    encode_pull,
    encode_push,
)

# Re-export STATUS bits for tests that imported them from here
STATUS_ALIVE1 = STATUS_ALIVE

DEFAULT_CFG = {
    "per": 8.0,
    "phase": 0,
    "msb_first": False,
    "dout_lp": 0,
    "din_lp": 1,
    "tick_source": TickSource.TIMER,
    "pins": [
        {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1},
        {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 2, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
    ],
    "events": [{"kind": EventKind.HOST_DATA}],
}

# SCLK period in core clocks (f_clk/8); half-period for Timer edges.
_SCLK_DIV = 8
_CS_GAP_CYC = 4


class HostLink:
    """Host-facing API. Tests must not touch ui_in/uio for host access."""

    def __init__(self, dut, *, sclk_div: int = _SCLK_DIV, phase_ns: float = 1.0):
        self.dut = dut
        self.sclk_div = max(8, int(sclk_div))
        self.phase_ns = float(phase_ns)  # sub-cycle offset from clk edge
        self._clk_ns = 20.0  # 50 MHz default; updated on reset if measurable
        self._ctrl = 0  # shadow CTRL (RUN / IRQ enables)
        self._running = False
        self._half_ns = (self.sclk_div * self._clk_ns) / 2.0

    # --- lifecycle ---------------------------------------------------------

    async def reset(self, cycles: int = 5) -> None:
        d = self.dut
        d.ena.value = 1
        d.ui_in.value = 0x04  # CS_n high
        d.uio_in.value = 0
        d.rst_n.value = 0
        await ClockCycles(d.clk, cycles)
        d.rst_n.value = 1
        await ClockCycles(d.clk, 2)
        self._ctrl = 0
        self._running = False
        # CS idle high
        await self._set_pins(cs_n=1, sclk=0, mosi=0)
        await ClockCycles(d.clk, _CS_GAP_CYC)

    async def soft_reset(self) -> None:
        await self._write_ctrl(self._ctrl | CTRL_SOFT_RESET)
        # SOFT_RESET is self-clearing in HW; keep shadow without the pulse bit
        self._ctrl &= ~CTRL_SOFT_RESET

    async def run(self, *, settle: str = "edge") -> None:
        # CTRL.RUN is applied on CS rise inside _xfer (2 clk sync). run_q updates
        # that cycle but the core samples the prior value, so the caller's first
        # RisingEdge is the first execute cycle. uo[2] may already read 1.
        # settle="timer": don't wait RisingEdge in the postamble (lockstep's
        # await_run_rise owns those edges).
        await self._write_ctrl(self._ctrl | CTRL_RUN, settle=settle)
        self._running = True

    async def stop(self) -> None:
        await self._write_ctrl(self._ctrl & ~CTRL_RUN)
        self._running = False

    # --- program memory ----------------------------------------------------

    async def load_program(self, words: Sequence[int]) -> None:
        """Write IMEM from address 0. Temporarily clears ENABLE[0] if set."""
        en = await self.cfg_read(ADDR_ENABLE)
        if en & 1:
            await self.cfg_write(ADDR_ENABLE, en & ~1)
        await self._xfer(encode_imem_write(0, list(words)))
        if en & 1:
            await self.cfg_write(ADDR_ENABLE, en)

    async def read_program(self, count: int, start: int = 0) -> list[int]:
        """Read IMEM. Caller must disable the context first (shared fetch port)."""
        en = await self.cfg_read(ADDR_ENABLE)
        if en & 1:
            raise RuntimeError(
                "read_program: ENABLE[0] is set; disable the context before IMEM_READ"
            )
        mosi = encode_imem_read(start, count)
        miso = await self._xfer(mosi)
        # miso: [STATUS, 0(addr), 0(dummy), HI0, LO0, ...]
        data = miso[3:]
        out: list[int] = []
        for i in range(count):
            hi = data[2 * i] if 2 * i < len(data) else 0
            lo = data[2 * i + 1] if 2 * i + 1 < len(data) else 0
            out.append(((hi & 0xFF) << 8) | (lo & 0xFF))
        return out

    # --- config ------------------------------------------------------------

    async def cfg_write(self, addr: int, data: int) -> None:
        if addr == ADDR_CTRL:
            self._ctrl = data & (CTRL_RUN | CTRL_IRQ_EN_RX | CTRL_IRQ_EN_ERR)
            self._running = bool(data & CTRL_RUN)
        await self._xfer(encode_cfg_write(addr, [data]))

    async def cfg_write_map(self, mapping: Mapping[int, int]) -> None:
        # Group consecutive? Spec allows auto-inc; write each for simplicity
        # or one burst from min if contiguous. Per-addr is fine.
        items = sorted(mapping.items())
        if not items:
            return
        # Burst contiguous runs
        run_addr, run_bytes = items[0][0], [items[0][1]]
        for a, v in items[1:]:
            if a == run_addr + len(run_bytes):
                run_bytes.append(v)
            else:
                if run_addr == ADDR_CTRL and run_bytes:
                    self._ctrl = run_bytes[0] & (
                        CTRL_RUN | CTRL_IRQ_EN_RX | CTRL_IRQ_EN_ERR
                    )
                    self._running = bool(run_bytes[0] & CTRL_RUN)
                await self._xfer(encode_cfg_write(run_addr, run_bytes))
                run_addr, run_bytes = a, [v]
        if run_addr == ADDR_CTRL and run_bytes:
            self._ctrl = run_bytes[0] & (CTRL_RUN | CTRL_IRQ_EN_RX | CTRL_IRQ_EN_ERR)
            self._running = bool(run_bytes[0] & CTRL_RUN)
        await self._xfer(encode_cfg_write(run_addr, run_bytes))

    async def cfg_read(self, addr: int) -> int:
        miso = await self._xfer(encode_cfg_read(addr, 1))
        # [STATUS, 0(addr), 0(dummy), DATA]
        return miso[3] & 0xFF if len(miso) > 3 else 0

    async def load_default_cfg(
        self, cfg: dict | None = None, enable_mask: int = 1
    ) -> None:
        blob = dict_to_bytes(0, cfg or DEFAULT_CFG, enable_mask=None)
        for addr, val in sorted(blob.items()):
            if addr == ADDR_ENABLE:
                continue
            await self.cfg_write(addr, val)
        await self.cfg_write(ADDR_ENABLE, enable_mask & 3)

    # --- host FIFOs --------------------------------------------------------

    async def push(self, data: int, *, last: bool = False, cmd: bool = False) -> None:
        await self._xfer(encode_push([data], cmd=cmd, last=last))

    async def pull(self) -> tuple[int, int] | None:
        miso = await self._xfer(encode_pull(1))
        # [STATUS, 0(dummy), TAGBYTE, DATA]
        if len(miso) < 4:
            return None
        ent = decode_pull_pair(miso[2], miso[3])
        if not ent.valid:
            return None
        return ent.tag, ent.data

    async def status(self) -> int:
        miso = await self._xfer(encode_nop())
        return miso[0] & 0xFF

    # --- SPI bitbang -------------------------------------------------------

    async def _write_ctrl(self, val: int, *, settle: str = "edge") -> None:
        self._ctrl = val & (CTRL_RUN | CTRL_IRQ_EN_RX | CTRL_IRQ_EN_ERR)
        self._running = bool(val & CTRL_RUN)
        await self._xfer(
            encode_cfg_write(ADDR_CTRL, [val & 0xFF]), settle=settle
        )

    async def _set_pins(self, *, cs_n: int, sclk: int, mosi: int) -> None:
        # ui[2]=CS_n, ui[1]=MOSI, ui[0]=SCLK; keep ui[7:3]=0
        self.dut.ui_in.value = ((cs_n & 1) << 2) | ((mosi & 1) << 1) | (sclk & 1)

    def _miso(self) -> int:
        return int(self.dut.uo_out.value) & 1

    async def _xfer(
        self,
        mosi_bytes: Sequence[int],
        *,
        abort_after_bits: int | None = None,
        settle: str = "edge",
    ) -> list[int]:
        """Full-duplex SPI mode 0 transaction; returns MISO bytes.

        If ``abort_after_bits`` is set, raise CS_n after that many MOSI bits
        (partial transaction → LINKERR.ABORTED when mid-unit).
        ``settle``: ``edge`` waits 2 RisingEdges after CS high; ``timer``
        waits 4 clk periods without joining RisingEdge waiters (lockstep).
        """
        d = self.dut
        half = self._half_ns
        phase = self.phase_ns

        # Align to clk, then offset so SCLK edges are sub-cycle
        await RisingEdge(d.clk)
        if phase > 0:
            await Timer(phase, unit="ns")

        # CS setup (≥4 clk; allow 2-flop sync to see CS fall before first SCLK)
        await self._set_pins(cs_n=1, sclk=0, mosi=0)
        await Timer(max(_CS_GAP_CYC, 8) * self._clk_ns, unit="ns")
        await self._set_pins(cs_n=0, sclk=0, mosi=0)
        await Timer(max(_CS_GAP_CYC, 8) * self._clk_ns, unit="ns")

        miso_bytes: list[int] = []
        bits_done = 0
        aborted = False
        for byte in mosi_bytes:
            rx = 0
            for bit in range(8):
                if abort_after_bits is not None and bits_done >= abort_after_bits:
                    aborted = True
                    break
                mosi_bit = (byte >> (7 - bit)) & 1
                # Mode 0: change MOSI on falling path; sample MISO on rising edge
                # after a short settle (chip updates MISO after prior fall).
                await self._set_pins(cs_n=0, sclk=0, mosi=mosi_bit)
                await Timer(half, unit="ns")
                await self._set_pins(cs_n=0, sclk=1, mosi=mosi_bit)
                await Timer(2.0, unit="ns")  # settle; not a clk edge
                rx = (rx << 1) | self._miso()
                await Timer(max(half - 2.0, 1.0), unit="ns")
                bits_done += 1
            if aborted:
                break
            miso_bytes.append(rx & 0xFF)

        # CS hold then idle. After CS rise, wait exactly 2 core clocks so the
        # 2-flop sync + edge detect apply deferred CTRL (incl. RUN). Inter-
        # transaction CS-high ≥4 is enforced on the *next* xfer's setup.
        # Lockstep uses start_run()/await_run_rise so execute cycle 0 is the
        # first RisingEdge after observed uo RUN, not these postamble edges.
        await self._set_pins(cs_n=0, sclk=0, mosi=0)
        await Timer(_CS_GAP_CYC * self._clk_ns, unit="ns")
        await self._set_pins(cs_n=1, sclk=0, mosi=0)
        if settle == "timer":
            # Wait until CTRL.RUN is visible on uo[2], then return on that
            # edge — do not burn extra clocks (those would execute the core
            # before lockstep's cycle-0 RisingEdge).
            for _ in range(8):
                await RisingEdge(d.clk)
                if (int(d.uo_out.value) >> 2) & 1:
                    break
        else:
            await RisingEdge(d.clk)
            await RisingEdge(d.clk)
        return miso_bytes


def default_cfg_bytes(cfg: dict | None = None, enable_mask: int = 1) -> dict[int, int]:
    c = dict(cfg or DEFAULT_CFG)
    blob = dict_to_bytes(0, c, enable_mask=None)
    blob[ADDR_ENABLE] = enable_mask & 3
    return blob
