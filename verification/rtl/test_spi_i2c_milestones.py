"""SPI/I2C engine-clock milestones on RTL vs ISS + max SCLK probe."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))
sys.path.insert(0, str(ROOT / "verification" / "model"))

from tick import EventKind, Machine, MissPolicy, PinMode, TickSource, assemble
from tick.cfg import dict_to_bytes
from tick.host_link import HostLink
from lockstep_harness import UO_RUN_LEAD_CYCLES, start_run, rtl_pads

ALIGN = UO_RUN_LEAD_CYCLES

CLK_NS = 20.0  # 50 MHz

# Non-integer SCLK periods (in clk cycles). SCLK is driven by Timer, not clk edges.
# Include sub-4.3 values so MOSI-only vs MOSI+MISO floors can diverge.
_SPI_PERIOD_CANDIDATES = (
    2.0,
    2.5,
    3.0,
    3.5,
    4.0,
    4.3,
    5.7,
    6.5,
    7.3,
    8.5,
    9.7,
    10.5,
    12.5,
    14.5,
    16.5,
)


def _spi_target_cfg():
    return {
        "tick_source": TickSource.PIN_EDGE,
        "tick_pin": 2,
        "tick_on_rise": True,
        "msb_first": True,
        "miss_policy": MissPolicy.SEND_DEFAULT,
        "default_byte": 0xFF,
        "clk_en": True,
        "cpol": False,
        "cpha": False,
        "dout_lp": 0,
        "din_lp": 1,
        "clk_lp": 2,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 2, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
        ],
        "events": [
            {"kind": EventKind.EDGE_FALL, "pin": 3},
            {"kind": EventKind.EDGE_RISE, "pin": 3, "trap": True, "vector": 9},
        ],
    }


def _i2c_target_cfg():
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


def _spi_controller_cfg(*, per: float, cpol: bool, cpha: bool):
    return {
        "per": per,
        "tick_source": TickSource.TIMER,
        "msb_first": True,
        "miss_policy": MissPolicy.FLAG,
        "clk_en": True,
        "cpol": cpol,
        "cpha": cpha,
        "dout_lp": 0,
        "din_lp": 1,
        "clk_lp": 2,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0 if not cpol else 1},
            {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 1},
        ],
        "events": [{"kind": EventKind.HOST_DATA}],
    }


def _pin_pair(m: Machine):
    out = oe = 0
    for p in range(8):
        if m.phys_oe[p]:
            oe |= 1 << p
            out |= (m.phys_drive[p] & 1) << p
    return out, oe


async def _lockstep_ext(dut, img, cfg, ext, host=(), *, check=True, align: int | None = None):
    """Offline ISS vs RTL registered pads.

    ``align`` (default ``ALIGN``) shifts the pad compare: ISS cycle i ↔ RTL
    cycle i+align. Timer-driven controller tests often need ``align=0`` (drive
    already stable in the registered pads on the execute edge); pin-edge target
    tests need the default pad lag.
    """
    if align is None:
        align = ALIGN
    host_words = host
    m = Machine()
    m.load(img, [cfg])
    for hw in host_words:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    iss = []
    for cy in range(len(ext)):
        m.phys_ext = [(ext[cy] >> p) & 1 for p in range(8)]
        m.step()
        iss.append(_pin_pair(m))

    hl = HostLink(dut)
    await hl.reset()
    await hl.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await hl.cfg_write_map({0x00: 0x01})
    await hl.load_program(img)
    for hw in host_words:
        await hl.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    dut.uio_in.value = ext[0] if ext else 0
    await start_run(hl, dut)
    rtl = []
    for cy in range(len(ext) + align):
        dut.uio_in.value = ext[min(cy, len(ext) - 1)]
        await RisingEdge(dut.clk)
        rtl.append(rtl_pads(dut))
    if check:
        for i, (io, ie) in enumerate(iss):
            ro, re = rtl[i + align]
            assert ie == re and (io & ie) == (ro & re), (
                f"cy={i} ISS=({io:#04x},{ie:#04x}) RTL=({ro:#04x},{re:#04x})"
            )
    return iss, rtl


@cocotb.test()
async def spi_target_engine_clock_lockstep(dut):
    """spi_target.asm + CLK_EN: MISO default 0xFF locksteps ISS on RTL."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "spi_target.asm").read_text())
    cfg = _spi_target_cfg()
    half = 4
    ext = []
    # CS high settle, then CS low + 8 SCLK periods (both edges).
    for _ in range(8):
        ext.append(0x08)  # CS high, SCLK low
    for _ in range(4):
        ext.append(0x00)  # CS low, SCLK low
    for _ in range(8):
        for _h in range(half):
            ext.append(0x00)  # SCLK low (drive edge for CPHA=0 trailing)
        for _h in range(half):
            ext.append(0x04)  # SCLK high (sample)
    for _ in range(8):
        ext.append(0x08)  # CS high
    await _lockstep_ext(dut, img, cfg, ext)


def _i2c_record_bus(m: Machine, ext: list, sda: int, scl: int, n: int):
    sys.path.insert(0, str(ROOT / "verification" / "model"))
    from check_i2c import _set_sda_scl

    _set_sda_scl(m, sda, scl)
    for _ in range(n):
        m.step()
        v = 0
        for p in range(8):
            v |= (m.phys_ext[p] & 1) << p
        ext.append(v)


def _i2c_build_ext(cfg, build_fn, host=()):
    """Run ISS-only bus script; return (img, ext) for RTL lockstep."""
    img = assemble((ROOT / "sw" / "programs" / "i2c_target.asm").read_text())
    m = Machine()
    m.load(img, [cfg])
    for hw in host:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    ext: list[int] = []
    build_fn(m, ext)
    return img, ext


@cocotb.test()
async def i2c_target_write_ack_lockstep(dut):
    """I2C target write path: address 0x50 → ACK, lockstep ISS↔RTL."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    sys.path.insert(0, str(ROOT / "verification" / "model"))
    from check_i2c import _SCL_PHASE

    cfg = _i2c_target_cfg()

    def build(m, ext):
        _i2c_record_bus(m, ext, 1, 1, 8)
        _i2c_record_bus(m, ext, 1, 1, 1)
        _i2c_record_bus(m, ext, 0, 1, _SCL_PHASE)  # START
        for bi in range(7, -1, -1):
            bit = (0x50 >> bi) & 1
            _i2c_record_bus(m, ext, bit, 0, _SCL_PHASE)
            _i2c_record_bus(m, ext, bit, 1, _SCL_PHASE)
            _i2c_record_bus(m, ext, bit, 0, _SCL_PHASE)
        _i2c_record_bus(m, ext, 1, 0, 32)
        _i2c_record_bus(m, ext, 1, 0, _SCL_PHASE)
        _i2c_record_bus(m, ext, 1, 1, _SCL_PHASE)
        _i2c_record_bus(m, ext, 1, 0, _SCL_PHASE)

    img, ext = _i2c_build_ext(cfg, build)
    await _lockstep_ext(dut, img, cfg, ext)


@cocotb.test()
async def i2c_target_read_addr_ack_lockstep(dut):
    """I2C read address 0x51 → ACK lockstep (stop before do_read data XFER)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    from check_i2c import _SCL_PHASE

    cfg = _i2c_target_cfg()

    def build(m, ext):
        _i2c_record_bus(m, ext, 1, 1, 8)
        _i2c_record_bus(m, ext, 0, 1, _SCL_PHASE)  # START
        for bi in range(7, -1, -1):
            bit = (0x51 >> bi) & 1
            _i2c_record_bus(m, ext, bit, 0, _SCL_PHASE)
            _i2c_record_bus(m, ext, bit, 1, _SCL_PHASE)
            _i2c_record_bus(m, ext, bit, 0, _SCL_PHASE)
        # Compare+post ACK, then one ACK sample edge; no further SCL edges
        # so do_read's data XFER does not start mid-lockstep.
        _i2c_record_bus(m, ext, 1, 0, 32)
        _i2c_record_bus(m, ext, 1, 0, _SCL_PHASE)
        _i2c_record_bus(m, ext, 1, 1, _SCL_PHASE)

    img, ext = _i2c_build_ext(cfg, build, host=[0xC3 | 0x100])
    await _lockstep_ext(dut, img, cfg, ext)


def _sda_host(dut) -> int:
    """Host view of OD SDA: 0 if DUT drives low, else release/high."""
    oe = int(dut.uio_oe.value) & 0x1
    out = int(dut.uio_out.value) & 0x1
    if oe and not out:
        return 0
    return 1


async def _i2c_drive(dut, sda: int, scl: int) -> None:
    dut.uio_in.value = (sda & 1) | ((scl & 1) << 1)


async def _i2c_phase(dut, sda: int, scl: int, n: int) -> None:
    await _i2c_drive(dut, sda, scl)
    for _ in range(n):
        await RisingEdge(dut.clk)


@cocotb.test()
async def i2c_target_read_ack_nack_stop_lockstep(dut):
    """I2C read: target data byte, host NACK (last byte), STOP.

    check_i2c on ISS; RTL replays the same ext and host-samples SDA at SCL rise.
    """
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

    cfg = _i2c_target_cfg()
    host_words = [0xC3 | 0x100]
    img = assemble((ROOT / "sw" / "programs" / "i2c_target.asm").read_text())

    # --- ISS checker ---
    m2 = Machine()
    m2.load(img, [cfg])
    for hw in host_words:
        m2.host_push(hw & 0xFF, last=bool(hw & 0x100))
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
    for _ in range(16):
        m2.step()
    assert m2.ctx[0].evf & 0x02

    # --- Record ext from ISS for RTL replay ---
    m = Machine()
    m.load(img, [cfg])
    for hw in host_words:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100))
    ext: list[int] = []

    def step_rec(n: int = 1):
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
    assert (0 if (m.phys_oe[0] and not (m.phys_drive[0] & 1)) else 1) == 0
    set_pins(1, 0)
    step_rec(_SCL_PHASE)
    for _ in range(40):
        step_rec(1)
        ta = m.ctx[0].timed_active
        if ta and ta.kind == "xfer" and ta.job and ta.job.n_bits == 8:
            break
    value = 0
    for _ in range(8):
        set_pins(1, 0)
        step_rec(_SCL_PHASE)
        set_pins(1, 1)
        step_rec(_SCL_PHASE)
        bit = 0 if (m.phys_oe[0] and not (m.phys_drive[0] & 1)) else 1
        value = (value << 1) | bit
        set_pins(1, 0)
        step_rec(_SCL_PHASE)
    assert value == 0xC3, value
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

    # --- RTL host-sample at SCL rises ---
    rtl_out: list[tuple[int, int]] = []
    host = HostLink(dut)
    await host.reset()
    await host.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await host.cfg_write_map({0x00: 0x01})
    await host.load_program(img)
    for hw in host_words:
        await host.push(hw & 0xFF, last=bool(hw & 0x100))
    dut.uio_in.value = ext[0] if ext else 0
    await start_run(host, dut)
    for cy in range(len(ext) + ALIGN):
        e = ext[min(cy, len(ext) - 1)]
        dut.uio_in.value = e
        await RisingEdge(dut.clk)
        rtl_out.append(rtl_pads(dut))

    def _sda_host(oe: int, out: int, ext_sda: int) -> int:
        return 0 if ((oe & 1) and not (out & 1)) else (ext_sda & 1)

    m3 = Machine()
    m3.load(img, [cfg])
    for hw in host_words:
        m3.host_push(hw & 0xFF, last=bool(hw & 0x100))
    iss_bits: list[int] = []
    rtl_bits: list[int] = []
    prev = 1
    for src, e in enumerate(ext):
        m3.phys_ext = [(e >> p) & 1 for p in range(8)]
        m3.step()
        scl = (e >> 1) & 1
        if prev == 0 and scl == 1:
            ext_sda = e & 1
            iss_bits.append(
                _sda_host(1 if m3.phys_oe[0] else 0, m3.phys_drive[0] & 1, ext_sda)
            )
            out, oe = rtl_out[src + ALIGN]
            rtl_bits.append(_sda_host(oe, out, ext_sda))
        prev = scl

    assert len(iss_bits) >= 9 + 8 + 1, len(iss_bits)

    def bits_to_byte(bits):
        v = 0
        for b in bits:
            v = (v << 1) | b
        return v

    assert bits_to_byte(iss_bits[0:8]) == 0x51
    assert iss_bits[8] == 0  # ACK
    assert bits_to_byte(iss_bits[9:17]) == 0xC3
    assert len(iss_bits) >= 18  # NACK sample rise present
    # Full host-view lockstep including data phase (rf_d bypass after MFS RX).
    assert rtl_bits == iss_bits, (rtl_bits, iss_bits)


@cocotb.test()
async def i2c_target_addr_mismatch_nack_lockstep(dut):
    """Wrong address → NACK bit lockstep."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    sys.path.insert(0, str(ROOT / "verification" / "model"))
    from check_i2c import _SCL_PHASE

    cfg = _i2c_target_cfg()

    def build(m, ext):
        _i2c_record_bus(m, ext, 1, 1, 8)
        _i2c_record_bus(m, ext, 0, 1, _SCL_PHASE)
        for bi in range(7, -1, -1):
            bit = (0x22 >> bi) & 1  # not 0x50
            _i2c_record_bus(m, ext, bit, 0, _SCL_PHASE)
            _i2c_record_bus(m, ext, bit, 1, _SCL_PHASE)
            _i2c_record_bus(m, ext, bit, 0, _SCL_PHASE)
        _i2c_record_bus(m, ext, 1, 0, 32)
        _i2c_record_bus(m, ext, 1, 0, _SCL_PHASE)
        _i2c_record_bus(m, ext, 1, 1, _SCL_PHASE)
        _i2c_record_bus(m, ext, 1, 0, _SCL_PHASE)

    img, ext = _i2c_build_ext(cfg, build)
    await _lockstep_ext(dut, img, cfg, ext)


@cocotb.test()
async def i2c_target_start_stop_trap_lockstep(dut):
    """START then STOP trap returns to idle; pin lockstep."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    sys.path.insert(0, str(ROOT / "verification" / "model"))
    from check_i2c import _SCL_PHASE

    cfg = _i2c_target_cfg()

    def build(m, ext):
        _i2c_record_bus(m, ext, 1, 1, 8)
        _i2c_record_bus(m, ext, 0, 1, _SCL_PHASE)  # START
        _i2c_record_bus(m, ext, 0, 1, 4)
        _i2c_record_bus(m, ext, 1, 1, _SCL_PHASE)  # STOP (SDA rise while SCL high)
        _i2c_record_bus(m, ext, 1, 1, 16)

    img, ext = _i2c_build_ext(cfg, build)
    await _lockstep_ext(dut, img, cfg, ext)


@cocotb.test()
async def i2c_target_stretch_while_host_late_lockstep(dut):
    """After address ACK, pause SCL low long enough for MISS stretch; lockstep."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    sys.path.insert(0, str(ROOT / "verification" / "model"))
    from check_i2c import _SCL_PHASE

    cfg = _i2c_target_cfg()

    def build(m, ext):
        _i2c_record_bus(m, ext, 1, 1, 8)
        _i2c_record_bus(m, ext, 0, 1, _SCL_PHASE)
        for bi in range(7, -1, -1):
            bit = (0x50 >> bi) & 1
            _i2c_record_bus(m, ext, bit, 0, _SCL_PHASE)
            _i2c_record_bus(m, ext, bit, 1, _SCL_PHASE)
            _i2c_record_bus(m, ext, bit, 0, _SCL_PHASE)
        _i2c_record_bus(m, ext, 1, 0, 32)
        _i2c_record_bus(m, ext, 1, 0, _SCL_PHASE)
        _i2c_record_bus(m, ext, 1, 1, _SCL_PHASE)
        # Host late: hold SCL low for many edges' worth while target stretches.
        _i2c_record_bus(m, ext, 1, 0, _SCL_PHASE * 4)
        for bi in range(7, -1, -1):
            bit = (0xA5 >> bi) & 1
            _i2c_record_bus(m, ext, bit, 0, _SCL_PHASE)
            _i2c_record_bus(m, ext, bit, 1, _SCL_PHASE)
            _i2c_record_bus(m, ext, bit, 0, _SCL_PHASE)

    img, ext = _i2c_build_ext(cfg, build)
    await _lockstep_ext(dut, img, cfg, ext)


@cocotb.test()
async def i2c_controller_write_byte_lockstep(dut):
    """i2c_controller.asm writes address+data to OD target model; ISS↔RTL."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "i2c_controller.asm").read_text())
    cfg = {
        "per": 4.0,
        "tick_source": TickSource.TIMER,
        "msb_first": True,
        "miss_policy": MissPolicy.FLAG,
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
        "events": [{"kind": EventKind.HOST_DATA}],
    }
    # Target ACK: hold SDA low during ACK slots via ext when not driven.
    # Controller drives both; leave SDA released (1) so ACK=0 must come from
    # a model — use ext=0 on SDA during ACK windows is fragile. Simpler: tie
    # SDA low always so every ACK samples 0 (NACK path not taken).
    n = 200
    ext = [0x00] * n  # SDA=0, SCL=0 external pull favors ACK
    await _lockstep_ext(dut, img, cfg, ext, host=[0x50, 0xA5 | 0x100], align=0)


@cocotb.test()
async def spi_controller_modes_lockstep(dut):
    """spi_controller.asm: all four CPOL/CPHA modes lockstep vs ISS at PER=4."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "spi_controller.asm").read_text())
    for cpol in (False, True):
        for cpha in (False, True):
            cfg = _spi_controller_cfg(per=4.0, cpol=cpol, cpha=cpha)
            # MISO tied high; host pushes one byte then LAST empty ends.
            n = 80
            idle_clk = 0x04 if cpol else 0x00
            ext = [(idle_clk | 0x02)] * n  # MISO=1, CS driven by DUT
            await _lockstep_ext(dut, img, cfg, ext, host=[0xA5 | 0x100], align=0)


@cocotb.test()
async def spi_controller_max_sclk(dut):
    """Find the smallest PER where spi_controller.asm locksteps ISS↔RTL.

    Reports max SCLK = f_clk / (2·PER) for engine-clock mode-0.
    """
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "spi_controller.asm").read_text())
    best = None
    for per in (1.0, 2.0, 3.0, 4.0):
        cfg = _spi_controller_cfg(per=per, cpol=False, cpha=False)
        n = 80
        ext = [0x02] * n
        try:
            await _lockstep_ext(dut, img, cfg, ext, host=[0x3C | 0x100], align=0)
            best = per
            break
        except AssertionError as e:
            dut._log.info(f"PER={per} lockstep fail: {e}")
    assert best is not None, "no PER in 1..4 locksteps"
    mhz = 50.0 / (2.0 * best)
    dut._log.info(f"max_sclk_ctrl: min lockstep PER={best} → {mhz:.1f} MHz SCLK @ 50 MHz clk")


def _miso_pad(dut) -> int:
    """Host view of MISO (pad 0): driven level if OE, else pull-up 1."""
    oe = int(dut.uio_oe.value) & 0xFF
    out = int(dut.uio_out.value) & 0xFF
    if oe & 0x1:
        return out & 0x1
    return 1


async def _pop_host_rx(host: HostLink) -> int | None:
    got = await host.pull()
    if got is None:
        return None
    tag, data = got
    return (data & 0xFF) | ((tag & 3) << 8)


def _spi_half_lens(period_clk: float, n_halves: int) -> list[int]:
    """Integer half lengths whose mean is period_clk/2 (non-integer period)."""
    target = period_clk / 2.0
    acc = 0.0
    out: list[int] = []
    for i in range(n_halves):
        want = target * (i + 1)
        n = int(want - acc + 1e-9)
        if n < 1:
            n = 1
        out.append(n)
        acc += n
    return out


def _spi_max_ext(
    *,
    period_clk: float,
    cpol: bool,
    cpha: bool,
    mosi_bytes: list[int],
    phase_clk: int = 1,
) -> tuple[list[int], list[int]]:
    """Build CS/SCLK/MOSI ext; return (ext, indices of SCLK rising edges).

    Half lengths average to period/2 so the SCLK period is non-integer in clk.
    Modes 0 and 3 both sample on rising (SCLK pad bit → 1).
    """
    idle = 0x04 if cpol else 0x00
    active = 0x00 if cpol else 0x04
    ext: list[int] = []
    rise_idx: list[int] = []
    for _ in range(8):
        ext.append(0x08 | idle)
    for _ in range(6 + phase_clk):
        ext.append(idle)
    n_bits = 8 * len(mosi_bytes)
    halves = _spi_half_lens(period_clk, n_bits * 2)
    for bit_i in range(n_bits):
        by = bit_i // 8
        bi = 7 - (bit_i % 8)
        mosi = (mosi_bytes[by] >> bi) & 1
        h0 = halves[bit_i * 2]
        h1 = halves[bit_i * 2 + 1]
        if not cpha:
            # Mode 0: setup on idle(low), sample on rise to active(high).
            for _ in range(h0):
                ext.append(idle | ((mosi & 1) << 1))
            rise_idx.append(len(ext))
            for _ in range(h1):
                ext.append(active | ((mosi & 1) << 1))
        else:
            # Mode 3: leading fall to active(low), sample on rise to idle(high).
            for _ in range(h0):
                ext.append(active | ((mosi & 1) << 1))
            rise_idx.append(len(ext))
            for _ in range(h1):
                ext.append(idle | ((mosi & 1) << 1))
    for _ in range(24):
        ext.append(idle)
    for _ in range(16):
        ext.append(0x08 | idle)
    return ext, rise_idx


async def _spi_target_async_xfer(
    dut,
    img,
    cfg,
    *,
    period_clk: float,
    cpol: bool,
    cpha: bool,
    mosi_bytes: list[int],
    expect_miso: list[int] | None,
    host: list[int] = (),
    phase_clk: int = 1,
) -> list[int]:
    """Host-style max-SCLK probe: non-integer period, sample MISO at SCLK rise.

    MOSI-only: ISS↔RTL pin lockstep (target must track MOSI/SCLK).
    MOSI+MISO: also require host-sampled MISO bytes == expect_miso.
    """
    host_words = list(host)
    ext, rise_idx = _spi_max_ext(
        period_clk=period_clk,
        cpol=cpol,
        cpha=cpha,
        mosi_bytes=mosi_bytes,
        phase_clk=phase_clk,
    )

    # ISS must receive the MOSI payload (proves the ext is a valid receive path).
    m = Machine()
    m.load(img, [cfg])
    for hw in host_words:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    iss_miso_bits: list[int] = []
    for cy, e in enumerate(ext):
        m.phys_ext = [(e >> p) & 1 for p in range(8)]
        m.step()
        if cy in rise_idx and len(iss_miso_bits) < 8 * len(mosi_bytes):
            iss_miso_bits.append(m.phys_drive[0] & 1 if m.phys_oe[0] else 1)
    iss_rx: list[int] = []
    while True:
        w = m.host_pop()
        if w is None:
            break
        if int(w.tag) == 0:
            iss_rx.append(w.data & 0xFF)
        if int(w.tag) == 1:
            break
    assert any(b in iss_rx for b in mosi_bytes), (
        f"ISS RX@{period_clk} {iss_rx} missing MOSI {mosi_bytes}"
    )

    # Pin lockstep = MOSI receive path on RTL.
    await _lockstep_ext(dut, img, cfg, ext, host=host_words)

    if expect_miso is None:
        return []

    # Re-run for host-style MISO sample at each SCLK rising edge.
    # Sample MISO with a Timer offset so we never race the chip's clk-edge
    # update (host model must not sample on the same edge the DUT changes it).
    hl = HostLink(dut)
    await hl.reset()
    await hl.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await hl.cfg_write_map({0x00: 0x01})
    await hl.load_program(img)
    for hw in host_words:
        await hl.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    dut.uio_in.value = ext[0] if ext else 0
    await start_run(hl, dut)

    # Drive SCLK mid-cycle (sub-cycle offset from clk) so the host sample
    # never shares the chip's MISO-update clk edge.
    half_ns = CLK_NS / 2.0
    rtl_miso_bits: list[int] = []
    for cy in range(len(ext) + ALIGN):
        e = ext[min(cy, len(ext) - 1)]
        await RisingEdge(dut.clk)
        await Timer(half_ns, unit="ns")
        dut.uio_in.value = e
        src = cy - ALIGN
        if src in rise_idx and len(rtl_miso_bits) < 8 * len(mosi_bytes):
            rtl_miso_bits.append(_miso_pad(dut))

    def _pack(bits: list[int]) -> list[int]:
        out = []
        for i in range(len(mosi_bytes)):
            v = 0
            for b in bits[i * 8 : (i + 1) * 8]:
                v = (v << 1) | b
            out.append(v & 0xFF)
        return out

    rtl_miso = _pack(rtl_miso_bits)
    iss_miso = _pack(iss_miso_bits)
    assert iss_miso == expect_miso, f"ISS MISO@{period_clk}: {iss_miso} want {expect_miso}"
    assert rtl_miso == expect_miso, f"RTL MISO@{period_clk}: {rtl_miso} want {expect_miso}"
    return rtl_miso


def _spi_max_cfg(*, cpol: bool, cpha: bool) -> dict:
    """SEND_DEFAULT + large PER so slow SCLK halves do not MISS mid-byte."""
    cfg = _spi_target_cfg()
    cfg["cpol"] = cpol
    cfg["cpha"] = cpha
    cfg["pins"][2]["idle"] = 1 if cpol else 0
    cfg["per"] = 64.0
    return cfg


@cocotb.test()
async def spi_target_max_sclk_modes_0_and_3(dut):
    """Host-style max SCLK: sample MISO at SCLK rising; SCLK not clk-locked.

    Reports smallest passing period (clk cycles) separately for:
      MOSI-only (target receive) and MOSI+MISO (target send), modes 0 and 3.
    Phase offset 0.37·clk so edges fall between clk edges.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "spi_target.asm").read_text())
    results = {}
    for mode, cpol, cpha in (("mode0", False, False), ("mode3", True, True)):
        best_rx = None
        for period in _SPI_PERIOD_CANDIDATES:
            try:
                await _spi_target_async_xfer(
                    dut,
                    img,
                    _spi_max_cfg(cpol=cpol, cpha=cpha),
                    period_clk=period,
                    cpol=cpol,
                    cpha=cpha,
                    mosi_bytes=[0xA5, 0x3C],
                    expect_miso=None,  # MOSI-only: lockstep receive path
                    phase_clk=1,
                )
                best_rx = period
                break
            except AssertionError as e:
                dut._log.info(f"{mode} MOSI-only period={period} fail: {e}")
        assert best_rx is not None, f"{mode} MOSI-only: no period passed"

        # Alternating MISO (host FIFO) so a stale bit fails the sample check.
        host_alt = [0xAA, 0x55 | 0x100]
        expect_alt = [0xAA, 0x55]
        best_both = None
        for period in _SPI_PERIOD_CANDIDATES:
            try:
                await _spi_target_async_xfer(
                    dut,
                    img,
                    _spi_max_cfg(cpol=cpol, cpha=cpha),
                    period_clk=period,
                    cpol=cpol,
                    cpha=cpha,
                    mosi_bytes=[0xA5, 0x3C],
                    expect_miso=expect_alt,
                    host=host_alt,
                    phase_clk=1,
                )
                best_both = period
                break
            except AssertionError as e:
                dut._log.info(f"{mode} MOSI+MISO period={period} fail: {e}")
        assert best_both is not None, f"{mode} MOSI+MISO: no period passed"

        results[mode] = {
            "mosi_only": (best_rx, 50.0 / best_rx),
            "mosi_miso": (best_both, 50.0 / best_both),
        }
        dut._log.info(
            f"max_sclk_target_{mode}: MOSI-only period={best_rx} → {50.0 / best_rx:.2f} MHz; "
            f"MOSI+MISO period={best_both} → {50.0 / best_both:.2f} MHz @ 50 MHz clk"
        )
    dut._log.info(f"SPI_TARGET_MAX_SCLK {results!r}")
    await _spi_target_async_xfer(
        dut,
        img,
        _spi_max_cfg(cpol=False, cpha=False),
        period_clk=results["mode0"]["mosi_miso"][0],
        cpol=False,
        cpha=False,
        mosi_bytes=[0xA5, 0x5A],
        expect_miso=[0xAA, 0x55],
        host=[0xAA, 0x55 | 0x100],
        phase_clk=3,
    )
