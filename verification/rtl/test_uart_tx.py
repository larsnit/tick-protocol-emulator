"""cocotb tests: load UART TX program and check 8N1 framing on uio[0]."""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))
from tick import assemble
from rtl_bus import load_default_cfg, load_program, push_host, reset_dut


@cocotb.test()
async def test_uart_tx_0x55(dut):
    clock = Clock(dut.clk, 20, unit="ns")
    cocotb.start_soon(clock.start())

    await reset_dut(dut)
    await load_default_cfg(dut)

    words = assemble((ROOT / "sw" / "programs" / "uart_tx.asm").read_text())
    await load_program(dut, words)
    await push_host(dut, 0x55, last=True)

    dut.ui_in.value = 1 << 3
    pin_trace = []
    for _cy in range(300):
        await RisingEdge(dut.clk)
        pin = int(dut.uio_out.value) & 1
        oe = int(dut.uio_oe.value) & 1
        pin_trace.append(pin if oe else 1)

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
