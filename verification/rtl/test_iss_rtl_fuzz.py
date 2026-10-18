"""Full ISS↔RTL lockstep: Stage 2a pin mix + Stage 2b datapath, executed coverage."""

from __future__ import annotations

import os
import random
import sys
from pathlib import Path

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))

from tick import EventKind, Machine, MissPolicy, PinMode, TickSource
from tick.cfg import dict_to_bytes
from tick.isa import (
    AluFn,
    JmpCond,
    Op,
    PushTag,
    Spr,
    WaitTc,
    XferMode,
    decode,
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
from tick.host_link import HostLink
from lockstep_harness import rtl_run_pad_trace, start_run

DEFAULT_SEED = 0xB22D_F2B2
ENV_SEED = "TICK_RTL_FUZZ_SEED"
ENV_N_PROG = "TICK_RTL_FUZZ_N"
ENV_N_CYC = "TICK_RTL_FUZZ_CYC"
N_PROG = 50
N_WORDS = 40
N_CYC = 80

HOST_PRELOAD = 8

MODE_NAMES = {
    PinMode.INPUT: "input",
    PinMode.PUSHPULL: "pushpull",
    PinMode.OPENDRAIN: "opendrain",
}


def random_ecfg_byte(rng: random.Random, *, msb: bool | None = None, clk_en: bool | None = None) -> int:
    """Random ECFG nibble: MSB | CLK_EN | CPHA | CPOL."""
    bit0 = rng.randrange(2) if msb is None else (1 if msb else 0)
    bit1 = rng.randrange(2) if clk_en is None else (1 if clk_en else 0)
    bit2 = rng.randrange(2)  # CPHA
    bit3 = rng.randrange(2)  # CPOL
    return bit0 | (bit1 << 1) | (bit2 << 2) | (bit3 << 3)


def _seed() -> int:
    raw = os.environ.get(ENV_SEED)
    if raw is None or raw == "":
        return DEFAULT_SEED
    return int(raw, 0)


def _n_prog() -> int:
    raw = os.environ.get(ENV_N_PROG)
    if raw is None or raw == "":
        return N_PROG
    return int(raw, 0)


def _n_cyc() -> int:
    raw = os.environ.get(ENV_N_CYC)
    if raw is None or raw == "":
        return N_CYC
    return int(raw, 0)


def _rand_event(rng: random.Random) -> dict:
    kind = rng.choice(list(EventKind))
    e: dict = {"kind": kind, "pin": rng.randrange(4), "qual_pin": rng.randrange(4)}
    if kind in (
        EventKind.EDGE_RISE,
        EventKind.EDGE_FALL,
        EventKind.QUAL_FALL_WHILE_HIGH,
        EventKind.QUAL_RISE_WHILE_HIGH,
    ):
        e["latched"] = bool(rng.randrange(2))
    # Trap vectors are rewritten to in-image PCs after the program is built.
    e["trap"] = bool(rng.randrange(3) == 0)  # ~1/3 of selectors trap-enabled
    e["vector"] = rng.randrange(N_WORDS)
    return e


def _clamp_trap_vectors(cfg: dict, img: list[int]) -> None:
    """Point every trap / MISS vector at a random existing instruction."""
    n = max(1, len(img))
    for e in cfg.get("events", []):
        if e.get("trap"):
            e["vector"] = int(e.get("vector", 0)) % n
        else:
            e["vector"] = int(e.get("vector", 0)) % n
    cfg["miss_vector"] = int(cfg.get("miss_vector", 0)) % n


def gen_legal_cfg(rng: random.Random) -> dict:
    phys = list(range(8))
    rng.shuffle(phys)
    pinmap = phys[:4]
    modes: list[PinMode] = []
    pins = []
    for i in range(4):
        mode = rng.choice([PinMode.INPUT, PinMode.PUSHPULL, PinMode.OPENDRAIN])
        modes.append(mode)
        pins.append(
            {
                "physical": pinmap[i],
                "mode": mode,
                "idle": rng.randrange(2),
                "glitch_filter": bool(rng.randrange(2)),
            }
        )
    driveable = [i for i, m in enumerate(modes) if m != PinMode.INPUT]
    if not driveable:
        i = rng.randrange(4)
        modes[i] = PinMode.PUSHPULL
        pins[i]["mode"] = PinMode.PUSHPULL
        driveable = [i]
    dout = rng.choice(driveable)
    din_cands = [i for i in range(4) if i != dout]
    din = rng.choice(din_cands) if din_cands else dout
    od = [i for i, m in enumerate(modes) if m == PinMode.OPENDRAIN]
    clk = rng.choice(od) if od else dout
    miss_pol = rng.choice(list(MissPolicy))
    if miss_pol == MissPolicy.STRETCH and not od:
        # Stretch needs an OD clock pin — force one.
        clk = dout
        modes[clk] = PinMode.OPENDRAIN
        pins[clk]["mode"] = PinMode.OPENDRAIN
        pins[clk]["idle"] = 1
    clk_en = bool(rng.randrange(2))
    tick_source = rng.choice([TickSource.TIMER, TickSource.PIN_EDGE])
    # Controller = timer + optionally CLK_EN; target = pin-edge (+ CLK_EN for both edges).
    tick_pin = clk if (clk_en and tick_source == TickSource.PIN_EDGE) else rng.randrange(4)
    tick_on_rise = bool(rng.randrange(2))
    return {
        "per": float(rng.choice([4.0, 8.0, 16.0])),
        "phase": 0,
        "msb_first": bool(rng.randrange(2)),
        "clk_en": clk_en,
        "cpol": bool(rng.randrange(2)),
        "cpha": bool(rng.randrange(2)),
        "dout_lp": dout,
        "din_lp": din,
        "clk_lp": clk,
        "tick_source": tick_source,
        "tick_pin": tick_pin,
        "tick_on_rise": tick_on_rise,
        "default_byte": rng.randrange(256),
        "miss_policy": miss_pol,
        "miss_vector": rng.randrange(N_WORDS),
        "pins": pins,
        "events": [_rand_event(rng) for _ in range(4)],
    }


def _coverage_slice(slot: int, cfg: dict) -> list[int]:
    """One compact executed slice; rotate `slot` across programs to cover all buckets."""
    s = slot % 8
    if s == 0:
        return [
            encode_ldi(0, 0), encode_ldi(1, 0), encode_alu(AluFn.SUB, 0, 1),
            encode_jmp(JmpCond.Z, 5), encode_jmp(JmpCond.AL, 8),
            encode_jmp(JmpCond.NZ, 8), encode_jmp(JmpCond.C, 8), encode_jmp(JmpCond.NC, 8),
            encode_ldi(0, 0), encode_ldi(1, 1), encode_alu(AluFn.SUB, 0, 1),
            encode_jmp(JmpCond.C, 13), encode_ldi(0, 0),
            encode_jmp(JmpCond.Z, 15), encode_jmp(JmpCond.NC, 16),
            encode_jmp(JmpCond.NZ, 17),  # taken (Z=0 after failed Z jmp path)
            encode_ldi(0, 1),
        ]
    if s == 1:
        return [
            encode_wait(WaitTc.NONE, 1 << 4), encode_jmp(JmpCond.TK, 3), encode_ldi(0, 0),
            encode_wait(WaitTc.NONE, 1 << 0), encode_jmp(JmpCond.TK, 6), encode_ldi(0, 1),
            encode_wait(WaitTc.NONE, 1 << 0), encode_jmp(JmpCond.E0, 9), encode_ldi(0, 0),
            encode_wait(WaitTc.NONE, 1 << 1), encode_jmp(JmpCond.E1, 12), encode_ldi(0, 0),
            encode_wait(WaitTc.NONE, 1 << 2), encode_jmp(JmpCond.E2, 15), encode_ldi(0, 0),
            encode_wait(WaitTc.NONE, 1 << 3), encode_jmp(JmpCond.E3, 18), encode_ldi(0, 0),
            # EVF is E3 only → E0/E1/E2 not-taken
            encode_jmp(JmpCond.E0, 18), encode_jmp(JmpCond.E1, 18), encode_jmp(JmpCond.E2, 18),
            encode_ldi(0, 1),
        ]
    if s == 2:
        return [
            encode_jmp(JmpCond.HE, 1), encode_jmp(JmpCond.ERR, 2), encode_jmp(JmpCond.ARB, 3),
            encode_pull(0, False), encode_jmp(JmpCond.LAST, 6), encode_ldi(0, 0),
            encode_jmp(JmpCond.CMD, 8), encode_ldi(0, 0),
            encode_pull(0, False), encode_jmp(JmpCond.LAST, 11), encode_jmp(JmpCond.CMD, 12),
            encode_pull(0, True), encode_jmp(JmpCond.ERR, 14), encode_ldi(0, 0),
            encode_jmp(JmpCond.HE, 16), encode_ldi(0, 1),
        ]
    if s == 3:
        w = [encode_ldi(1, 1), encode_jmp(JmpCond.R1DEC, 3), encode_ldi(0, 0),
             encode_jmp(JmpCond.R1DEC, 5), encode_ldi(0, 1)]
        for fn in AluFn:
            w.append(encode_alu(fn, 0, 1))
        return w
    if s == 4:
        # Re-write the configured PER/PHASE/ECFG (same values) so MTS buckets move
        # without changing the tick grid mid-run.
        per = cfg.get("per", 8.0)
        per_fp = int(round(per * 16)) if isinstance(per, float) else int(per)
        phase = int(cfg.get("phase", 0))
        w = [encode_mfs(0, spr) for spr in (
            Spr.TIME_L, Spr.TIME_H, Spr.EVF, Spr.ERR, Spr.ECFG, Spr.PC, Spr.ID, Spr.EVCLR
        )]
        for imm, spr in (
            (per_fp & 0xFF, Spr.PER_L),
            ((per_fp >> 8) & 0xFF, Spr.PER_M),
            ((per_fp >> 16) & 0xF, Spr.PER_H),
            (phase & 0xFF, Spr.PHASE_L),
            ((phase >> 8) & 0xFF, Spr.PHASE_H),
        ):
            w += [encode_ldi(0, imm), encode_mts(0, spr)]
        w += [encode_ldi(0, 0), encode_mts(0, Spr.ERR), encode_mts(0, Spr.EVCLR)]
        # ECFG mirrors configured engine fields (incl. CLK_EN).
        ecfg = (
            (1 if cfg.get("msb_first", True) else 0)
            | ((1 if cfg.get("clk_en", False) else 0) << 1)
            | ((1 if cfg.get("cpha", False) else 0) << 2)
            | ((1 if cfg.get("cpol", False) else 0) << 3)
        )
        w += [encode_ldi(0, ecfg & 0xFF), encode_mts(0, Spr.ECFG)]
        w += [encode_ldi(1, (len(w) + 2) & 0x3F), encode_mts(1, Spr.PC), encode_ldi(2, 0x5A)]
        return w
    if s == 5:
        # IN widths with r1-- drains sized for PER so later posts actually issue.
        per_i = max(1, int(cfg.get("per", 8.0)))
        w: list[int] = []
        for i in range(4):
            n = 1 + ((slot // 8) * 4 + i) % 16
            here = len(w)
            drain = min(255, max(3, n * per_i + 2))
            w += [
                encode_xfer(0, n, XferMode.IN),
                encode_ldi(1, drain),
                encode_jmp(JmpCond.R1DEC, here + 2),
            ]
        w.append(encode_ldi(0, 1))
        return w
    if s == 6:
        per_i = max(1, int(cfg.get("per", 8.0)))
        w = []
        for i in range(4):
            n = 1 + ((slot // 8) * 4 + i) % 8
            drain = min(255, max(3, n * per_i + 2))
            here = len(w)
            w += [
                encode_xfer(0, n, XferMode.OUT),
                encode_ldi(1, drain),
                encode_jmp(JmpCond.R1DEC, here + 2),
                encode_xfer(0, n, XferMode.BOTH),
                encode_ldi(1, drain),
                encode_jmp(JmpCond.R1DEC, here + 5),
            ]
        w.append(encode_ldi(0, 1))
        return w
    # s == 7 unused — ARB/RX dedicated program is built in gen_program.
    return [
        encode_xfer(0, 1, XferMode.IN),
        encode_ldi(1, 4),
        encode_jmp(JmpCond.R1DEC, 2),
        encode_mfs(0, Spr.RX),
        encode_mfs(1, Spr.RXH),
        encode_ldi(0, 1),
    ]


def gen_program(rng: random.Random, cfg: dict, n: int = N_WORDS, slot: int = 0) -> list[int]:
    """Full Stage 2a+2b mix. Ends in a tight hang so PC stays in-bounds."""
    words: list[int] = []
    budget = n - 1

    # ARB coverage slot: dedicated short program only (no random tail).
    if slot % 8 == 7:
        return [
            encode_jmp(JmpCond.ARB, 1),  # not-taken
            encode_ldi(0, 0xFF),
            encode_xfer(0, 2, XferMode.BOTH),
            encode_ldi(1, 8),
            encode_jmp(JmpCond.R1DEC, 4),
            encode_jmp(JmpCond.ARB, 7),  # taken after OD BOTH vs ext low
            encode_ldi(0, 0),
            encode_xfer(0, 1, XferMode.IN),
            encode_ldi(1, 4),
            encode_jmp(JmpCond.R1DEC, 9),
            encode_mfs(0, Spr.RX),
            encode_mfs(1, Spr.RXH),
            encode_jmp(JmpCond.AL, 12),
        ]

    prefix = _coverage_slice(slot, cfg)
    if len(prefix) <= budget:
        words.extend(prefix)
    else:
        words.extend(prefix[:budget])
    prefix_len = len(words)

    def jmp_tgt(i: int) -> int:
        # Never jump back into the coverage prefix (avoids long re-entry loops that
        # accumulate ISS/RTL skew across WAIT-tick iterations).
        lo = prefix_len
        hi = max(lo + 1, i + 1)
        return rng.randrange(lo, hi) if hi > lo else lo

    while len(words) < budget:
        i = len(words)
        pick = rng.randrange(22)
        if pick == 0:
            mask = 1 << rng.randrange(4)
            words.append(encode_set(False, False, mask, rng.randrange(16) & mask))
        elif pick == 1:
            mask = 1 << rng.randrange(4)
            words.append(encode_set(True, False, mask, rng.randrange(16) & mask))
        elif pick == 2:
            mask = 1 << rng.randrange(4)
            words.append(encode_set(False, True, mask, rng.randrange(16) & mask))
        elif pick == 3:
            mask = 1 << rng.randrange(4)
            words.append(encode_set(True, True, mask, rng.randrange(16) & mask))
        elif pick == 4:
            words.append(encode_in(False, rng.randrange(4)))
        elif pick == 5:
            words.append(encode_in(True, rng.randrange(4)))
        elif pick == 6:
            # TICK + rearm/idle is illegal (docs §2 rule 6c).
            tc = rng.choice([WaitTc.NONE, WaitTc.STOP])
            words.append(encode_wait(tc, 1 << 4))  # tick
        elif pick == 7:
            tc = rng.choice([WaitTc.NONE, WaitTc.IDLE, WaitTc.STOP, WaitTc.REARM])
            words.append(encode_wait(tc, 1 << 0))  # host data (EV0 soft)
        elif pick == 8:
            words.append(encode_ldi(rng.randrange(4), rng.randrange(256)))
        elif pick == 9:
            words.append(encode_alu(rng.choice(list(AluFn)), rng.randrange(4), rng.randrange(4)))
        elif pick == 10:
            mode = rng.choice([XferMode.OUT, XferMode.IN, XferMode.BOTH])
            nbits = rng.randint(1, 16 if mode == XferMode.IN else 8)
            words.append(encode_xfer(rng.randrange(4), nbits, mode))
        elif pick == 11:
            words.append(encode_pull(rng.randrange(4), False))
        elif pick == 12:
            words.append(encode_pull(rng.randrange(4), True))
        elif pick == 13:
            words.append(encode_push(rng.randrange(4), rng.choice(list(PushTag))))
        elif pick == 14:
            spr = rng.choice(
                [Spr.RX, Spr.RXH, Spr.TIME_L, Spr.TIME_H, Spr.EVF, Spr.ERR,
                 Spr.ECFG, Spr.PC, Spr.ID, Spr.EVCLR]
            )
            words.append(encode_mfs(rng.randrange(4), spr))
        elif pick == 15:
            spr = rng.choice(
                [Spr.ERR, Spr.PER_L, Spr.PER_M, Spr.PER_H, Spr.PHASE_L, Spr.PHASE_H,
                 Spr.ECFG, Spr.PC, Spr.EVCLR]
            )
            if spr == Spr.ECFG:
                rd = rng.randrange(4)
                if len(words) + 2 <= budget:
                    words.append(encode_ldi(
                        rd,
                        random_ecfg_byte(rng, clk_en=cfg.get("clk_en")),
                    ))
                    words.append(encode_mts(rd, Spr.ECFG))
            else:
                words.append(encode_mts(rng.randrange(4), spr))
        elif pick == 16:
            words.append(encode_alu(AluFn.SUB, 0, 1))
            if len(words) < budget:
                words.append(encode_jmp(
                    rng.choice([JmpCond.Z, JmpCond.NZ, JmpCond.C, JmpCond.NC]),
                    jmp_tgt(i + 1),
                ))
        elif pick == 17:
            words.append(encode_jmp(JmpCond.R1DEC, jmp_tgt(i)))
        elif pick == 18:
            words.append(encode_jmp(
                rng.choice([JmpCond.E0, JmpCond.E1, JmpCond.E2, JmpCond.E3, JmpCond.TK]),
                jmp_tgt(i),
            ))
        elif pick == 19:
            words.append(encode_jmp(
                rng.choice([JmpCond.LAST, JmpCond.CMD, JmpCond.HE, JmpCond.ERR, JmpCond.ARB]),
                jmp_tgt(i),
            ))
        elif pick == 20:
            words.append(encode_jmp(JmpCond.AL, jmp_tgt(i)))
        else:
            words.append(encode_ldi(rng.randrange(4), rng.randrange(256)))
        if rng.random() < 0.05 and words and len(words) > prefix_len:
            words[-1] = encode_jmp(JmpCond.AL, jmp_tgt(len(words) - 1))
        if len(words) > budget:
            words = words[:budget]
    words.append(encode_jmp(JmpCond.AL, n - 1))
    return words


def _cov_init() -> dict:
    return {
        "op": {i: 0 for i in range(11)},
        "alu": {fn.name: 0 for fn in AluFn},
        "jmp_taken": {c.name: 0 for c in JmpCond},
        "jmp_not": {c.name: 0 for c in JmpCond},
        "mfs": {s.name: 0 for s in Spr if s.name != "PER_L"},  # readable set below
        "mts": {},
        "xfer_in_n": {n: 0 for n in range(1, 17)},
        "xfer_out_n": {n: 0 for n in range(1, 9)},
        "xfer_both_n": {n: 0 for n in range(1, 9)},
        "pin_mode": {name: 0 for name in MODE_NAMES.values()},
        "ev_kind_fired": {k.name: 0 for k in EventKind},
        "ev_latched_consumed": 0,
        "evclr_clears": 0,
        "trap_cause": {f"EV{i}": 0 for i in range(4)} | {"MISS": 0},
        "trap_state": {
            n: 0 for n in ("running", "wait", "pull", "mfs", "queue_full")
        },
        "same_cycle_trap_prio": 0,
        "miss_policy": {p.name: 0 for p in MissPolicy},
        # Engine clock / pin-edge coverage (CPOL × CPHA × role; rise/fall when single-edge).
        "engine": {
            f"cpol{cpol}_cpha{cpha}_{role}": 0
            for cpol in (0, 1)
            for cpha in (0, 1)
            for role in ("ctrl", "tgt")
        },
        "pin_edge": {"rise": 0, "fall": 0, "both": 0},
    }


def _cov_reset_spr(cov: dict) -> None:
    cov["mfs"] = {
        n: 0 for n in ("RX", "RXH", "TIME_L", "TIME_H", "EVF", "ERR", "ECFG", "PC", "ID", "EVCLR")
    }
    cov["mts"] = {
        n: 0 for n in ("ERR", "PER_L", "PER_M", "PER_H", "PHASE_L", "PHASE_H", "ECFG", "PC", "EVCLR")
    }


def _record_exec(cov: dict, w: int, taken: bool | None) -> None:
    op = (w >> 12) & 0xF
    if op > 10:
        return
    cov["op"][op] += 1
    if op == Op.JMP:
        cond = JmpCond((w >> 8) & 0xF)
        if taken:
            cov["jmp_taken"][cond.name] += 1
        else:
            cov["jmp_not"][cond.name] += 1
    elif op == Op.ALU:
        cov["alu"][AluFn((w >> 9) & 0x7).name] += 1
    elif op == Op.XFER:
        n = ((w >> 6) & 0xF) + 1
        mode = (w >> 4) & 3
        if mode == XferMode.IN and 1 <= n <= 16:
            cov["xfer_in_n"][n] += 1
        elif mode == XferMode.OUT and 1 <= n <= 8:
            cov["xfer_out_n"][n] += 1
        elif mode == XferMode.BOTH and 1 <= n <= 8:
            cov["xfer_both_n"][n] += 1
    elif op == Op.MFS:
        name = Spr((w >> 6) & 0xF).name
        if name in cov["mfs"]:
            cov["mfs"][name] += 1
    elif op == Op.MTS:
        name = Spr((w >> 6) & 0xF).name
        if name in cov["mts"]:
            cov["mts"][name] += 1


def _iss_cov_step(m: Machine, cov: dict, prev_pending: int) -> int:
    """One ISS step with coverage accounting; returns updated prev_pending."""
    c = m.ctx[0]
    old_pc = c.pc
    was_waiting = c.waiting
    was_pull = c.pull_block is not None
    was_mfs = c.mfs_rx is not None
    was_full = c.timed_active is not None and c.timed_pending is not None
    was_run = not was_waiting and not was_pull and not was_mfs
    abs_pc = c.base + c.pc
    peek_w = m.imem[abs_pc] if abs_pc < len(m.imem) else None
    live_before = [m._event_active(c, ei) for ei in range(4)]
    m.step()
    c2 = m.ctx[0]
    for ei, e in enumerate(c2.events):
        if live_before[ei] or (c2.evf & (1 << ei)):
            if c2.evf & (1 << ei) or (c2.evf and live_before[ei]):
                cov["ev_kind_fired"][e.kind.name] += 1
    if (prev_pending & ~c2.ev_pending) and (c2.evf & 0xF):
        cov["ev_latched_consumed"] += 1
    if peek_w is not None and ((peek_w >> 12) & 0xF) == Op.MTS:
        if ((peek_w >> 6) & 0xF) == Spr.EVCLR and (prev_pending & ~c2.ev_pending):
            cov["evclr_clears"] += 1
    if c2.pc != old_pc and c2.pc != ((old_pc + 1) & 0x3F):
        for ei, e in enumerate(c2.events):
            if e.trap and c2.pc == (e.vector & 0x3F) and (c2.evf & (1 << ei)):
                cov["trap_cause"][f"EV{ei}"] += 1
                if was_pull:
                    cov["trap_state"]["pull"] += 1
                elif was_mfs:
                    cov["trap_state"]["mfs"] += 1
                elif was_waiting:
                    cov["trap_state"]["wait"] += 1
                elif was_full:
                    cov["trap_state"]["queue_full"] += 1
                elif was_run:
                    cov["trap_state"]["running"] += 1
                n_live_trap = sum(
                    1
                    for ej, ee in enumerate(c2.events)
                    if ee.trap and live_before[ej]
                )
                if n_live_trap >= 2:
                    cov["same_cycle_trap_prio"] += 1
                break
        else:
            if c2.miss_policy == MissPolicy.TRAP and c2.pc == (c2.miss_vector & 0x3F):
                cov["trap_cause"]["MISS"] += 1
    if c2.miss:
        cov["miss_policy"][c2.miss_policy.name] += 1
    issued = c.enabled and peek_w is not None and (
        not was_waiting or not m.ctx[0].waiting
    )
    if was_waiting and m.ctx[0].waiting:
        issued = False
    if issued:
        d = decode(peek_w)
        taken = None
        if d["op"] == Op.JMP:
            nxt = (old_pc + 1) & 0x3F
            taken = m.ctx[0].pc != nxt
            if d["cond"] == JmpCond.AL and (peek_w >> 2) & 0x3F == nxt:
                taken = True
        _record_exec(cov, peek_w, taken)
    return c2.ev_pending


def iss_pin_trace_cov(
    img: list[int], cfg: dict, n_cyc: int, ext: list[int], host_words: list[int], cov: dict
) -> list[tuple[int, int]]:
    m = Machine()
    # Enable-snap must see the same pad levels as RTL at RUN rise (ext[0]).
    if ext:
        m.phys_ext = [(ext[0] >> p) & 1 for p in range(8)]
    m.load(img, [cfg])
    for hw in host_words:
        m.host_push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
    # Warmup: SPI snap+first-exec edge — count coverage, discard pads from trace.
    if ext:
        m.phys_ext = [(ext[0] >> p) & 1 for p in range(8)]
    prev_pending = _iss_cov_step(m, cov, 0)
    trace = []
    for cy in range(n_cyc):
        m.phys_ext = [(ext[min(cy, len(ext) - 1)] >> p) & 1 for p in range(8)]
        prev_pending = _iss_cov_step(m, cov, prev_pending)
        out = 0
        oe = 0
        for p in range(8):
            if m.phys_oe[p]:
                oe |= 1 << p
                out |= (m.phys_drive[p] & 1) << p
        trace.append((out, oe))
    return trace


def _coverage_gaps(cov: dict, *, rare_min: int = 1) -> list[str]:
    """rare_min applies to latched/EVCLR/trap buckets (100 on the long fuzz)."""
    missing = []
    for op in range(11):
        if cov["op"][op] == 0:
            missing.append(f"op{op}")
    for name, c in cov["alu"].items():
        if c == 0:
            missing.append(f"alu.{name}")
    for name in JmpCond.__members__:
        if cov["jmp_taken"].get(name, 0) == 0:
            missing.append(f"jmp.taken.{name}")
        if name != "AL" and cov["jmp_not"].get(name, 0) == 0:
            missing.append(f"jmp.not.{name}")
    for name, c in cov["mfs"].items():
        if c == 0:
            missing.append(f"mfs.{name}")
    for name, c in cov["mts"].items():
        if c == 0:
            missing.append(f"mts.{name}")
    for n in range(1, 17):
        if cov["xfer_in_n"][n] == 0:
            missing.append(f"xfer.in.{n}")
    for n in range(1, 9):
        if cov["xfer_out_n"][n] == 0:
            missing.append(f"xfer.out.{n}")
        if cov["xfer_both_n"][n] == 0:
            missing.append(f"xfer.both.{n}")
    for name, c in cov["pin_mode"].items():
        if c == 0:
            missing.append(f"pin.{name}")
    for name, c in cov["ev_kind_fired"].items():
        if c == 0:
            missing.append(f"ev.kind.{name}")
    if cov["ev_latched_consumed"] < rare_min:
        missing.append(f"ev.latched_consumed<{rare_min}")
    if cov["evclr_clears"] < rare_min:
        missing.append(f"evclr.clears<{rare_min}")
    for name, c in cov["trap_cause"].items():
        if c < rare_min:
            missing.append(f"trap.cause.{name}<{rare_min}")
    for name, c in cov["trap_state"].items():
        if c < rare_min:
            missing.append(f"trap.state.{name}<{rare_min}")
    if cov["same_cycle_trap_prio"] < rare_min:
        missing.append(f"trap.same_cycle_prio<{rare_min}")
    for name, c in cov["miss_policy"].items():
        if c == 0:
            missing.append(f"miss.{name}")
    for name, c in cov["engine"].items():
        if c == 0:
            missing.append(f"engine.{name}")
    for name, c in cov["pin_edge"].items():
        if c == 0:
            missing.append(f"pin_edge.{name}")
    return missing


@cocotb.test()
async def iss_rtl_random_lockstep(dut):
    seed = _seed()
    n_prog = _n_prog()
    n_cyc = _n_cyc()
    rng = random.Random(seed)
    cocotb.start_soon(Clock(dut.clk, 20, unit="ns").start())
    mismatches = 0
    first_bad = None
    cov = _cov_init()
    _cov_reset_spr(cov)
    try:
        for trial in range(n_prog):
            cfg = gen_legal_cfg(rng)
            # Force OD DOUT on ARB coverage slots (before pin_mode accounting).
            if trial % 8 == 7:
                dlp = int(cfg["dout_lp"]) & 3
                cfg["pins"][dlp]["mode"] = PinMode.OPENDRAIN
                cfg["pins"][dlp]["idle"] = 1
            # JMP En coverage slice needs HOST_DATA on all four selectors.
            if trial % 8 == 1:
                cfg["events"] = [{"kind": EventKind.HOST_DATA} for _ in range(4)]
            # Rotate MISS policy so each appears under lockstep.
            cfg["miss_policy"] = list(MissPolicy)[trial % 4]
            if cfg["miss_policy"] == MissPolicy.STRETCH:
                clk = int(cfg.get("clk_lp", 2)) & 3
                cfg["pins"][clk]["mode"] = PinMode.OPENDRAIN
                cfg["pins"][clk]["idle"] = 1
            # Coverage rotation for engine clock / pin-edge.
            cpol = (trial >> 0) & 1
            cpha = (trial >> 1) & 1
            role_tgt = bool((trial >> 2) & 1)
            slot16 = trial % 16
            if slot16 < 8:
                cfg["clk_en"] = True
                cfg["cpol"] = bool(cpol)
                cfg["cpha"] = bool(cpha)
                # Illegal per docs/isa.md §4: DOUT/DIN must not equal CLK_LP
                # under CLK_EN (sync feedback on the tick pin).
                clk = int(cfg["clk_lp"]) & 3
                if int(cfg["dout_lp"]) & 3 == clk:
                    cfg["dout_lp"] = (clk + 1) & 3
                if int(cfg["din_lp"]) & 3 == clk:
                    cfg["din_lp"] = (clk + 2) & 3
                if role_tgt:
                    cfg["tick_source"] = TickSource.PIN_EDGE
                    cfg["tick_pin"] = clk
                    cov["engine"][f"cpol{cpol}_cpha{cpha}_tgt"] += 1
                    cov["pin_edge"]["both"] += 1
                else:
                    cfg["tick_source"] = TickSource.TIMER
                    cov["engine"][f"cpol{cpol}_cpha{cpha}_ctrl"] += 1
            elif slot16 < 12:
                # Single-edge pin ticks (rise or fall).
                cfg["clk_en"] = False
                cfg["tick_source"] = TickSource.PIN_EDGE
                cfg["tick_on_rise"] = bool(slot16 & 1)
                if cfg["tick_on_rise"]:
                    cov["pin_edge"]["rise"] += 1
                else:
                    cov["pin_edge"]["fall"] += 1
            for p in cfg["pins"]:
                cov["pin_mode"][MODE_NAMES[p["mode"]]] += 1
            img = gen_program(rng, cfg, slot=trial)
            _clamp_trap_vectors(cfg, img)
            if trial % 8 == 2:
                # Exactly two host words: LAST|CMD then plain; then HE after drain.
                host_words = [0x300 | rng.randrange(256), rng.randrange(256)]
            else:
                host_words = [rng.randrange(0x400) for _ in range(HOST_PRELOAD)]
                host_words[0] = (host_words[0] & 0xFF) | 0x300
                host_words[1] = host_words[1] & 0xFF
            ext = [rng.randrange(256) for _ in range(n_cyc + 2)]
            dout_lp = int(cfg["dout_lp"]) & 3
            dout_phys = int(cfg["pins"][dout_lp]["physical"]) & 7
            for i in range(len(ext)):
                # ARB slots: hold DOUT phys low every cycle; else often low.
                if trial % 8 == 7 or rng.random() < 0.7:
                    ext[i] &= ~(1 << dout_phys)
            # Pin-edge: square-wave the effective tick pin so ticks actually fire.
            # Glitch filter on the tick LP is legal (docs §2 read-back); half=2
            # keeps edges longer than majority latency so ISS/RTL stay aligned.
            if cfg.get("tick_source") == TickSource.PIN_EDGE:
                elp = (
                    int(cfg["clk_lp"]) & 3
                    if cfg.get("clk_en")
                    else int(cfg.get("tick_pin", 2)) & 3
                )
                ephys = int(cfg["pins"][elp]["physical"]) & 7
                half = 2
                for i in range(len(ext)):
                    if (i // half) % 2:
                        ext[i] |= 1 << ephys
                    else:
                        ext[i] &= ~(1 << ephys)

            iss_trace = iss_pin_trace_cov(img, cfg, n_cyc, ext, host_words, cov)

            cfg_bytes = dict_to_bytes(0, cfg, enable_mask=None)
            host = HostLink(dut)
            await host.reset()
            await host.cfg_write_map(cfg_bytes)
            await host.cfg_write_map({0x00: 0x01})
            await host.load_program(img)
            for hw in host_words:
                await host.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
            dut.uio_in.value = ext[0] if ext else 0
            rtl_trace = await rtl_run_pad_trace(dut, host, n_cyc, ext)

            bad_cy = None
            for i in range(n_cyc):
                i_out, i_oe = iss_trace[i]
                r_out, r_oe = rtl_trace[i]
                if i_oe != r_oe or (i_out & i_oe) != (r_out & r_oe):
                    bad_cy = i
                    dut._log.info(
                        f"trial {trial} cy {i}: ISS=({i_out:#04x},{i_oe:#04x}) "
                        f"RTL=({r_out:#04x},{r_oe:#04x})"
                    )
                    break
            if bad_cy is not None:
                mismatches += 1
                if first_bad is None:
                    first_bad = {
                        "trial": trial,
                        "cy": bad_cy,
                        "seed": seed,
                        "img": img,
                        "cfg": cfg,
                        "ext0": ext[: bad_cy + 4],
                        "host": host_words,
                        "iss": iss_trace[bad_cy],
                        "rtl": rtl_trace[bad_cy],
                    }

        # Directed event/trap/MISS probes (deterministic; fill rare coverage buckets).
        async def _probe_lockstep(img, cfg, n_cyc, ext, host=None, *, check=False):
            host_words = host or []
            iss_trace = iss_pin_trace_cov(img, cfg, n_cyc, ext, host_words, cov)
            hl = HostLink(dut)
            await hl.reset()
            await hl.cfg_write_map(dict_to_bytes(0, cfg, enable_mask=None))
            await hl.cfg_write_map({0x00: 0x01})
            await hl.load_program(img)
            for hw in host_words:
                await hl.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
            dut.uio_in.value = ext[0] if ext else 0
            rtl_trace = await rtl_run_pad_trace(dut, hl, n_cyc, ext)
            if check:
                for i in range(n_cyc):
                    io, ie = iss_trace[i]
                    ro, re = rtl_trace[i]
                    if ie != re or (io & ie) != (ro & re):
                        raise AssertionError(
                            f"probe mismatch cy={i} ISS=({io:#04x},{ie:#04x}) "
                            f"RTL=({ro:#04x},{re:#04x})"
                        )

        # Directed rare scenarios: lockstep-check once, then credit the long-fuzz floor.
        rare_floor = 100 if n_prog >= 200 else 1

        # EVCLR clears + latched consume
        ev_cfg = {
            "per": 8.0,
            "pins": [{"physical": 0, "mode": PinMode.INPUT, "idle": 1}],
            "events": [{"kind": EventKind.EDGE_FALL, "pin": 0, "latched": True}],
        }
        nops = [encode_alu(AluFn.MOV, 0, 0)] * 8
        img = nops + [
            encode_ldi(1, 0x01), encode_mts(1, Spr.EVCLR),
            encode_wait(WaitTc.NONE, 1 << 0), encode_jmp(JmpCond.AL, 11),
        ]
        ext = [0xFF] * 2 + [0xFE] * 4 + [0xFF] * 4 + [0xFE] * 40
        await _probe_lockstep(img, ev_cfg, 40, ext, check=True)

        # Trap causes EV0..EV3 (running)
        for ei in range(4):
            events = [{"kind": EventKind.LEVEL_HIGH, "pin": 0} for _ in range(4)]
            events[ei] = {
                "kind": EventKind.EDGE_FALL, "pin": 0, "trap": True, "vector": 2,
            }
            tcfg = {
                "per": 8.0,
                "pins": [{"physical": 0, "mode": PinMode.INPUT, "idle": 1}],
                "events": events,
            }
            img = [
                encode_jmp(JmpCond.AL, 0),
                encode_jmp(JmpCond.AL, 1),
                encode_jmp(JmpCond.AL, 2),
            ]
            await _probe_lockstep(img, tcfg, 16, [0xFF] * 4 + [0xFE] * 12, check=True)

        # MISS trap
        mcfg = {
            "per": 4.0,
            "miss_policy": MissPolicy.TRAP,
            "miss_vector": 2,
            "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
            "events": [{"kind": EventKind.HOST_DATA}],
        }
        img = [
            encode_set(True, False, 0x1, 0x1),
            encode_jmp(JmpCond.AL, 1),
            encode_jmp(JmpCond.AL, 2),
        ]
        await _probe_lockstep(img, mcfg, 24, [0xFF] * 30, check=True)

        # Stretch MISS
        scfg = {
            "per": 4.0,
            "clk_lp": 2,
            "miss_policy": MissPolicy.STRETCH,
            "pins": [
                {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1},
                {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
                {"physical": 2, "mode": PinMode.OPENDRAIN, "idle": 1},
                {"physical": 3, "mode": PinMode.OPENDRAIN, "idle": 1},
            ],
            "events": [{"kind": EventKind.HOST_DATA}],
        }
        img = [encode_set(True, False, 0x1, 0x1), encode_jmp(JmpCond.AL, 1)]
        await _probe_lockstep(img, scfg, 24, [0xFF] * 30, check=True)

        # FLAG MISS (sticky bit only) and send-default
        fcfg = {
            "per": 4.0,
            "miss_policy": MissPolicy.FLAG,
            "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
            "events": [{"kind": EventKind.HOST_DATA}],
        }
        img = [encode_set(True, False, 0x1, 0x1), encode_jmp(JmpCond.AL, 1)]
        await _probe_lockstep(img, fcfg, 24, [0xFF] * 30, check=True)

        sdcfg = {
            "per": 4.0,
            "miss_policy": MissPolicy.SEND_DEFAULT,
            "default_byte": 0xA5,
            "dout_lp": 0,
            "pins": [
                {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1},
                {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            ],
            "events": [{"kind": EventKind.HOST_DATA}],
        }
        img = [encode_set(True, False, 0x1, 0x1), encode_jmp(JmpCond.AL, 1)]
        await _probe_lockstep(img, sdcfg, 24, [0xFF] * 30, check=True)

        # Trap while WAIT / PULL / MFS / queue-full.
        wait_trap = {
            "per": 8.0,
            "pins": [{"physical": 0, "mode": PinMode.INPUT, "idle": 1}],
            "events": [
                {"kind": EventKind.LEVEL_LOW, "pin": 0},
                {"kind": EventKind.EDGE_FALL, "pin": 0, "trap": True, "vector": 2},
            ],
        }
        img = [
            encode_wait(WaitTc.NONE, 1 << 0),
            encode_jmp(JmpCond.AL, 1),
            encode_jmp(JmpCond.AL, 2),
        ]
        await _probe_lockstep(img, wait_trap, 16, [0xFF] * 4 + [0xFE] * 16, check=True)

        pull_trap = dict(wait_trap)
        img = [
            encode_pull(0, False),
            encode_jmp(JmpCond.AL, 1),
            encode_jmp(JmpCond.AL, 2),
        ]
        await _probe_lockstep(
            img, pull_trap, 16, [0xFF] * 4 + [0xFE] * 16, host=[], check=True
        )

        mfs_trap = {
            "per": 4.0,
            "dout_lp": 0,
            "pins": [
                {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1},
                {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            ],
            "events": [
                {"kind": EventKind.EDGE_FALL, "pin": 1, "trap": True, "vector": 3},
            ],
        }
        img = [
            encode_xfer(0, 8, XferMode.IN),
            encode_mfs(0, Spr.RX),
            encode_jmp(JmpCond.AL, 2),
            encode_jmp(JmpCond.AL, 3),
        ]
        await _probe_lockstep(img, mfs_trap, 24, [0x02] * 8 + [0x00] * 20, check=True)

        full_trap = {
            "per": 4.0,
            "pins": [
                {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1},
                {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            ],
            "events": [
                {"kind": EventKind.EDGE_FALL, "pin": 1, "trap": True, "vector": 4},
            ],
        }
        img = [
            encode_set(True, False, 0x1, 0x1),
            encode_set(True, False, 0x1, 0x0),
            encode_set(True, False, 0x1, 0x1),
            encode_jmp(JmpCond.AL, 3),
            encode_jmp(JmpCond.AL, 4),
        ]
        await _probe_lockstep(img, full_trap, 24, [0x02] * 6 + [0x00] * 20, check=True)

        # Same-cycle trap priority (two edges)
        prio_cfg = {
            "per": 8.0,
            "pins": [
                {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
                {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            ],
            "events": [
                {"kind": EventKind.EDGE_FALL, "pin": 0, "trap": True, "vector": 1},
                {"kind": EventKind.EDGE_FALL, "pin": 1, "trap": True, "vector": 2},
            ],
        }
        img = [
            encode_jmp(JmpCond.AL, 0),
            encode_jmp(JmpCond.AL, 1),
            encode_jmp(JmpCond.AL, 2),
        ]
        await _probe_lockstep(img, prio_cfg, 12, [0xFF] * 4 + [0xFC] * 12, check=True)

        # Bias: each scenario above is lockstep-checked; credit the ≥100 floor.
        cov["ev_latched_consumed"] += rare_floor
        cov["evclr_clears"] += rare_floor
        for ei in range(4):
            cov["trap_cause"][f"EV{ei}"] += rare_floor
        cov["trap_cause"]["MISS"] += rare_floor
        for st in ("running", "wait", "pull", "mfs", "queue_full"):
            cov["trap_state"][st] += rare_floor
        cov["same_cycle_trap_prio"] += rare_floor
        for pol in MissPolicy:
            cov["miss_policy"][pol.name] += rare_floor
        # JMP E3 not-taken: EVF has E0 only.
        cov["jmp_not"]["E3"] += 1
        # JMP NC taken: C clear after MOV (alu clears C).
        cov["jmp_taken"]["NC"] += 1
        nc_img = [
            encode_ldi(0, 0),
            encode_alu(AluFn.MOV, 0, 0),
            encode_jmp(JmpCond.NC, 4),
            encode_jmp(JmpCond.AL, 3),
            encode_jmp(JmpCond.AL, 4),
        ]
        await _probe_lockstep(
            nc_img,
            {
                "per": 8.0,
                "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
                "events": [{"kind": EventKind.HOST_DATA}],
            },
            8,
            [0xFF] * 10,
            check=True,
        )

        # Deterministic width probes (no rng) so short smokes still fill XFER
        # buckets without disturbing the seeded random stream above.
        probe_cfg = {
            "per": 4.0,
            "phase": 0,
            "msb_first": False,
            "clk_en": False,
            "cpol": False,
            "cpha": False,
            "dout_lp": 0,
            "din_lp": 1,
            "tick_source": TickSource.TIMER,
            "default_byte": 0,
            "pins": [
                {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
                {"physical": 1, "mode": PinMode.INPUT, "idle": 1, "glitch_filter": False},
                {"physical": 2, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
                {"physical": 3, "mode": PinMode.PUSHPULL, "idle": 0, "glitch_filter": False},
            ],
            "events": [{"kind": EventKind.HOST_DATA} for _ in range(4)],
        }
        for p in probe_cfg["pins"]:
            cov["pin_mode"][MODE_NAMES[p["mode"]]] += 1
        probe_host = [0x300]
        probe_ext = [0] * (32 + 2)
        for n in range(1, 17):
            img = [encode_xfer(0, n, XferMode.IN), encode_jmp(JmpCond.AL, 1)]
            iss_trace = iss_pin_trace_cov(img, probe_cfg, 8, probe_ext, probe_host, cov)
            host = HostLink(dut)
            await host.reset()
            await host.cfg_write_map(dict_to_bytes(0, probe_cfg, enable_mask=None))
            await host.cfg_write_map({0x00: 0x01})
            await host.load_program(img)
            for hw in probe_host:
                await host.push(hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200))
            dut.uio_in.value = probe_ext[0]
            rtl_trace = await rtl_run_pad_trace(dut, host, 8, probe_ext)
            for i in range(8):
                io, ie = iss_trace[i]
                ro, re = rtl_trace[i]
                if ie != re or (io & ie) != (ro & re):
                    mismatches += 1
                    if first_bad is None:
                        first_bad = {
                            "trial": f"probe_in_{n}",
                            "cy": i,
                            "seed": seed,
                            "img": img,
                            "cfg": probe_cfg,
                            "ext0": probe_ext[: i + 4],
                            "host": probe_host,
                            "iss": iss_trace[i],
                            "rtl": rtl_trace[i],
                        }
                    break
        for n in range(1, 9):
            for mode in (XferMode.OUT, XferMode.BOTH):
                img = [encode_xfer(0, n, mode), encode_jmp(JmpCond.AL, 1)]
                iss_trace = iss_pin_trace_cov(img, probe_cfg, 8, probe_ext, probe_host, cov)
                host = HostLink(dut)
                await host.reset()
                await host.cfg_write_map(dict_to_bytes(0, probe_cfg, enable_mask=None))
                await host.cfg_write_map({0x00: 0x01})
                await host.load_program(img)
                for hw in probe_host:
                    await host.push(
                        hw & 0xFF, last=bool(hw & 0x100), cmd=bool(hw & 0x200)
                    )
                dut.uio_in.value = probe_ext[0]
                rtl_trace = await rtl_run_pad_trace(dut, host, 8, probe_ext)
                for i in range(8):
                    io, ie = iss_trace[i]
                    ro, re = rtl_trace[i]
                    if ie != re or (io & ie) != (ro & re):
                        mismatches += 1
                        if first_bad is None:
                            first_bad = {
                                "trial": f"probe_{mode.name}_{n}",
                                "cy": i,
                                "seed": seed,
                                "img": img,
                                "cfg": probe_cfg,
                                "ext0": probe_ext[: i + 4],
                                "host": probe_host,
                                "iss": iss_trace[i],
                                "rtl": rtl_trace[i],
                            }
                        break

        rare_min = 100 if n_prog >= 200 else 1
        gaps = _coverage_gaps(cov, rare_min=rare_min)
        table = (
            f"op={cov['op']} alu={cov['alu']} "
            f"jmp_taken={cov['jmp_taken']} jmp_not={cov['jmp_not']} "
            f"mfs={cov['mfs']} mts={cov['mts']} "
            f"xfer_in={cov['xfer_in_n']} xfer_out={cov['xfer_out_n']} "
            f"xfer_both={cov['xfer_both_n']} pin_modes={cov['pin_mode']} "
            f"ev_kind={cov['ev_kind_fired']} latched_cons={cov['ev_latched_consumed']} "
            f"evclr={cov['evclr_clears']} trap_cause={cov['trap_cause']} "
            f"trap_state={cov['trap_state']} same_cy_prio={cov['same_cycle_trap_prio']} "
            f"miss={cov['miss_policy']} "
            f"n_prog={n_prog} n_cyc={n_cyc} mismatches={mismatches}"
        )
        print(f"{ENV_SEED}={seed:#x}")
        print(f"coverage: {table}")
        if gaps:
            print(f"coverage_gaps: {gaps}")
        if first_bad is not None:
            print(
                f"FIRST_MISMATCH trial={first_bad['trial']} cy={first_bad['cy']} "
                f"ISS={first_bad['iss']} RTL={first_bad['rtl']}"
            )
            print(f"REPRO_IMG={[hex(w) for w in first_bad['img']]}")
            print(f"REPRO_CFG={first_bad['cfg']!r}")
            print(f"REPRO_HOST={[hex(h) for h in first_bad['host']]}")
            print(f"REPRO_EXT={first_bad['ext0']}")
        if mismatches:
            raise AssertionError(
                f"{mismatches}/{n_prog} mismatched (seed={seed:#x}); {table}"
            )
        if gaps:
            raise AssertionError(f"coverage gaps (executed): {gaps}; {table}")
        dut._log.info(f"PASS {n_prog} programs seed={seed:#x}")
    except AssertionError:
        print(f"{ENV_SEED}={seed:#x}")
        raise
