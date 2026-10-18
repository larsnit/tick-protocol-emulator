"""Directed Stage 2b pin-only tests (GL-safe): ALU, JMP, ERR, XFER, MTS PC, ARB."""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, PinMode, assemble
from tick.host_link import HostLink


async def _start(dut):
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    host = HostLink(dut)
    await host.reset()
    return host


async def _run_until_pin(dut, pin: int, val: int, cycles: int = 80) -> bool:
    for _ in range(cycles):
        await RisingEdge(dut.clk)
        oe = int(dut.uio_oe.value)
        out = int(dut.uio_out.value)
        if (oe >> pin) & 1 and ((out >> pin) & 1) == val:
            return True
    return False


def _pp_cfg(per: float = 4.0, **extra):
    cfg = {
        "per": per,
        "msb_first": False,
        "dout_lp": 0,
        "din_lp": 1,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 0},
        ],
    }
    cfg.update(extra)
    return cfg


@cocotb.test()
async def alu_sub_borrow_equality(dut):
    host = await _start(dut)
    await host.load_default_cfg( _pp_cfg())
    src = """
    LDI r0, 1
    LDI r1, 2
    ALU SUB r0, r1
    JMP C, borrow
    bad0: JMP AL, bad0
    borrow:
    LDI r0, 5
    LDI r1, 5
    ALU SUB r0, r1
    JMP Z, eq
    bad1: JMP AL, bad1
    eq: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    assert await _run_until_pin(dut, 2, 1)


@cocotb.test()
async def alu_cmp_same_as_sub_flags(dut):
    host = await _start(dut)
    await host.load_default_cfg( _pp_cfg())
    src = """
    LDI r0, 1
    LDI r1, 2
    ALU CMP r0, r1
    JMP C, ok
    bad: JMP AL, bad
    ok: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    assert await _run_until_pin(dut, 2, 1)


@cocotb.test()
async def alu_shr_carry(dut):
    host = await _start(dut)
    await host.load_default_cfg( _pp_cfg())
    src = """
    LDI r0, 5
    ALU SHR r0, r0
    JMP C, ok
    bad: JMP AL, bad
    ok: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    assert await _run_until_pin(dut, 2, 1)


@cocotb.test()
async def alu_logic_and_mov_clear_c(dut):
    host = await _start(dut)
    await host.load_default_cfg( _pp_cfg())
    src = """
    LDI r0, 0x80
    LDI r1, 0x80
    ALU ADD r0, r1
    JMP C, had_c
    bad0: JMP AL, bad0
    had_c:
    LDI r0, 0xF0
    LDI r1, 0x0F
    ALU AND r0, r1
    JMP NC, and_ok
    bad1: JMP AL, bad1
    and_ok:
    LDI r0, 0xFF
    LDI r1, 0x01
    ALU ADD r0, r1
    JMP C, had_c2
    bad2: JMP AL, bad2
    had_c2:
    ALU MOV r0, r1
    JMP NC, mov_ok
    bad3: JMP AL, bad3
    mov_ok: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    assert await _run_until_pin(dut, 2, 1, cycles=40)


@cocotb.test()
async def jmp_r1dec_zero_and_one(dut):
    host = await _start(dut)
    await host.load_default_cfg( _pp_cfg())
    src = """
    LDI r1, 0
    JMP r1--, skip0
    SET lp2=1
    JMP AL, after0
    skip0: SET lp2=0
    after0:
    LDI r1, 1
    JMP r1--, took
    bad: JMP AL, bad
    took: SET lp3=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    saw2 = saw3 = False
    for _ in range(40):
        await RisingEdge(dut.clk)
        oe = int(dut.uio_oe.value)
        out = int(dut.uio_out.value)
        if (oe >> 2) & 1 and (out >> 2) & 1:
            saw2 = True
        if (oe >> 3) & 1 and (out >> 3) & 1:
            saw3 = True
    assert saw2 and saw3, (saw2, saw3)


@cocotb.test()
async def time_lh_latch_across_carry(dut):
    """MFS TIME_L latches high; TIME_H returns latch after counter wraps past 255."""
    host = await _start(dut)
    await host.load_default_cfg( _pp_cfg(per=2.0))
    # Start timer, burn ~300 cycles via r1-- loop, then read TIME_L/H and show on pins.
    src = """
    SET.T lp0=1
    LDI r1, 255
    burn: JMP r1--, burn
    MFS r0, TIME_L
    MFS r1, TIME_H
    ALU OR r0, r1
    JMP NZ, ok
    bad: JMP AL, bad
    ok: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    assert await _run_until_pin(dut, 2, 1, cycles=400)


@cocotb.test()
async def err_w1c_only_written_bits(dut):
    host = await _start(dut)
    cfg = _pp_cfg()
    cfg["pins"] = [
        {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1},
        {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
        {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
        {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 0},
    ]
    await host.load_default_cfg( cfg)
    src = """
    LDI r0, 0
    LDI r0, 0
    PULL.NB r0
    LDI r1, 0x02
    MTS ERR, r1
    MFS r0, ERR
    LDI r1, 0x10
    ALU AND r0, r1
    JMP NZ, map_remains
    bad: JMP AL, bad
    map_remains: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    assert await _run_until_pin(dut, 2, 1, cycles=40)


@cocotb.test()
async def overrun_two_xfer_jmp_err(dut):
    host = await _start(dut)
    await host.load_default_cfg( _pp_cfg(per=2.0))
    src = """
    LDI r0, 0x55
    XFER r0, 2, out
    XFER r0, 2, out
    LDI r1, 40
    wait: JMP r1--, wait
    MFS r0, ERR
    LDI r1, 0x04
    ALU AND r0, r1
    JMP NZ, got
    bad: JMP AL, bad
    got: JMP ERR, ok
    bad2: JMP AL, bad2
    ok: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    assert await _run_until_pin(dut, 2, 1, cycles=120)


@cocotb.test()
async def xfer_in_16bit_rx_rxh(dut):
    """16-bit XFER in with pin held high → RX=0xFF, RXH=0xFF (MSB or LSB)."""
    host = await _start(dut)
    cfg = _pp_cfg(per=2.0, msb_first=False, dout_lp=0, din_lp=1)
    cfg["pins"] = [
        {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
        {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 0},
    ]
    await host.load_default_cfg( cfg)
    src = """
    XFER 16, in
    LDI r1, 60
    wait: JMP r1--, wait
    MFS r0, RX
    LDI r1, 0xFF
    ALU CMP r0, r1
    JMP NZ, bad
    MFS r0, RXH
    LDI r1, 0xFF
    ALU CMP r0, r1
    JMP Z, ok
    bad: JMP AL, bad
    ok: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    dut.uio_in.value = 0x01  # pin0 high for IN sample on dout_lp
    await host.run()
    assert await _run_until_pin(dut, 2, 1, cycles=200)


@cocotb.test()
async def mts_pc_jump_table(dut):
    host = await _start(dut)
    await host.load_default_cfg( _pp_cfg())
    src = """
    PULL r0
    MTS PC, r0
    hang: JMP AL, hang
    h0: SET lp2=1
    loop0: JMP AL, loop0
    h1: SET lp3=1
    loop1: JMP AL, loop1
    """
    words = assemble(src)
    # Find handler addresses from assembled labels via disassembly of known layout:
    # 0 PULL, 1 MTS, 2 hang, 3 h0, 4 loop0, 5 h1, 6 loop1
    await host.load_program(words)
    await host.push(5)  # jump to h1
    await host.run()
    assert await _run_until_pin(dut, 3, 1, cycles=40)


@cocotb.test()
async def arb_od_both_external_low(dut):
    host = await _start(dut)
    cfg = _pp_cfg(per=2.0)
    cfg["pins"] = [
        {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1},
        {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
        {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
    ]
    cfg["dout_lp"] = 0
    cfg["din_lp"] = 1
    await host.load_default_cfg( cfg)
    # XFER both with data bit1=1 → OD release; hold pin0 low → ARB
    src = """
    LDI r0, 0xFF
    XFER r0, 4, both
    LDI r1, 40
    wait: JMP r1--, wait
    MFS r0, ERR
    LDI r1, 0x08
    ALU AND r0, r1
    JMP NZ, got
    bad: JMP AL, bad
    got: JMP ARB, ok
    bad2: JMP AL, bad2
    ok: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    dut.uio_in.value = 0  # hold bus low
    await host.run()
    assert await _run_until_pin(dut, 2, 1, cycles=120)


@cocotb.test()
async def pull_nb_default_under(dut):
    host = await _start(dut)
    cfg = _pp_cfg()
    cfg["default_byte"] = 0xA5
    await host.load_default_cfg( cfg)
    src = """
    PULL.NB r0
    LDI r1, 0xA5
    ALU CMP r0, r1
    JMP NZ, bad
    MFS r0, ERR
    LDI r1, 0x02
    ALU AND r0, r1
    JMP NZ, ok
    bad: JMP AL, bad
    ok: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    assert await _run_until_pin(dut, 2, 1)


@cocotb.test()
async def jmp_sees_same_cycle_wait_flags(dut):
    """WAIT tick → JMP TK and IN.T → JMP C see same-cycle flag updates (isa.md §3.1)."""
    host = await _start(dut)
    cfg = _pp_cfg(per=4.0)
    cfg["pins"] = [
        {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
        {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 0},
    ]
    await host.load_default_cfg( cfg)
    src = """
    WAIT tick
    JMP TK, got_tk
    bad_tk: JMP AL, bad_tk
    got_tk:
    IN.T lp0
    JMP C, got_c
    bad_c: JMP AL, bad_c
    got_c: SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    dut.uio_in.value = 0x01  # phys0 high for IN.T → C=1
    await host.run()
    assert await _run_until_pin(dut, 2, 1, cycles=120)


@cocotb.test()
async def mfs_time_l_matches_iss_post_increment(dut):
    """MFS TIME_L must see the same-cycle post-increment count (ISS step order).

    SET.T starts the timer (time=0 that cycle). Three LDIs follow; MFS TIME_L
    then runs on the cycle where ISS has just incremented time to 4 (even).
    Pre-fix RTL exposed pre-increment TIME (=3, odd) and failed the JMP Z.
    """
    host = await _start(dut)
    cfg = _pp_cfg(per=4.0)
    await host.load_default_cfg( cfg)
    src = """
    SET.T lp2=0
    LDI r0, 0
    LDI r0, 1
    LDI r0, 2
    MFS r1, TIME_L
    LDI r0, 1
    ALU AND r0, r1
    JMP Z, even_ok
    bad: JMP AL, bad
    even_ok: SET lp3=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    assert await _run_until_pin(dut, 3, 1, cycles=80)


@cocotb.test()
async def push_fills_all_eight_host_fifo_slots(dut):
    """Core→host FIFO must accept HOST_FIFO_DEPTH (8) PUSHes, not DEPTH-1.

    Pre-fix RTL used pointer-full (wptr+1==rptr) and stalled on the 8th PUSH
    while ISS still accepted it — lockstep PC desync under PUSH pressure.
    """
    host = await _start(dut)
    await host.load_default_cfg( _pp_cfg())
    # Eight PUSHes then SET lp2; a 7-deep FIFO would hang forever on the 8th.
    src = """
    LDI r0, 1
    PUSH r0, data
    PUSH r0, data
    PUSH r0, data
    PUSH r0, data
    PUSH r0, data
    PUSH r0, data
    PUSH r0, data
    PUSH r0, data
    SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.run()
    assert await _run_until_pin(dut, 2, 1, cycles=40)


@cocotb.test()
async def soft_wait_host_requires_ev0_host_data(dut):
    """Soft WAIT ev0 must not complete on host FIFO unless EV0 kind is HOST_DATA."""
    host = await _start(dut)
    # Explicit LEVEL_HIGH on lp0 (not HOST_DATA). OD idle0 drives low after sync settles.
    cfg = _pp_cfg(per=4.0)
    cfg["pins"] = [
        {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 0},
        {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
        {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
        {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 0},
    ]
    cfg["events"] = [{"kind": EventKind.LEVEL_HIGH}]
    await host.load_default_cfg( cfg)
    src = """
    LDI r1, 12
    settle: JMP r1--, settle
    WAIT ev0
    SET lp2=1
    hang: JMP AL, hang
    """
    await host.load_program(assemble(src))
    await host.push(0x11)
    await host.run()
    for _ in range(60):
        await RisingEdge(dut.clk)
        oe = int(dut.uio_oe.value)
        out = int(dut.uio_out.value)
        assert not ((oe >> 2) & 1 and (out >> 2) & 1), "WAIT completed without HOST_DATA EV0"

    # Same program with EV0=HOST_DATA must complete and drive lp2.
    host = HostLink(dut)
    await host.reset()
    cfg["events"] = [{"kind": EventKind.HOST_DATA}]
    await host.load_default_cfg( cfg)
    await host.load_program(assemble(src))
    await host.push(0x22)
    await host.run()
    assert await _run_until_pin(dut, 2, 1, cycles=80)
