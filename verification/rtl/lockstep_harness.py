"""ISS↔RTL lockstep without guessed ALIGN constants.

Timeline (measured on this SPI host link):
  - CTRL.RUN is applied on CS_n rise → ``uo[2]`` rises that cycle.
  - Core sync-snap / first execute are on the **next** rising ``clk`` edge
    (``UO_RUN_LEAD_CYCLES`` = 1). See docs/isa.md.
  - ISS cycle 0 = that first execute edge.

Pad compares use the **registered** top-level ``uio_out`` / ``uio_oe`` (same as
tick-ref lockstep). ISS ``phys_*`` matches those registered pads on the same
execute index; the queue's combinational ``q_uio_*_c`` leads by one cycle and
must not be used for lockstep equality.

Pin stimuli are driven before each rising execute edge (same protocol as tick-ref).
"""

from __future__ import annotations

from typing import Callable, Sequence

import cocotb
from cocotb.triggers import RisingEdge

from tick import Machine
from tick.host_link import HostLink


def _uo_run(dut) -> int:
    return (int(dut.uo_out.value) >> 2) & 1


def _core(dut):
    return dut.user_project.core


# Measured: uo[2] rises one cycle before the first core execute edge.
UO_RUN_LEAD_CYCLES = 1


async def await_run_rise(dut) -> None:
    """Block until uo[2] rises (sampled after a rising clk edge)."""
    prev = _uo_run(dut)
    while True:
        await RisingEdge(dut.clk)
        cur = _uo_run(dut)
        if cur and not prev:
            return
        prev = cur


async def start_run(host: HostLink, dut, iss: Machine | None = None):
    """Kick CTRL.RUN via SPI; return right after uo RUN rises.

    The next rising ``clk`` after a falling-edge pin setup is execute cycle 0.
    If ``iss`` is given, snap its pin sync to match RTL run-rise.

    Caller must drive ``dut.uio_in`` to the intended pre-RUN pin vector *before*
    calling this (RTL snaps pin sync on the first execute / run-rise edge).
    """
    task = cocotb.start_soon(host.run(settle="timer"))
    await await_run_rise(dut)
    if iss is not None:
        iss._snap_inputs_after_enable()
    await task
    return task


def _ext_bits(byte: int) -> list[int]:
    return [(byte >> p) & 1 for p in range(8)]


def _pad_out(m: Machine) -> tuple[int, int]:
    out = oe = 0
    for p in range(8):
        if m.phys_oe[p]:
            oe |= 1 << p
            out |= (m.phys_drive[p] & 1) << p
    return out, oe


def _apply_fifo_strobes(m: Machine, dut) -> None:
    """Mirror core-side host FIFO strobes into the ISS (same cycle as RTL)."""
    spi = dut.user_project.u_host
    wr = int(spi.host_wr.value)
    rd = int(spi.host_rd.value)
    wdata = int(spi.host_wdata.value)
    if wr:
        if len(m.host_to_core) < 8:
            m.host_push(wdata & 0xFF, last=bool(wdata & 0x100), cmd=bool(wdata & 0x200))
    if rd:
        m.host_pop()


def drive_ext(m: Machine, dut, byte: int) -> None:
    """Drive pad inputs for the upcoming rising edge.

    ISS end-captures ``phys_ext`` at the end of ``step()`` (same model as
    tick-ref offline lockstep). Do not refresh ``_pin_sample`` here — that
    makes the ISS synchroniser one cycle early vs RTL and breaks pin-edge
    protocols (SPI/I2C target).
    """
    dut.uio_in.value = byte & 0xFF
    m.phys_ext = _ext_bits(byte)


def rtl_pads(dut) -> tuple[int, int]:
    """Registered top-level pads (matches ISS phys_* on the same execute cycle)."""
    out = int(dut.uio_out.value) & 0xFF
    oe = int(dut.uio_oe.value) & 0xFF
    return out, oe


# SPI vs tick-ref parallel bus: first post-RUN edge is snap+exec (tick-ref had a
# non-exec run-rise). Discard that edge on both sides, then present ext one
# cycle early on RTL so pin-edge ticks match ISS end-of-cycle capture.
SPI_EXEC_WARMUP = 1
SPI_PIN_LEAD = 1


async def rtl_run_pad_trace(
    dut,
    host: HostLink,
    n_cyc: int,
    ext: Sequence[int],
    *,
    pin_lead: int = SPI_PIN_LEAD,
    warmup: int = SPI_EXEC_WARMUP,
) -> list[tuple[int, int]]:
    """Registered pad (out, oe) per recorded execute cycle after SPI RUN.

    Warmup edges are discarded; ``pin_lead`` shifts the ext index for RTL.
    """
    await start_run(host, dut)
    for _ in range(warmup):
        dut.uio_in.value = ext[0] if ext else 0
        await RisingEdge(dut.clk)
    rtl: list[tuple[int, int]] = []
    for cy in range(n_cyc):
        idx = min(cy + pin_lead, len(ext) - 1) if ext else 0
        dut.uio_in.value = ext[idx] if ext else 0
        await RisingEdge(dut.clk)
        rtl.append(rtl_pads(dut))
    return rtl


async def lockstep_pins(
    dut,
    host: HostLink,
    iss: Machine,
    n_cyc: int,
    ext: Sequence[int],
    *,
    compare: Callable[[int, Machine], None] | None = None,
    apply_fifo: bool = True,
    align: int | None = None,
) -> list[tuple[int, int]]:
    """Run from observed RUN rise; lockstep ISS↔registered RTL pads.

    ``align`` (default ``UO_RUN_LEAD_CYCLES`` = 1) is the measured lag from ISS
    ``phys_*`` to registered ``uio_out``/``uio_oe`` — same role as tick-ref's
    ALIGN on pad outputs. ISS cycle i is compared to RTL cycle i+align.
    Core and ISS both execute on cycles 0..n_cyc-1; ``align`` trailing RTL
    cycles flush the pad registers.
    """
    if align is None:
        align = UO_RUN_LEAD_CYCLES
    await start_run(host, dut, iss)
    rtl: list[tuple[int, int]] = []
    iss_pads: list[tuple[int, int]] = []
    for cy in range(n_cyc + align):
        byte = ext[min(cy, len(ext) - 1)] if ext else 0
        drive_ext(iss, dut, byte)
        await RisingEdge(dut.clk)
        if cy < n_cyc:
            iss.step()
            if apply_fifo:
                _apply_fifo_strobes(iss, dut)
            iss_pads.append(_pad_out(iss))
        out, oe = rtl_pads(dut)
        rtl.append((out, oe))
        if compare is not None and cy < n_cyc:
            compare(cy, iss)
    if compare is None:
        for i in range(n_cyc):
            io, ie = iss_pads[i]
            out, oe = rtl[i + align]
            if ie != oe or (io & ie) != (out & oe):
                raise AssertionError(
                    f"cy={i} ISS=({io:#04x},{ie:#04x}) RTL=({out:#04x},{oe:#04x})"
                )
    return rtl
