"""Directed + random SPI host-link tests vs HostLinkModel (docs/isa.md)."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge, Timer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick.host_link import HostLink
from tick.host_link_model import HostLinkModel
from tick.host_proto import (
    ADDR_CTRL,
    ADDR_ENABLE,
    ADDR_ID,
    ADDR_LINKERR,
    ADDR_RX_COUNT,
    ADDR_TX_FREE,
    CMD_CFG_READ,
    CMD_CFG_WRITE,
    CMD_IMEM_WRITE,
    CMD_NOP,
    CMD_PULL,
    CTRL_RUN,
    ID_VALUE,
    LINKERR_ABORTED,
    LINKERR_BADCMD,
    LINKERR_IMEM_REJECTED,
    LINKERR_OVERFLOW,
    decode_status,
    encode_cfg_read,
    encode_cfg_write,
    encode_imem_read,
    encode_imem_write,
    encode_nop,
    encode_pull,
    encode_push,
)

CLK_NS = 20.0


async def _start(dut, *, sclk_div=8, phase_ns=1.0):
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    host = HostLink(dut, sclk_div=sclk_div, phase_ns=phase_ns)
    await host.reset()
    return host


@cocotb.test()
async def host_link_nop_status_alive(dut):
    host = await _start(dut)
    st = decode_status(await host.status())
    assert st.alive
    assert not st.run


@cocotb.test()
async def host_link_cfg_write_read_roundtrip(dut):
    host = await _start(dut)
    await host.cfg_write(0x19, 0x80)  # PER_L
    assert await host.cfg_read(0x19) == 0x80
    assert await host.cfg_read(ADDR_ID) == ID_VALUE


@cocotb.test()
async def host_link_ctrl_run_and_id(dut):
    host = await _start(dut)
    await host.cfg_write(ADDR_CTRL, CTRL_RUN)
    st = decode_status(await host.status())
    assert st.run
    assert (int(dut.uo_out.value) >> 2) & 1  # RUN pin
    await host.stop()
    st = decode_status(await host.status())
    assert not st.run


@cocotb.test()
async def host_link_imem_write_read(dut):
    host = await _start(dut)
    words = [0x1234, 0xABCD, 0x0001]
    await host.load_program(words)
    got = await host.read_program(3)
    assert got == words


@cocotb.test()
async def host_link_imem_write_while_enabled_rejected(dut):
    host = await _start(dut)
    await host.cfg_write(ADDR_ENABLE, 0x01)
    # Direct IMEM_WRITE (bypass load_program's auto-disable)
    await host._xfer(encode_imem_write(0, [0x55AA]))
    link = await host.cfg_read(ADDR_LINKERR)
    assert link & LINKERR_IMEM_REJECTED
    # clear W1C
    await host.cfg_write(ADDR_LINKERR, LINKERR_IMEM_REJECTED)
    assert (await host.cfg_read(ADDR_LINKERR) & LINKERR_IMEM_REJECTED) == 0


@cocotb.test()
async def host_link_push_pull_and_overflow(dut):
    host = await _start(dut)
    for i in range(8):
        await host.push(i, last=(i == 7))
    assert (await host.cfg_read(ADDR_TX_FREE)) == 0
    await host.push(0xFF, last=True)  # overflow
    assert (await host.cfg_read(ADDR_LINKERR)) & LINKERR_OVERFLOW


@cocotb.test()
async def host_link_pull_empty_valid0(dut):
    host = await _start(dut)
    assert await host.pull() is None


@cocotb.test()
async def host_link_badcmd(dut):
    host = await _start(dut)
    await host._xfer([0xEE, 0x00, 0x00])
    assert (await host.cfg_read(ADDR_LINKERR)) & LINKERR_BADCMD


@cocotb.test()
async def host_link_cs_abort_imem_half_word(dut):
    """CS rise after HI only → ABORTED; IMEM unchanged."""
    host = await _start(dut)
    await host.load_program([0])
    # Manual abort mid IMEM_WRITE: CMD, WADDR, HI — then CS rise
    await host._set_pins(cs_n=1, sclk=0, mosi=0)
    await Timer(4 * CLK_NS, unit="ns")
    await host._set_pins(cs_n=0, sclk=0, mosi=0)
    await Timer(4 * CLK_NS, unit="ns")
    # clock out CMD=0x03, WADDR=0, HI=0xBE only (3 bytes), then CS rise
    for byte in [CMD_IMEM_WRITE, 0x00, 0xBE]:
        for bit in range(8):
            b = (byte >> (7 - bit)) & 1
            await host._set_pins(cs_n=0, sclk=0, mosi=b)
            await Timer(host._half_ns, unit="ns")
            await host._set_pins(cs_n=0, sclk=1, mosi=b)
            await Timer(host._half_ns, unit="ns")
    await host._set_pins(cs_n=0, sclk=0, mosi=0)
    await Timer(4 * CLK_NS, unit="ns")
    await host._set_pins(cs_n=1, sclk=0, mosi=0)
    await Timer(4 * CLK_NS, unit="ns")
    assert (await host.cfg_read(ADDR_LINKERR)) & LINKERR_ABORTED
    assert (await host.read_program(1))[0] == 0


@cocotb.test()
async def host_link_random_vs_model(dut):
    """Random command streams vs HostLinkModel; SCLK at /8 and /10, random phase."""
    for sclk_div, phase in [(8, 1.0), (8, 7.0), (10, 3.0)]:
        host = await _start(dut, sclk_div=sclk_div, phase_ns=phase)
        model = HostLinkModel()
        rng = random.Random(0xC0FFEE ^ sclk_div)

        for _ in range(40):
            kind = rng.randrange(6)
            if kind == 0:
                mosi = encode_nop()
            elif kind == 1:
                addr = rng.choice([0x19, 0x1A, ADDR_CTRL, ADDR_LINKERR])
                val = rng.randrange(256)
                if addr == ADDR_CTRL:
                    val &= 0x0D  # avoid soft_reset spam
                mosi = encode_cfg_write(addr, [val])
            elif kind == 2:
                mosi = encode_cfg_read(0x19, 1)
            elif kind == 3:
                # ensure disabled for imem write
                if model.enable0():
                    mosi = encode_cfg_write(ADDR_ENABLE, [0])
                    miso_m = model.apply(mosi)
                    miso_h = await host._xfer(mosi)
                    assert miso_h[0] == miso_m[0]
                w = rng.randrange(0x10000)
                mosi = encode_imem_write(rng.randrange(8), [w])
            elif kind == 4:
                mosi = encode_push([rng.randrange(256)], last=True)
            else:
                mosi = encode_pull(1)

            # Occasional abort mid-stream (both DUT and model)
            abort = None
            if rng.random() < 0.15 and len(mosi) > 1:
                abort = rng.randrange(8, len(mosi) * 8)

            miso_m = model.apply(list(mosi), abort_after_bits=abort)
            miso_h = await host._xfer(mosi, abort_after_bits=abort)
            if abort is None:
                assert miso_h[0] == miso_m[0], (kind, miso_h[0], miso_m[0])
            # Spot-check shared mirrors (after abort, LINKERR may differ only in
            # ABORTED timing; TX_FREE still tracks completed pushes)
            assert (await host.cfg_read(ADDR_TX_FREE)) == (8 - len(model.tx))
            assert (await host.cfg_read(ADDR_LINKERR)) == model.linkerr
