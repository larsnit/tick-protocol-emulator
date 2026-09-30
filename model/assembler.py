"""Assembler for Tick ISA assembly syntax (docs/isa.md)."""

from __future__ import annotations

import re
from pathlib import Path

from .opcodes import (
    ALU_NAMES,
    JMP_NAMES,
    PUSH_TAG_NAMES,
    SPR_NAMES,
    TC_NAMES,
    XFER_MODE_NAMES,
    encode_alu,
    encode_in,
    encode_jmp,
    encode_ldi,
    encode_mfs,
    encode_mts,
    encode_pull,
    encode_push,
    encode_set,
    encode_wait,
    encode_xfer,
)

_REG = re.compile(r"^r([0-3])$", re.I)
_LABEL = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _reg(tok: str) -> int:
    m = _REG.match(tok.strip())
    if not m:
        raise ValueError(f"expected register r0-r3, got {tok!r}")
    return int(m.group(1))


def _imm8(tok: str) -> int:
    tok = tok.strip().rstrip(",")
    if tok.lower().startswith("0x"):
        v = int(tok, 16)
    else:
        v = int(tok, 0)
    if not 0 <= v <= 255:
        raise ValueError(f"imm8 out of range: {v}")
    return v


def _parse_set_args(args: str) -> tuple[int, int]:
    """Parse 'tx=0' or 'mask=0b0101,val=0b0001' or 'lp0=1,lp1=0' style."""
    args = args.strip()
    if not args:
        return 0, 0
    # pin=name forms: recognize lpN= or named aliases
    aliases = {"tx": 0, "rx": 0, "miso": 0, "mosi": 1, "sclk": 2, "cs": 3, "sda": 0, "scl": 1}
    mask = 0
    val = 0
    parts = [p.strip() for p in args.split(",") if p.strip()]
    for part in parts:
        if "=" not in part:
            raise ValueError(f"bad SET arg {part!r}")
        k, v = part.split("=", 1)
        k = k.strip().lower()
        v = v.strip().lower()
        bit = 1 if v in ("1", "on", "high", "true") else 0
        if k.startswith("lp") and k[2:].isdigit():
            idx = int(k[2:])
        elif k in aliases:
            idx = aliases[k]
        elif k == "mask":
            mask = int(v, 0) & 0xF
            continue
        elif k == "val":
            val = int(v, 0) & 0xF
            continue
        else:
            raise ValueError(f"unknown SET pin {k!r}")
        mask |= 1 << idx
        if bit:
            val |= 1 << idx
    return mask, val


def _evmask(tok: str) -> int:
    """Parse event mask: 'ev0', 'ev0|ev1|tick', 'tick', or numeric."""
    tok = tok.strip().lower().rstrip(",")
    if tok.startswith("0") or tok.isdigit():
        return int(tok, 0) & 0x1F
    mask = 0
    for part in tok.replace("|", " ").replace(",", " ").split():
        part = part.strip()
        if not part:
            continue
        if part == "tick" or part == "tk":
            mask |= 1 << 4
        elif part.startswith("ev") and part[2:].isdigit():
            mask |= 1 << int(part[2:])
        else:
            raise ValueError(f"bad event token {part!r}")
    return mask


def assemble(text: str) -> list[int]:
    """Assemble assembly text into a list of 16-bit words."""
    lines: list[tuple[int, str]] = []
    labels: dict[str, int] = {}
    pc = 0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        while True:
            if ":" in line:
                lab, rest = line.split(":", 1)
                lab = lab.strip()
                if not _LABEL.match(lab):
                    raise ValueError(f"line {lineno}: bad label {lab!r}")
                if lab.lower() in labels:
                    raise ValueError(f"line {lineno}: duplicate label {lab}")
                labels[lab.lower()] = pc
                line = rest.strip()
                if not line:
                    break
            else:
                lines.append((lineno, line))
                pc += 1
                break

    words: list[int] = []
    for lineno, line in lines:
        try:
            words.append(_assemble_one(line, labels, len(words)))
        except Exception as e:
            raise ValueError(f"line {lineno}: {e}") from e
    if len(words) > 64:
        raise ValueError(f"program too long: {len(words)} > 64")
    return words


def _assemble_one(line: str, labels: dict[str, int], pc: int) -> int:
    # mnemonic may include .T .E .NB suffixes
    parts = line.replace(",", " ").split()
    if not parts:
        raise ValueError("empty")
    mnem = parts[0].lower()
    args = parts[1:]

    base, *suffixes = mnem.split(".")
    timed = "t" in suffixes
    oe = "e" in suffixes
    nb = "nb" in suffixes

    if base == "set":
        mask, val = _parse_set_args(" ".join(parts[1:]).replace(" ", ""))
        # re-parse with commas preserved
        raw_args = line.split(None, 1)[1] if len(parts) > 1 else ""
        mask, val = _parse_set_args(raw_args)
        return encode_set(timed, oe, mask, val)

    if base == "in":
        if len(args) != 1:
            raise ValueError("IN needs one logical pin")
        lp_tok = args[0].lower()
        aliases = {"tx": 0, "rx": 0, "miso": 0, "mosi": 1, "sclk": 2, "cs": 3, "sda": 0, "scl": 1}
        if lp_tok.startswith("lp"):
            lp = int(lp_tok[2:])
        elif lp_tok in aliases:
            lp = aliases[lp_tok]
        else:
            lp = int(lp_tok)
        return encode_in(timed, lp)

    if base == "wait":
        # WAIT evmask[, tc]
        if not args:
            raise ValueError("WAIT needs event mask")
        tc_name = None
        if len(args) >= 2 and args[-1].lower() in ("rearm", "stop", "idle"):
            tc_name = args[-1].lower()
            ev_tok = " ".join(args[:-1])
        else:
            ev_tok = " ".join(args)
        return encode_wait(TC_NAMES[tc_name], _evmask(ev_tok))

    if base == "jmp":
        if len(args) == 1:
            cond = JMP_NAMES["al"]
            dest = args[0].lower()
        elif len(args) == 2:
            cond = JMP_NAMES[args[0].lower()]
            dest = args[1].lower()
        else:
            raise ValueError("JMP needs [cond,] addr")
        if dest in labels:
            addr = labels[dest]
        else:
            addr = int(dest, 0)
        return encode_jmp(cond, addr)

    if base == "ldi":
        if len(args) != 2:
            raise ValueError("LDI needs rd, imm")
        return encode_ldi(_reg(args[0]), _imm8(args[1]))

    if base == "alu":
        # ALU fn rd, rs
        if len(args) != 3:
            raise ValueError("ALU needs fn rd rs")
        fn = ALU_NAMES[args[0].lower()]
        return encode_alu(fn, _reg(args[1]), _reg(args[2]))

    if base == "xfer":
        # XFER [rs,] n, mode   or XFER n, mode (rs ignored for in-only)
        toks = [a.strip() for a in line.split(None, 1)[1].replace(",", " ").split()]
        if len(toks) == 2:
            rs, n, mode = 0, int(toks[0], 0), XFER_MODE_NAMES[toks[1].lower()]
        elif len(toks) == 3:
            if _REG.match(toks[0]):
                rs, n, mode = _reg(toks[0]), int(toks[1], 0), XFER_MODE_NAMES[toks[2].lower()]
            else:
                rs, n, mode = 0, int(toks[0], 0), XFER_MODE_NAMES[toks[1].lower()]
        else:
            raise ValueError("XFER: use 'XFER [rs,] n, mode'")
        if not 1 <= n <= 16:
            raise ValueError("XFER n must be 1..16")
        return encode_xfer(rs, n, mode)

    if base == "pull":
        if len(args) != 1:
            raise ValueError("PULL needs rd")
        return encode_pull(_reg(args[0]), nb)

    if base == "push":
        if len(args) != 2:
            raise ValueError("PUSH needs rs, tag")
        return encode_push(_reg(args[0]), PUSH_TAG_NAMES[args[1].lower()])

    if base == "mfs":
        if len(args) != 2:
            raise ValueError("MFS needs rd, spr")
        return encode_mfs(_reg(args[0]), SPR_NAMES[args[1].lower()])

    if base == "mts":
        if len(args) != 2:
            raise ValueError("MTS needs spr, rs OR rs, spr — use 'MTS spr, rs'")
        # Draft: MTS spr, rs — but encoding is ss,r. Accept both orders if second is reg.
        if _REG.match(args[1]):
            spr = SPR_NAMES[args[0].lower()]
            rs = _reg(args[1])
        else:
            rs = _reg(args[0])
            spr = SPR_NAMES[args[1].lower()]
        return encode_mts(rs, spr)

    if base == "nop":
        return encode_alu(ALU_NAMES["mov"], 0, 0)

    raise ValueError(f"unknown mnemonic {mnem!r}")


def assemble_file(path: str | Path) -> list[int]:
    return assemble(Path(path).read_text())
