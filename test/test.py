"""cocotb tests: load UART TX program and check 8N1 framing on uio[0]."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model.assembler import assemble


async def set_cmd(dut, nibble: int, data: int = 0):
    dut.ui_in.value = (nibble & 0xF) << 4
    dut.uio_in.value = data & 0xFF
    await ClockCycles(dut.clk, 1)


async def pulse_imem_we(dut):
    v = int(dut.ui_in.value)
    dut.ui_in.value = v | (1 << 2)
    await ClockCycles(dut.clk, 1)
    dut.ui_in.value = v & ~(1 << 2)
    await ClockCycles(dut.clk, 1)


async def pulse_host_wr(dut):
    v = int(dut.ui_in.value)
    dut.ui_in.value = v | (1 << 0)
    await ClockCycles(dut.clk, 1)
    dut.ui_in.value = v & ~(1 << 0)
    await ClockCycles(dut.clk, 1)


async def load_program(dut, words):
    for addr, w in enumerate(words):
        await set_cmd(dut, 0xA, addr)
        await set_cmd(dut, 0xB, w & 0xFF)
        await set_cmd(dut, 0xC, (w >> 8) & 0xFF)
        await pulse_imem_we(dut)


async def push_host(dut, data: int, last: bool = False, cmd: bool = False):
    word = (data & 0xFF) | ((1 if last else 0) << 8) | ((1 if cmd else 0) << 9)
    await set_cmd(dut, 0xD, word & 0xFF)
    await set_cmd(dut, 0xE, (word >> 8) & 0x3)
    await pulse_host_wr(dut)


@cocotb.test()
async def test_uart_tx_0x55(dut):
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)

    words = assemble((ROOT / "programs" / "uart_tx.asm").read_text())
    await load_program(dut, words)
    await push_host(dut, 0x55, last=True)

    # run=1
    dut.ui_in.value = 1 << 3
    dut.uio_in.value = 0

    levels = []
    prev = 1
    for _ in range(400):
        await RisingEdge(dut.clk)
        pin = int(dut.uio_out.value) & 1
        oe = int(dut.uio_oe.value) & 1
        cur = pin if oe else 1
        if not levels or cur != prev:
            levels.append((len(levels) and levels[-1][0] + 1 or 0, cur))
            # better track cycle count
        prev = cur

    # Resample with cycle counter
    samples = []
    dut.ui_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)
    await load_program(dut, words)
    await push_host(dut, 0x55, last=True)
    dut.ui_in.value = 1 << 3
    pin_trace = []
    for cy in range(300):
        await RisingEdge(dut.clk)
        pin = int(dut.uio_out.value) & 1
        oe = int(dut.uio_oe.value) & 1
        pin_trace.append(pin if oe else 1)

    # find start bit
    start = None
    for i in range(1, len(pin_trace)):
        if pin_trace[i - 1] == 1 and pin_trace[i] == 0:
            start = i
            break
    assert start is not None, "no start bit"
    per = 8
    bits = []
    for k in range(10):
        t = start + k * per + per // 2
        assert t < len(pin_trace)
        bits.append(pin_trace[t])
    assert bits[0] == 0, bits
    data = 0
    for i, b in enumerate(bits[1:9]):
        data |= b << i
    assert data == 0x55, bits
    assert bits[9] == 1, bits
