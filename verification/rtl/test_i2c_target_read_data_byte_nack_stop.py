"""I2C target read: address ACK → data byte → host NACK → STOP.

Full path on RTL vs ISS with check_i2c host sampling of SDA at SCL rise.
Fails if RTL data-phase SDA does not match ISS (not a known limit).
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))
sys.path.insert(0, str(ROOT / "verification" / "model"))

from tick import EventKind, Machine, MissPolicy, PinMode, TickSource, assemble
from tick.cfg import dict_to_bytes
from rtl_bus import load_cfg_bytes, load_program, push_host, reset_dut

ALIGN = 1


def _cfg():
    return {
        "tick_source": TickSource.PIN_EDGE,
        "tick_pin": 1,
        "tick_on_rise": True,
        "msb_first": True,
        "miss_policy": MissPolicy.STRETCH,
        "clk_en": True,
        "cpol": True,
        "cpha": True,
        "dout_lp": 0,
        "din_lp": 0,
        "clk_lp": 1,
        "pins": [
            {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1},
            {"physical": 1, "mode": PinMode.OPENDRAIN, "idle": 1},
        ],
        "events": [
            {"kind": EventKind.QUAL_FALL_WHILE_HIGH, "pin": 0, "qual_pin": 1},
            {
                "kind": EventKind.QUAL_RISE_WHILE_HIGH,
                "pin": 0,
                "qual_pin": 1,
                "trap": True,
                "vector": 0,
            },
        ],
    }


def _sda_host(oe: int, out: int, ext_sda: int) -> int:
    """I2C host view: DUT OD pull-low wins; else external/release level."""
    dut_low = bool((oe & 1) and not (out & 1))
    return 0 if dut_low else (ext_sda & 1)


@cocotb.test()
async def i2c_target_read_data_byte_nack_stop(dut):
    """Host samples SDA at SCL rise: addr ACK, data 0xC3, NACK, STOP — ISS==RTL."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    from check_i2c import (
        _SCL_PHASE,
        i2c_clock_byte_msb,
        i2c_clock_in_byte_msb,
        i2c_idle,
        i2c_master_nack,
        i2c_start,
        i2c_stop,
    )

    cfg = _cfg()
    host = [0xC3 | 0x100]
    img = assemble((ROOT / "sw" / "programs" / "i2c_target.asm").read_text())

    # ISS checker
    m2 = Machine()
    m2.load(img, [cfg])
    m2.host_push(0xC3, last=True)
    i2c_idle(m2, 8)
    i2c_start(m2)
    assert i2c_clock_byte_msb(m2, 0x51, sample_ack=True) == 0
    for _ in range(40):
        m2.step()
        ta = m2.ctx[0].timed_active
        if ta and ta.kind == "xfer" and ta.job and ta.job.n_bits == 8:
            break
    assert i2c_clock_in_byte_msb(m2) == 0xC3
    i2c_master_nack(m2)
    i2c_stop(m2)

    # Build ext
    m = Machine()
    m.load(img, [cfg])
    m.host_push(0xC3, last=True)
    ext: list[int] = []

    def step_rec(n=1):
        for _ in range(n):
            m.step()
            v = 0
            for p in range(8):
                v |= (m.phys_ext[p] & 1) << p
            ext.append(v)

    def set_pins(sda, scl):
        m.phys_ext[0] = sda
        m.phys_ext[1] = scl

    set_pins(1, 1)
    step_rec(8)
    set_pins(1, 1)
    step_rec(1)
    set_pins(0, 1)
    step_rec(_SCL_PHASE)
    for bi in range(7, -1, -1):
        bit = (0x51 >> bi) & 1
        set_pins(bit, 0)
        step_rec(_SCL_PHASE)
        set_pins(bit, 1)
        step_rec(_SCL_PHASE)
        set_pins(bit, 0)
        step_rec(_SCL_PHASE)
    for _ in range(32):
        step_rec(1)
        ta = m.ctx[0].timed_active
        if ta is not None and ta.kind == "xfer" and ta.job and ta.job.n_bits == 1:
            break
    set_pins(1, 0)
    step_rec(_SCL_PHASE)
    set_pins(1, 1)
    step_rec(_SCL_PHASE)
    set_pins(1, 0)
    step_rec(_SCL_PHASE)
    for _ in range(40):
        step_rec(1)
        ta = m.ctx[0].timed_active
        if ta and ta.kind == "xfer" and ta.job and ta.job.n_bits == 8:
            break
    for _ in range(8):
        set_pins(1, 0)
        step_rec(_SCL_PHASE)
        set_pins(1, 1)
        step_rec(_SCL_PHASE)
        set_pins(1, 0)
        step_rec(_SCL_PHASE)
    set_pins(1, 0)
    step_rec(_SCL_PHASE)
    set_pins(1, 1)
    step_rec(_SCL_PHASE)
    set_pins(1, 0)
    step_rec(_SCL_PHASE)
    set_pins(0, 1)
    step_rec(_SCL_PHASE)
    set_pins(1, 1)
    step_rec(_SCL_PHASE)
    step_rec(16)

    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, cfg, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, img)
    await push_host(dut, 0xC3, last=True)
    dut.ui_in.value = 1 << 3

    rtl_out: list[tuple[int, int]] = []
    for cy in range(len(ext) + ALIGN):
        e = ext[min(cy, len(ext) - 1)]
        dut.uio_in.value = e
        await RisingEdge(dut.clk)
        rtl_out.append((int(dut.uio_out.value) & 0xFF, int(dut.uio_oe.value) & 0xFF))

    m3 = Machine()
    m3.load(img, [cfg])
    m3.host_push(0xC3, last=True)
    iss_bits: list[int] = []
    rtl_bits: list[int] = []
    prev = 1
    for src, e in enumerate(ext):
        m3.phys_ext = [(e >> p) & 1 for p in range(8)]
        m3.step()
        scl = (e >> 1) & 1
        if prev == 0 and scl == 1:
            ext_sda = e & 1
            iss_oe = 1 if m3.phys_oe[0] else 0
            iss_out = m3.phys_drive[0] & 1
            iss_bits.append(_sda_host(iss_oe, iss_out, ext_sda))
            out, oe = rtl_out[src + ALIGN]
            rtl_bits.append(_sda_host(oe, out, ext_sda))
        prev = scl

    assert len(iss_bits) >= 9 + 8 + 1, len(iss_bits)

    def bits_to_byte(bits):
        v = 0
        for b in bits:
            v = (v << 1) | b
        return v

    assert bits_to_byte(iss_bits[0:8]) == 0x51  # address
    assert iss_bits[8] == 0  # ACK
    assert bits_to_byte(iss_bits[9:17]) == 0xC3
    # Full host-view lockstep including data phase (the former "limit").
    assert rtl_bits == iss_bits, (
        f"SDA@SCL-rise diverge first@"
        f"{next(i for i in range(len(iss_bits)) if rtl_bits[i] != iss_bits[i])}: "
        f"RTL={rtl_bits} ISS={iss_bits}"
    )
