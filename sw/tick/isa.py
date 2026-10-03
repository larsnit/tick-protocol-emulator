"""Single source of truth for Tick ISA encodings (docs/isa.md § Encoding)."""

from __future__ import annotations

from enum import IntEnum


class Op(IntEnum):
    SET = 0b0000
    IN = 0b0001
    WAIT = 0b0010
    JMP = 0b0011
    LDI = 0b0100
    ALU = 0b0101
    XFER = 0b0110
    PULL = 0b0111
    PUSH = 0b1000
    MFS = 0b1001
    MTS = 0b1010


class AluFn(IntEnum):
    MOV = 0
    ADD = 1
    SUB = 2
    AND = 3
    OR = 4
    XOR = 5
    CMP = 6
    SHR = 7


class JmpCond(IntEnum):
    AL = 0
    Z = 1
    NZ = 2
    C = 3
    NC = 4
    R1DEC = 5  # r1--; jump if was non-zero
    E0 = 6
    E1 = 7
    E2 = 8
    E3 = 9
    TK = 10
    LAST = 11
    CMD = 12
    HE = 13
    ERR = 14
    ARB = 15


class WaitTc(IntEnum):
    NONE = 0b00
    REARM = 0b01
    STOP = 0b10
    IDLE = 0b11


class XferMode(IntEnum):
    OUT = 0
    IN = 1
    BOTH = 2


class PushTag(IntEnum):
    DATA = 0
    EOF = 1
    ERR = 2
    EVT = 3


class Spr(IntEnum):
    RX = 0
    RXH = 1
    TIME_L = 2
    TIME_H = 3
    EVF = 4
    ERR = 5
    PER_L = 6
    PER_M = 7
    PER_H = 8
    PHASE_L = 9
    PHASE_H = 10
    ECFG = 11
    PC = 12
    ID = 13


class MissPolicy(IntEnum):
    FLAG = 0
    TRAP = 1
    SEND_DEFAULT = 2
    STRETCH = 3


class PinMode(IntEnum):
    INPUT = 0
    PUSHPULL = 1
    OPENDRAIN = 2


class TickSource(IntEnum):
    TIMER = 0
    PIN_EDGE = 1


# Machine constants
IMEM_WORDS = 64
N_CONTEXTS = 2
N_LOGICAL_PINS = 4
N_EVENTS = 4
READBACK_LATENCY = 3
HOST_FIFO_DEPTH = 8
ID_VALUE = 0x24  # version nibble | imem size code | context count
DEFAULT_BYTE = 0xFF

ALU_NAMES = {fn.name.lower(): fn for fn in AluFn}
JMP_NAMES = {
    "al": JmpCond.AL,
    "z": JmpCond.Z,
    "nz": JmpCond.NZ,
    "c": JmpCond.C,
    "nc": JmpCond.NC,
    "r1--": JmpCond.R1DEC,
    "e0": JmpCond.E0,
    "e1": JmpCond.E1,
    "e2": JmpCond.E2,
    "e3": JmpCond.E3,
    "tk": JmpCond.TK,
    "last": JmpCond.LAST,
    "cmd": JmpCond.CMD,
    "he": JmpCond.HE,
    "err": JmpCond.ERR,
    "arb": JmpCond.ARB,
}
SPR_NAMES = {spr.name.lower(): spr for spr in Spr}
TC_NAMES = {
    None: WaitTc.NONE,
    "rearm": WaitTc.REARM,
    "stop": WaitTc.STOP,
    "idle": WaitTc.IDLE,
}
XFER_MODE_NAMES = {"out": XferMode.OUT, "in": XferMode.IN, "both": XferMode.BOTH}
PUSH_TAG_NAMES = {
    "data": PushTag.DATA,
    "eof": PushTag.EOF,
    "err": PushTag.ERR,
    "evt": PushTag.EVT,
}


def encode_set(timed: bool, oe: bool, mask: int, val: int) -> int:
    return (Op.SET << 12) | ((1 if timed else 0) << 11) | ((1 if oe else 0) << 10) | ((mask & 0xF) << 6) | ((val & 0xF) << 2)


def encode_in(timed: bool, lp: int) -> int:
    return (Op.IN << 12) | ((1 if timed else 0) << 11) | ((lp & 0x3) << 9)


def encode_wait(tc: int, evmask: int) -> int:
    return (Op.WAIT << 12) | ((tc & 0x3) << 10) | ((evmask & 0x1F) << 5)


def encode_jmp(cond: int, addr: int) -> int:
    return (Op.JMP << 12) | ((cond & 0xF) << 8) | ((addr & 0x3F) << 2)


def encode_ldi(rd: int, imm: int) -> int:
    return (Op.LDI << 12) | ((rd & 0x3) << 10) | (imm & 0xFF)


def encode_alu(fn: int, rd: int, rs: int) -> int:
    return (Op.ALU << 12) | ((fn & 0x7) << 9) | ((rd & 0x3) << 7) | ((rs & 0x3) << 5)


def encode_xfer(rs: int, n: int, mode: int) -> int:
    # n is 1..16 encoded as 0..15. XFER width: out/both ≤8; in may be ≤16.
    if mode in (XferMode.OUT, XferMode.BOTH) and n > 8:
        raise ValueError("XFER out/both width must be 1..8")
    if mode == XferMode.IN and not (1 <= n <= 16):
        raise ValueError("XFER in width must be 1..16")
    if not 1 <= n <= 16:
        raise ValueError("XFER n must be 1..16")
    return (Op.XFER << 12) | ((rs & 0x3) << 10) | (((n - 1) & 0xF) << 6) | ((mode & 0x3) << 4)


def encode_pull(rd: int, nb: bool) -> int:
    return (Op.PULL << 12) | ((rd & 0x3) << 10) | ((1 if nb else 0) << 9)


def encode_push(rs: int, tag: int) -> int:
    return (Op.PUSH << 12) | ((rs & 0x3) << 10) | ((tag & 0x3) << 8)


def encode_mfs(rd: int, spr: int) -> int:
    return (Op.MFS << 12) | ((rd & 0x3) << 10) | ((spr & 0xF) << 6)


def encode_mts(rs: int, spr: int) -> int:
    return (Op.MTS << 12) | ((rs & 0x3) << 10) | ((spr & 0xF) << 6)


def decode(word: int) -> dict:
    op = Op((word >> 12) & 0xF)
    d: dict = {"op": op, "raw": word}
    if op == Op.SET:
        d.update(timed=bool(word & (1 << 11)), oe=bool(word & (1 << 10)), mask=(word >> 6) & 0xF, val=(word >> 2) & 0xF)
    elif op == Op.IN:
        d.update(timed=bool(word & (1 << 11)), lp=(word >> 9) & 0x3)
    elif op == Op.WAIT:
        d.update(tc=(word >> 10) & 0x3, evmask=(word >> 5) & 0x1F)
    elif op == Op.JMP:
        d.update(cond=(word >> 8) & 0xF, addr=(word >> 2) & 0x3F)
    elif op == Op.LDI:
        d.update(rd=(word >> 10) & 0x3, imm=word & 0xFF)
    elif op == Op.ALU:
        d.update(fn=(word >> 9) & 0x7, rd=(word >> 7) & 0x3, rs=(word >> 5) & 0x3)
    elif op == Op.XFER:
        d.update(rs=(word >> 10) & 0x3, n=((word >> 6) & 0xF) + 1, mode=(word >> 4) & 0x3)
    elif op == Op.PULL:
        d.update(rd=(word >> 10) & 0x3, nb=bool(word & (1 << 9)))
    elif op == Op.PUSH:
        d.update(rs=(word >> 10) & 0x3, tag=(word >> 8) & 0x3)
    elif op == Op.MFS:
        d.update(rd=(word >> 10) & 0x3, spr=(word >> 6) & 0xF)
    elif op == Op.MTS:
        d.update(rs=(word >> 10) & 0x3, spr=(word >> 6) & 0xF)
    return d
