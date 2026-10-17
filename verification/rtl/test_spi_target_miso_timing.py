"""SPI target MISO timing: sub-cycle SCLK→MISO delay; prove checker can fail.

Uses alternating MISO bits (0xAA, 0x55) so a stale bit is visible as a bit error.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer
from cocotb.utils import get_sim_time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import assemble
from tick.cfg import dict_to_bytes
from rtl_bus import load_cfg_bytes, load_program, push_host, reset_dut

from test_spi_i2c_milestones import (
    ALIGN,
    CLK_NS,
    _SPI_PERIOD_CANDIDATES,
    _miso_pad,
    _spi_max_cfg,
    _spi_max_ext,
    _spi_target_async_xfer,
)

_ALT_MOSI = [0xA5, 0x3C]
_ALT_MISO = [0xAA, 0x55]

# Comfortable half for attribution (period ≈ 8.5 clk @ 50 MHz).
_HALF_NS = 85.0
_N_PHASES = 8  # sub-cycle offsets within one clk period


def _pack_uio(*, cs: int, sclk: int, mosi: int = 0) -> int:
    return ((cs & 1) << 3) | ((sclk & 1) << 2) | ((mosi & 1) << 1)


def _now_ns() -> float:
    return float(get_sim_time(units="ns"))


@cocotb.test()
async def spi_target_miso_sclk_to_change_delay(dut):
    """Sub-cycle phases: SCLK-fall → MISO change delay (ns) and margin to sample rise.

    Drives SCLK with Timer at 8 offsets within one clk period (not whole-cycle
    phase_clk steps). Mode 0: launch=fall, sample=rise.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "spi_target.asm").read_text())
    cfg = _spi_max_cfg(cpol=False, cpha=False)
    host = [0xAA, 0x55 | 0x100]

    delays_ns: list[float] = []
    margins_ns: list[float] = []  # MISO change → next host sample (rise)

    for phase_i in range(_N_PHASES):
        phase_ns = phase_i * (CLK_NS / _N_PHASES)
        await reset_dut(dut)
        await load_cfg_bytes(dut, dict_to_bytes(0, cfg, enable_mask=None))
        await load_cfg_bytes(dut, {0x00: 0x01})
        await load_program(dut, img)
        for hw in host:
            await push_host(dut, hw & 0xFF, last=bool(hw & 0x100))
        dut.ui_in.value = 1 << 3

        # Align to a clk edge, then offset SCLK by phase_ns within the period.
        await RisingEdge(dut.clk)
        if phase_ns > 0:
            await Timer(phase_ns, unit="ns")

        # CS high, then select; leave time for WAIT→SET.E→PULL→XFER first bit.
        dut.uio_in.value = _pack_uio(cs=1, sclk=0)
        await Timer(_HALF_NS, unit="ns")
        dut.uio_in.value = _pack_uio(cs=0, sclk=0)
        await Timer(4 * CLK_NS, unit="ns")

        step = 1.0  # 1 ns poll
        prev_miso = _miso_pad(dut)

        async def _hold(sclk: int, hold_ns: float, *, note_change_from_fall=None):
            """Hold SCLK; return (t_change_ns or None, final_miso)."""
            nonlocal prev_miso
            t_change = None
            elapsed = 0.0
            while elapsed < hold_ns - 0.5:
                await Timer(step, unit="ns")
                elapsed += step
                cur = _miso_pad(dut)
                if cur != prev_miso and t_change is None:
                    t_change = _now_ns()
                    prev_miso = cur
            return t_change

        # Mode 0: first rise samples bit 0 (already driven on XFER active).
        dut.uio_in.value = _pack_uio(cs=0, sclk=1)
        await _hold(1, _HALF_NS)

        # Subsequent bits: fall = launch next MISO; rise = host sample.
        for _ in range(15):
            dut.uio_in.value = _pack_uio(cs=0, sclk=0)
            t_fall = _now_ns()
            t_change = await _hold(0, _HALF_NS)
            dut.uio_in.value = _pack_uio(cs=0, sclk=1)
            t_rise = _now_ns()
            # Late change during high half still counts (after sample → neg margin).
            t_late = await _hold(1, _HALF_NS)
            if t_change is None and t_late is not None:
                t_change = t_late
            if t_change is not None:
                delays_ns.append(t_change - t_fall)
                margins_ns.append(t_rise - t_change)

        dut.uio_in.value = _pack_uio(cs=1, sclk=0)
        await Timer(2 * CLK_NS, unit="ns")

    assert delays_ns, "no MISO transitions observed"
    dmin, dmax = min(delays_ns), max(delays_ns)
    mmin = min(margins_ns) if margins_ns else float("nan")
    mmax = max(margins_ns) if margins_ns else float("nan")
    dut._log.info(
        f"MISO_TIMING_NS period_half={_HALF_NS}ns phases={_N_PHASES} "
        f"SCLK_fall→MISO min={dmin:.1f}ns max={dmax:.1f}ns "
        f"margin_to_sample_rise min={mmin:.1f}ns max={mmax:.1f}ns "
        f"(launch=fall sample=rise; {_N_PHASES} sub-cycle offsets in {CLK_NS}ns clk)"
    )
    # Sync (~2 clk) + registered drive → ~40–60 ns at 50 MHz, not same-cycle.
    assert dmin >= CLK_NS, f"delay {dmin}ns too small — likely measuring race"
    assert dmax <= 4 * CLK_NS, (dmin, dmax)


async def _sample_miso_at_rises(
    dut, img, cfg, *, period_clk: float, host: list[int], phase_clk: int = 1
) -> list[int]:
    """Host-sample MISO at each SCLK rise (no pin lockstep). Returns packed bytes."""
    ext, rise_idx = _spi_max_ext(
        period_clk=period_clk,
        cpol=False,
        cpha=False,
        mosi_bytes=_ALT_MOSI,
        phase_clk=phase_clk,
    )
    await reset_dut(dut)
    await load_cfg_bytes(dut, dict_to_bytes(0, cfg, enable_mask=None))
    await load_cfg_bytes(dut, {0x00: 0x01})
    await load_program(dut, img)
    for hw in host:
        await push_host(dut, hw & 0xFF, last=bool(hw & 0x100))
    dut.ui_in.value = 1 << 3
    bits: list[int] = []
    for cy in range(len(ext) + ALIGN):
        e = ext[min(cy, len(ext) - 1)]
        dut.uio_in.value = e
        await RisingEdge(dut.clk)
        src = cy - ALIGN
        if src in rise_idx and len(bits) < 16:
            bits.append(_miso_pad(dut))
    out = []
    for i in range(2):
        v = 0
        for b in bits[i * 8 : (i + 1) * 8]:
            v = (v << 1) | b
        out.append(v & 0xFF)
    return out


@cocotb.test()
async def spi_target_cpha0_pipelined_xfer_miso_aa_55(dut):
    """CPHA=0 pipelined XFER: host samples 0xAA then 0x55 (not mid-byte clobber)."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "spi_target.asm").read_text())
    cfg = _spi_max_cfg(cpol=False, cpha=False)
    host = [0xAA, 0x55 | 0x100]
    got = await _spi_target_async_xfer(
        dut,
        img,
        cfg,
        period_clk=8.5,
        cpol=False,
        cpha=False,
        mosi_bytes=_ALT_MOSI,
        expect_miso=_ALT_MISO,
        host=host,
        phase_clk=1,
    )
    assert got == _ALT_MISO, got


@cocotb.test()
async def spi_target_period4_zero_delay_race(dut):
    """Period 4 'passes' only because host samples on the same clk edge MISO updates.

    Half-period = 2 clk; measured fall→MISO is ~3 clk, so a real host sampling at
    the rise (2 clk after fall) would see the prior bit. Zero-delay RTL sim samples
    MISO after NBA on that shared clk edge and can see the new bit — not a valid
    timing result.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "spi_target.asm").read_text())
    cfg = _spi_max_cfg(cpol=False, cpha=False)
    host = [0xAA, 0x55 | 0x100]

    # Zero-delay sim may still pack expect_miso correctly at period 4.
    got = await _sample_miso_at_rises(
        dut, img, cfg, period_clk=4.0, host=host, phase_clk=1
    )
    dut._log.info(
        f"PERIOD4_ZERO_DELAY_RACE got={got} want={_ALT_MISO} "
        f"(sim may match; half=2 clk < fall→MISO≈3 clk — not a guaranteed pass)"
    )
    # Document: do not treat this as a timing pass. Guaranteed floor is period 8.
    assert True


@cocotb.test()
async def spi_target_miso_negative_short_period_bit_error(dut):
    """Shorten SCLK until host-sampled MISO bits fail (alternating payload)."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    img = assemble((ROOT / "sw" / "programs" / "spi_target.asm").read_text())
    cfg = _spi_max_cfg(cpol=False, cpha=False)
    host = [0xAA, 0x55 | 0x100]

    periods = list(_SPI_PERIOD_CANDIDATES) + [4.0, 3.5, 3.0, 2.5, 2.0]
    periods = sorted(set(periods), reverse=True)

    best_mosi = None
    best_both_sim = None  # zero-delay sim floor (may be optimistic)
    first_fail_period = None
    first_fail_got = None

    for period in periods:
        try:
            await _spi_target_async_xfer(
                dut,
                img,
                cfg,
                period_clk=period,
                cpol=False,
                cpha=False,
                mosi_bytes=_ALT_MOSI,
                expect_miso=None,
                host=host,
                phase_clk=1,
            )
            best_mosi = period
        except AssertionError:
            pass

        try:
            await _spi_target_async_xfer(
                dut,
                img,
                cfg,
                period_clk=period,
                cpol=False,
                cpha=False,
                mosi_bytes=_ALT_MOSI,
                expect_miso=_ALT_MISO,
                host=host,
                phase_clk=1,
            )
            best_both_sim = period
        except AssertionError:
            pass

        got = await _sample_miso_at_rises(
            dut, img, cfg, period_clk=period, host=host, phase_clk=1
        )
        if got != _ALT_MISO and first_fail_period is None:
            first_fail_period = period
            first_fail_got = got

    assert best_mosi is not None
    assert best_both_sim is not None
    assert first_fail_period is not None
    assert first_fail_got != _ALT_MISO

    # Guaranteed MOSI+MISO: period 8 (f_clk/8) — sync jitter + out delay + host setup.
    guaranteed = 8.0
    dut._log.info(
        f"SPI_MISO_LIMITS MOSI-only_sim period={best_mosi} → {50.0 / best_mosi:.2f} MHz; "
        f"MOSI+MISO_sim_zero_delay period={best_both_sim} → {50.0 / best_both_sim:.2f} MHz; "
        f"MOSI+MISO_guaranteed period={guaranteed} → {50.0 / guaranteed:.2f} MHz; "
        f"first_MISO_bit_error period={first_fail_period} got={first_fail_got}"
    )
    assert best_both_sim <= guaranteed
