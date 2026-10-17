"""ISS Stage 2b property tests: ALU flags, ECFG, overrun/arb, PULL.NB, MTS PC."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import Machine, PinMode, TickSource, assemble
from tick.isa import AluFn, ID_VALUE, Spr


def _cfg(**kw):
    base = {
        "per": 4.0,
        "phase": 0,
        "msb_first": False,
        "tick_source": TickSource.TIMER,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
        ],
    }
    base.update(kw)
    return base


def test_alu_sub_borrow_and_equality():
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [_cfg()])
    c = m.ctx[0]
    c.regs[0], c.regs[1] = 1, 2
    m._alu(c, AluFn.SUB, 0, 1)
    assert c.regs[0] == 0xFF and c.c and not c.z
    c.regs[0], c.regs[1] = 5, 5
    m._alu(c, AluFn.SUB, 0, 1)
    assert c.regs[0] == 0 and not c.c and c.z


def test_alu_cmp_flags_no_write():
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [_cfg()])
    c = m.ctx[0]
    c.regs[0], c.regs[1] = 3, 5
    m._alu(c, AluFn.CMP, 0, 1)
    assert c.regs[0] == 3 and c.c and not c.z


def test_alu_logic_clears_c_mov_clears_c():
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [_cfg()])
    c = m.ctx[0]
    c.c = True
    c.regs[0], c.regs[1] = 0xF0, 0x0F
    m._alu(c, AluFn.AND, 0, 1)
    assert c.regs[0] == 0 and not c.c and c.z
    c.c = True
    c.regs[0], c.regs[1] = 1, 2
    m._alu(c, AluFn.MOV, 0, 1)
    assert c.regs[0] == 2 and not c.c


def test_alu_shr_carry():
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [_cfg()])
    c = m.ctx[0]
    c.regs[0] = 0x05
    m._alu(c, AluFn.SHR, 0, 0)
    assert c.regs[0] == 0x02 and c.c and not c.z


def test_ecfg_alias_rw():
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [_cfg()])
    c = m.ctx[0]
    m._write_spr(c, Spr.ECFG, 0x0F)
    assert c.ecfg_msb_first and c.ecfg_clk_en and c.ecfg_cpha and c.ecfg_cpol
    assert m._read_spr(c, Spr.ECFG) == 0x0F
    m._write_spr(c, Spr.ECFG, 0xF0)  # high bits ignored
    assert m._read_spr(c, Spr.ECFG) == 0x00


def test_pull_nb_under_default():
    m = Machine()
    m.load(
        assemble(
            """
            PULL.NB r0
            hang: JMP AL, hang
            """
        ),
        [_cfg(default_byte=0xA5)],
    )
    m.step()
    assert m.ctx[0].regs[0] == 0xA5
    assert m.ctx[0].under
    assert not m.ctx[0].last and not m.ctx[0].cmd


def test_overrun_on_second_xfer():
    m = Machine()
    m.load(
        assemble(
            """
            LDI r0, 0x55
            XFER r0, 2, out
            XFER r0, 2, out
            hang: JMP AL, hang
            """
        ),
        [_cfg(per=2.0)],
    )
    for _ in range(40):
        m.step()
        if m.ctx[0].overrun:
            break
    assert m.ctx[0].overrun
    assert m.ctx[0].result_valid


def test_mts_pc_computed_jump():
    m = Machine()
    m.load(
        assemble(
            """
            LDI r0, 4
            MTS PC, r0
            hang: JMP AL, hang
            nop0: ALU MOV r0, r0
            here: SET lp0=1
            loop: JMP AL, loop
            """
        ),
        [_cfg()],
    )
    for _ in range(8):
        m.step()
        if m.phys_oe[0] and m.phys_drive[0]:
            break
    assert m.phys_oe[0] and m.phys_drive[0]
    assert m.ctx[0].pc in (4, 5)


def test_id_value():
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [_cfg()])
    assert m._read_spr(m.ctx[0], Spr.ID) == ID_VALUE


def test_evclr_stub_reads_zero_without_latch():
    m = Machine()
    m.load(assemble("hang: JMP AL, hang\n"), [_cfg()])
    assert m._read_spr(m.ctx[0], Spr.EVCLR) == 0
