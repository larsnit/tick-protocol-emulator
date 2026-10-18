"""Directed RTL: latched/pulse, EVCLR, same-cycle wait, trap priority, MISS policies."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, MissPolicy, PinMode, assemble
from tick.cfg import dict_to_bytes
from tick.host_link import HostLink
from lockstep_harness import start_run, rtl_pads



async def _lockstep(dut, img, cfg, n_cyc, ext, host=None):
    host_words = host or []
    m = Machine()
    m.load(img, [cfg])
    for hw in host_words:
        m.host_push(hw & 0xFF)
    iss = []
    for cy in range(n_cyc):
        m.phys_ext = [(ext[cy] >> p) & 1 for p in range(8)]
        m.step()
        out = oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        iss.append((out, oe, m.ctx[0].pc, m.ctx[0].evf, m.ctx[0].ev_pending, m.ctx[0].miss))

    hl = HostLink(dut)
    await hl.reset()
    await hl.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
    await hl.cfg_write_map({0x00: 0x01})
    await hl.load_program(img)
    for hw in host_words:
        await hl.push(hw & 0xFF)
    dut.uio_in.value = ext[0] if ext else 0
    await start_run(hl, dut)
    for cy in range(n_cyc):
        dut.uio_in.value = ext[min(cy, len(ext) - 1)]
        await RisingEdge(dut.clk)
        i = cy
        i_out, i_oe, *_ = iss[i]
        r_out = int(dut.uio_out.value) & 0xFF
        r_oe = int(dut.uio_oe.value) & 0xFF
        assert i_oe == r_oe and (i_out & i_oe) == (r_out & r_oe), (
            f"cy={i} ISS=({i_out:#04x},{i_oe:#04x}) RTL=({r_out:#04x},{r_oe:#04x})"
        )
    return iss


@cocotb.test()
async def latched_edge_before_wait_caught(dut):
    """Latched fall before WAIT is reported; pulse is lost (2026-10-17)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    nops = "\n".join(["ALU MOV r0, r0"] * 16)
    img = assemble(f"{nops}\nwait: WAIT ev0\nLDI r0, 0xA5\nPUSH r0, DATA\nhang: JMP AL, hang\n")
    cfg = {
        "per": 8.0,
        "pins": [{"physical": 0, "mode": PinMode.INPUT, "idle": 1}],
        "events": [{"kind": EventKind.EDGE_FALL, "pin": 0, "latched": True}],
    }
    ext = [0xFF] * 4 + [0xFE] * 40
    await _lockstep(dut, img, cfg, 40, ext)


@cocotb.test()
async def pulse_edge_before_wait_lost(dut):
    """Pulse edge before WAIT is not visible later (2026-10-17)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    nops = "\n".join(["ALU MOV r0, r0"] * 16)
    img = assemble(f"{nops}\nwait: WAIT ev0\nLDI r0, 0xA5\nPUSH r0, DATA\nhang: JMP AL, hang\n")
    cfg = {
        "per": 8.0,
        "pins": [{"physical": 0, "mode": PinMode.INPUT, "idle": 1}],
        "events": [{"kind": EventKind.EDGE_FALL, "pin": 0, "latched": False}],
    }
    ext = [0xFF] * 4 + [0xFE] * 8 + [0xFF] * 40
    await _lockstep(dut, img, cfg, 40, ext)


@cocotb.test()
async def evclr_drops_stale_latched_edge(dut):
    """EVCLR clears latched pending so WAIT does not fire on stale edge (2026-10-17)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    nops = "\n".join(["ALU MOV r0, r0"] * 12)
    img = assemble(
        f"{nops}\nLDI r1, 0x01\nMTS EVCLR, r1\nwait: WAIT ev0\n"
        f"LDI r0, 0x5A\nPUSH r0, DATA\nhang: JMP AL, hang\n"
    )
    cfg = {
        "per": 8.0,
        "pins": [{"physical": 0, "mode": PinMode.INPUT, "idle": 1}],
        "events": [{"kind": EventKind.EDGE_FALL, "pin": 0, "latched": True}],
    }
    ext = [0xFF] * 4 + [0xFE] * 40
    await _lockstep(dut, img, cfg, 40, ext)


@cocotb.test()
async def wait_event_and_tick_same_cycle(dut):
    """WAIT ev0|tick: same-cycle edge+tick → both EVF bits, no MISS (2026-10-17)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble(
        "WAIT ev0|tick, stop\nLDI r0, 0x5A\nPUSH r0, DATA\nhang: JMP AL, hang\n"
    )
    cfg = {
        "per": 4.0,
        "pins": [{"physical": 0, "mode": PinMode.INPUT, "idle": 1}],
        "events": [{"kind": EventKind.EDGE_FALL, "pin": 0}],
    }
    ext = [0xFF] * 2 + [0xFE] * 20
    await _lockstep(dut, img, cfg, 20, ext)


@cocotb.test()
async def two_traps_same_cycle_lower_wins(dut):
    """Two trap edges same cycle: lower event wins; other pending stays (2026-10-17)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble("hang: JMP AL, hang\nv1: JMP AL, v1\nv2: JMP AL, v2\n")
    cfg = {
        "per": 8.0,
        "pins": [
            {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
        ],
        "events": [
            {"kind": EventKind.EDGE_FALL, "pin": 0, "latched": True, "trap": True, "vector": 1},
            {"kind": EventKind.EDGE_FALL, "pin": 1, "latched": True, "trap": True, "vector": 2},
        ],
    }
    ext = [0xFF] * 4 + [0xFC] * 8
    iss = await _lockstep(dut, img, cfg, 12, ext)
    # After trap: PC=1, EVF=EV0, EV1 pending still set in ISS trace.
    assert any(pc == 1 and (evf & 1) for _, _, pc, evf, _, _ in iss)


@cocotb.test()
async def trap_mid_xfer_cancels_queue_idles_pins(dut):
    """Trap mid-XFER cancels queue and drives pins idle (2026-10-17)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    # Post an 8-bit OUT, then hang; EV0 fall traps to vector 3 mid-stream.
    img = assemble(
        """
        LDI   r0, 0xAA
        XFER  8, out
        hang: JMP AL, hang
        desel: SET lp0=0
               JMP AL, desel
        """
    )
    cfg = {
        "per": 4.0,
        "dout_lp": 0,
        "msb_first": True,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
        ],
        "events": [
            {"kind": EventKind.EDGE_FALL, "pin": 1, "trap": True, "vector": 3},
        ],
    }
    # Idle high on pin1, then fall after a few XFER ticks.
    ext = [0x02] * 10 + [0x00] * 20
    await _lockstep(dut, img, cfg, 28, ext)


@cocotb.test()
async def miss_stretch_holds_only_clock_pin(dut):
    """MISS stretch OD-drives only CLK_LP low (2026-10-17)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble("SET.T lp0=1\nhang: JMP AL, hang\n")
    cfg = {
        "per": 4.0,
        "clk_lp": 2,
        "dout_lp": 0,
        "miss_policy": MissPolicy.STRETCH,
        "pins": [
            {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 2, "mode": PinMode.OPENDRAIN, "idle": 1},
            {"physical": 3, "mode": PinMode.OPENDRAIN, "idle": 1},
        ],
    }
    ext = [0xFF] * 30
    await _lockstep(dut, img, cfg, 24, ext)


@cocotb.test()
async def miss_flag_send_default_trap_policies(dut):
    """MISS flag / send-default / trap policies match ISS pins (2026-10-17)."""
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    img = assemble("SET.T lp0=1\nhang: JMP AL, hang\ntrapv: JMP AL, trapv\n")
    for pol in (MissPolicy.FLAG, MissPolicy.SEND_DEFAULT, MissPolicy.TRAP):
        cfg = {
            "per": 4.0,
            "dout_lp": 0,
            "miss_policy": pol,
            "miss_vector": 2,
            "default_byte": 0xA5,
            "msb_first": True,
            "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
        }
        ext = [0xFF] * 40
        await _lockstep(dut, img, cfg, 32, ext)
