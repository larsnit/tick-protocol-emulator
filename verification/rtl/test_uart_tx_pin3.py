"""UART TX with LP0 mapped to physical pin 3."""

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import PinMode, assemble
from rtl_bus import load_default_cfg, load_program, push_host, reset_dut


@cocotb.test()
async def test_uart_tx_phys3(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    await reset_dut(dut)
    await load_default_cfg(
        dut,
        {
            "per": 8.0,
            "msb_first": False,
            "dout_lp": 0,
            "pins": [
                {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 1},
                {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
                {"physical": 2, "mode": PinMode.INPUT, "idle": 1},
                {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
            ],
        },
    )
    words = assemble((ROOT / "sw" / "programs" / "uart_tx.asm").read_text())
    await load_program(dut, words)
    await push_host(dut, 0x55, last=True)
    dut.ui_in.value = 1 << 3

    pin_trace = []
    for _ in range(300):
        await RisingEdge(dut.clk)
        oe = (int(dut.uio_oe.value) >> 3) & 1
        pin = (int(dut.uio_out.value) >> 3) & 1
        pin_trace.append(pin if oe else 1)

    start = None
    for i in range(1, len(pin_trace)):
        if pin_trace[i - 1] == 1 and pin_trace[i] == 0:
            start = i
            break
    assert start is not None, "no start bit on uio[3]"
    per = 8
    bits = [pin_trace[start + k * per + per // 2] for k in range(10)]
    assert bits[0] == 0, bits
    data = sum(b << i for i, b in enumerate(bits[1:9]))
    assert data == 0x55, bits
    assert bits[9] == 1, bits
