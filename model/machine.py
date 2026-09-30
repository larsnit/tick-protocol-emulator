"""Cycle-accurate instruction-set simulator for the Tick ISA."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from .opcodes import (
    DEFAULT_BYTE,
    HOST_FIFO_DEPTH,
    ID_VALUE,
    IMEM_WORDS,
    N_CONTEXTS,
    N_EVENTS,
    N_LOGICAL_PINS,
    AluFn,
    JmpCond,
    MissPolicy,
    Op,
    PinMode,
    PushTag,
    Spr,
    TickSource,
    WaitTc,
    XferMode,
    decode,
)


class EventKind(IntEnum):
    LEVEL_LOW = 0
    LEVEL_HIGH = 1
    EDGE_RISE = 2
    EDGE_FALL = 3
    QUAL_FALL_WHILE_HIGH = 4
    QUAL_RISE_WHILE_HIGH = 5
    HOST_DATA = 6
    HOST_SPACE = 7


@dataclass
class LogicalPinCfg:
    physical: int = 0
    mode: PinMode = PinMode.INPUT
    idle: int = 1


@dataclass
class EventCfg:
    kind: EventKind = EventKind.LEVEL_HIGH
    pin: int = 0
    qual_pin: int = 1
    trap: bool = False
    vector: int = 0


@dataclass
class Job:
    mode: int
    n_bits: int
    data: int
    bits_done: int = 0
    result: int = 0
    msb_first: bool = True


@dataclass
class TimedOp:
    kind: str  # set | xfer | in
    mask: int = 0
    val: int = 0
    oe: bool = False
    job: Optional[Job] = None
    lp: int = 0


@dataclass
class Context:
    regs: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    pc: int = 0
    base: int = 0
    bound: int = IMEM_WORDS
    z: bool = False
    c: bool = False
    evf: int = 0
    last: bool = False
    cmd: bool = False
    miss: bool = False
    under: bool = False
    overrun: bool = False
    arb: bool = False
    per_fp: int = 16 << 4
    phase: int = 0
    time: int = 0
    time_latch: int = 0
    timer_running: bool = False
    accum: int = 0
    phase_left: int = 0
    tick_source: TickSource = TickSource.TIMER
    tick_pin: int = 2
    tick_on_rise: bool = True
    miss_policy: MissPolicy = MissPolicy.FLAG
    default_byte: int = DEFAULT_BYTE
    ecfg_msb_first: bool = True
    timed_active: Optional[TimedOp] = None
    timed_pending: Optional[TimedOp] = None
    result: int = 0
    result_valid: bool = False
    waiting: bool = False
    wait_mask: int = 0
    wait_tc: int = 0
    pull_block: Optional[int] = None
    mfs_rx: Optional[int] = None
    pins: list[LogicalPinCfg] = field(
        default_factory=lambda: [LogicalPinCfg(i) for i in range(N_LOGICAL_PINS)]
    )
    events: list[EventCfg] = field(default_factory=lambda: [EventCfg() for _ in range(N_EVENTS)])
    drive_val: int = 0
    drive_oe: int = 0
    stretching: bool = False


@dataclass
class HostWord:
    data: int
    last: bool = False
    cmd: bool = False
    tag: int = PushTag.DATA


class Machine:
    def __init__(self) -> None:
        self.imem = [0] * IMEM_WORDS
        self.ctx = [Context() for _ in range(N_CONTEXTS)]
        self.cycle = 0
        self.sched = 0
        self.host_to_core: list[HostWord] = []
        self.core_to_host: list[HostWord] = []
        self.phys_drive = [0] * 8
        self.phys_oe = [0] * 8
        self.phys_ext = [1] * 8
        self._sync0 = [1] * 8
        self._sync1 = [1] * 8
        self._sync_prev = [1] * 8
        self.double_drive = False
        self.trace: list[dict] = []
        self.enable_trace = False

    def load(self, image: list[int], configs: Optional[list[dict]] = None) -> None:
        self.imem = [0] * IMEM_WORDS
        for i, w in enumerate(image):
            self.imem[i] = w & 0xFFFF
        if configs:
            for i, cfg in enumerate(configs):
                self.configure(i, cfg)

    def configure(self, ci: int, cfg: dict) -> None:
        c = self.ctx[ci]
        if "base" in cfg:
            c.base = cfg["base"]
        if "bound" in cfg:
            c.bound = cfg["bound"]
        if "per" in cfg:
            per = cfg["per"]
            c.per_fp = int(round(per * 16)) if isinstance(per, float) else int(per)
        if "phase" in cfg:
            c.phase = int(cfg["phase"])
        if "tick_source" in cfg:
            c.tick_source = TickSource(cfg["tick_source"])
        if "tick_pin" in cfg:
            c.tick_pin = int(cfg["tick_pin"])
        if "tick_on_rise" in cfg:
            c.tick_on_rise = bool(cfg["tick_on_rise"])
        if "miss_policy" in cfg:
            c.miss_policy = MissPolicy(cfg["miss_policy"])
        if "default_byte" in cfg:
            c.default_byte = int(cfg["default_byte"]) & 0xFF
        if "msb_first" in cfg:
            c.ecfg_msb_first = bool(cfg["msb_first"])
        if "pins" in cfg:
            for i, p in enumerate(cfg["pins"]):
                c.pins[i] = LogicalPinCfg(
                    physical=p.get("physical", i),
                    mode=PinMode(p.get("mode", PinMode.INPUT)),
                    idle=p.get("idle", 1),
                )
                if c.pins[i].mode != PinMode.INPUT:
                    c.drive_val = (c.drive_val & ~(1 << i)) | ((c.pins[i].idle & 1) << i)
                    if c.pins[i].mode == PinMode.PUSHPULL:
                        c.drive_oe |= 1 << i
                    else:
                        if c.pins[i].idle:
                            c.drive_oe &= ~(1 << i)
                        else:
                            c.drive_oe |= 1 << i
                            c.drive_val &= ~(1 << i)
        if "events" in cfg:
            for i, e in enumerate(cfg["events"]):
                c.events[i] = EventCfg(
                    kind=EventKind(e["kind"]),
                    pin=e.get("pin", 0),
                    qual_pin=e.get("qual_pin", 1),
                    trap=e.get("trap", False),
                    vector=e.get("vector", 0),
                )
        c.pc = 0

    def host_push(self, data: int, last: bool = False, cmd: bool = False) -> None:
        if len(self.host_to_core) >= HOST_FIFO_DEPTH:
            raise RuntimeError("host→core FIFO full")
        self.host_to_core.append(HostWord(data & 0xFF, last, cmd))

    def host_pop(self) -> Optional[HostWord]:
        if not self.core_to_host:
            return None
        return self.core_to_host.pop(0)

    def _phys_level(self, p: int) -> int:
        if self.phys_oe[p]:
            return self.phys_drive[p] & 1
        return self.phys_ext[p] & 1

    def _apply_drives(self) -> None:
        drives: list[list[tuple[int, int]]] = [[] for _ in range(8)]
        for ci, c in enumerate(self.ctx):
            for li in range(N_LOGICAL_PINS):
                phys = c.pins[li].physical
                if not (0 <= phys <= 7):
                    continue
                mode = c.pins[li].mode
                bit = (c.drive_val >> li) & 1
                oe = (c.drive_oe >> li) & 1
                if mode == PinMode.INPUT:
                    continue
                if mode == PinMode.OPENDRAIN:
                    if bit == 0 and oe:
                        drives[phys].append((ci, 0))
                else:
                    if oe:
                        drives[phys].append((ci, bit))
        self.double_drive = False
        for p in range(8):
            if len(drives[p]) > 1:
                self.double_drive = True
                _, val = max(drives[p], key=lambda x: x[0])
                self.phys_oe[p] = 1
                self.phys_drive[p] = val
            elif len(drives[p]) == 1:
                _, val = drives[p][0]
                self.phys_oe[p] = 1
                self.phys_drive[p] = val
            else:
                self.phys_oe[p] = 0

    def _logical_in(self, c: Context, li: int) -> int:
        return self._sync1[c.pins[li].physical]

    def _event_active(self, c: Context, ei: int) -> bool:
        e = c.events[ei]
        if e.kind == EventKind.HOST_DATA:
            return len(self.host_to_core) > 0
        if e.kind == EventKind.HOST_SPACE:
            return len(self.core_to_host) < HOST_FIFO_DEPTH
        pin = self._logical_in(c, e.pin)
        prev = self._sync_prev[c.pins[e.pin].physical]
        if e.kind == EventKind.LEVEL_LOW:
            return pin == 0
        if e.kind == EventKind.LEVEL_HIGH:
            return pin == 1
        if e.kind == EventKind.EDGE_RISE:
            return prev == 0 and pin == 1
        if e.kind == EventKind.EDGE_FALL:
            return prev == 1 and pin == 0
        qual = self._logical_in(c, e.qual_pin)
        if e.kind == EventKind.QUAL_FALL_WHILE_HIGH:
            return qual == 1 and prev == 1 and pin == 0
        if e.kind == EventKind.QUAL_RISE_WHILE_HIGH:
            return qual == 1 and prev == 0 and pin == 1
        return False

    def _event_mask_now(self, c: Context) -> int:
        m = 0
        for ei in range(N_EVENTS):
            if self._event_active(c, ei):
                m |= 1 << ei
        return m

    def _emit_tick(self, c: Context) -> bool:
        if c.tick_source == TickSource.PIN_EDGE:
            pin = self._logical_in(c, c.tick_pin)
            prev = self._sync_prev[c.pins[c.tick_pin].physical]
            if c.tick_on_rise:
                return prev == 0 and pin == 1
            return prev == 1 and pin == 0
        if not c.timer_running:
            return False
        if c.phase_left > 0:
            c.phase_left -= 1
            return c.phase_left == 0
        c.accum += 1 << 4
        if c.accum >= c.per_fp:
            c.accum -= c.per_fp
            return True
        return False

    def _start_timer(self, c: Context) -> None:
        c.timer_running = True
        c.accum = 0
        c.time = 0
        c.phase_left = c.phase

    def _stop_timer(self, c: Context) -> None:
        c.timer_running = False
        c.accum = 0
        c.phase_left = 0

    def _post_timed(self, c: Context, op: TimedOp) -> bool:
        if c.timed_active is None:
            c.timed_active = op
            return True
        if c.timed_pending is None:
            c.timed_pending = op
            return True
        return False

    def _promote(self, c: Context) -> None:
        c.timed_active = c.timed_pending
        c.timed_pending = None

    def _on_tick(self, c: Context) -> None:
        if c.timed_active is None:
            if c.timer_running:
                c.miss = True
                self._apply_miss(c)
            return
        op = c.timed_active
        if op.kind == "set":
            self._do_set(c, op.mask, op.val, oe=op.oe)
            self._promote(c)
        elif op.kind == "in":
            c.c = bool(self._logical_in(c, op.lp))
            c.z = not c.c
            c.evf |= 1 << 4
            if c.waiting and c.mfs_rx is None and c.pull_block is None:
                # IN.T resume
                pass
            c.waiting = False
            self._promote(c)
        elif op.kind == "xfer":
            self._engine_bit(c, op.job)
            assert op.job is not None
            if op.job.bits_done >= op.job.n_bits:
                if c.result_valid:
                    c.overrun = True
                c.result = op.job.result if op.job.mode != XferMode.OUT else op.job.data
                if op.job.mode == XferMode.IN or op.job.mode == XferMode.BOTH:
                    c.result = op.job.result
                c.result_valid = True
                self._promote(c)

    def _apply_miss(self, c: Context) -> None:
        if c.miss_policy == MissPolicy.FLAG:
            return
        if c.miss_policy == MissPolicy.TRAP:
            self._do_trap(c, c.events[0].vector)
        elif c.miss_policy == MissPolicy.SEND_DEFAULT:
            job = Job(XferMode.OUT, 8, c.default_byte, msb_first=c.ecfg_msb_first)
            self._post_timed(c, TimedOp("xfer", job=job))
            if c.timed_active and c.timed_active.kind == "xfer":
                self._engine_bit(c, c.timed_active.job)
                if c.timed_active.job.bits_done >= c.timed_active.job.n_bits:
                    c.result = c.timed_active.job.data
                    c.result_valid = True
                    self._promote(c)
        elif c.miss_policy == MissPolicy.STRETCH:
            c.stretching = True
            for li, p in enumerate(c.pins):
                if p.mode == PinMode.OPENDRAIN:
                    c.drive_val &= ~(1 << li)
                    c.drive_oe |= 1 << li

    def _engine_bit(self, c: Context, job: Optional[Job]) -> None:
        assert job is not None
        if c.stretching:
            c.stretching = False
            for li, p in enumerate(c.pins):
                if p.mode == PinMode.OPENDRAIN:
                    c.drive_oe &= ~(1 << li)
        remaining = job.n_bits - job.bits_done
        shift = (remaining - 1) if job.msb_first else job.bits_done
        out_bit = (job.data >> shift) & 1
        if job.mode in (XferMode.OUT, XferMode.BOTH):
            dout = 0
            mode = c.pins[dout].mode
            if mode == PinMode.OPENDRAIN:
                if out_bit == 0:
                    c.drive_val &= ~(1 << dout)
                    c.drive_oe |= 1 << dout
                else:
                    c.drive_oe &= ~(1 << dout)
            else:
                c.drive_val = (c.drive_val & ~(1 << dout)) | (out_bit << dout)
                c.drive_oe |= 1 << dout
        if job.mode in (XferMode.IN, XferMode.BOTH):
            din_lp = 1 if job.mode == XferMode.BOTH else 0
            in_bit = self._logical_in(c, din_lp)
            if job.msb_first:
                job.result = ((job.result << 1) | in_bit) & 0xFFFF
            else:
                job.result = (job.result | (in_bit << job.bits_done)) & 0xFFFF
            if job.mode == XferMode.BOTH and c.pins[0].mode == PinMode.OPENDRAIN:
                if out_bit == 1 and self._logical_in(c, 0) == 0:
                    c.arb = True
        job.bits_done += 1

    def _do_trap(self, c: Context, vector: int) -> None:
        c.pc = vector & 0x3F
        c.waiting = False
        c.timed_active = None
        c.timed_pending = None
        c.stretching = False
        c.pull_block = None
        c.mfs_rx = None
        self._stop_timer(c)
        for li, p in enumerate(c.pins):
            if p.mode == PinMode.INPUT:
                c.drive_oe &= ~(1 << li)
                continue
            bit = p.idle & 1
            c.drive_val = (c.drive_val & ~(1 << li)) | (bit << li)
            if p.mode == PinMode.OPENDRAIN:
                if bit:
                    c.drive_oe &= ~(1 << li)
                else:
                    c.drive_oe |= 1 << li
            else:
                c.drive_oe |= 1 << li

    def _do_set(self, c: Context, mask: int, val: int, oe: bool = False) -> None:
        for i in range(4):
            if not (mask & (1 << i)):
                continue
            bit = (val >> i) & 1
            if oe:
                if bit:
                    c.drive_oe |= 1 << i
                else:
                    c.drive_oe &= ~(1 << i)
            else:
                mode = c.pins[i].mode
                if mode == PinMode.OPENDRAIN:
                    if bit == 0:
                        c.drive_val &= ~(1 << i)
                        c.drive_oe |= 1 << i
                    else:
                        c.drive_oe &= ~(1 << i)
                else:
                    c.drive_val = (c.drive_val & ~(1 << i)) | (bit << i)
                    c.drive_oe |= 1 << i

    def _ensure_timer_for_timed(self, c: Context) -> None:
        if c.tick_source == TickSource.TIMER and not c.timer_running:
            self._start_timer(c)

    def _exec(self, ci: int) -> None:
        c = self.ctx[ci]
        if c.waiting:
            return
        abs_pc = c.base + c.pc
        if abs_pc >= c.base + c.bound or abs_pc >= IMEM_WORDS:
            return
        d = decode(self.imem[abs_pc])
        op = d["op"]
        next_pc = (c.pc + 1) & 0x3F

        if op == Op.SET:
            if d["timed"]:
                self._ensure_timer_for_timed(c)
                if not self._post_timed(c, TimedOp("set", mask=d["mask"], val=d["val"], oe=d["oe"])):
                    return  # stall
            else:
                self._do_set(c, d["mask"], d["val"], oe=d["oe"])
            c.pc = next_pc
            return

        if op == Op.IN:
            if d["timed"]:
                self._ensure_timer_for_timed(c)
                if not self._post_timed(c, TimedOp("in", lp=d["lp"])):
                    return
                c.waiting = True  # resume when IN consumes a tick
                c.wait_mask = 1 << 4
            else:
                c.c = bool(self._logical_in(c, d["lp"]))
                c.z = not c.c
            c.pc = next_pc
            return

        if op == Op.WAIT:
            tc = d["tc"]
            if tc in (WaitTc.REARM, WaitTc.IDLE):
                self._stop_timer(c)
            c.waiting = True
            c.wait_mask = d["evmask"]
            c.wait_tc = tc
            c.pc = next_pc
            return

        if op == Op.JMP:
            if self._eval_cond(c, d["cond"]):
                c.pc = d["addr"] & 0x3F
            else:
                c.pc = next_pc
            return

        if op == Op.LDI:
            c.regs[d["rd"]] = d["imm"] & 0xFF
            c.z = c.regs[d["rd"]] == 0
            c.pc = next_pc
            return

        if op == Op.ALU:
            self._alu(c, d["fn"], d["rd"], d["rs"])
            c.pc = next_pc
            return

        if op == Op.XFER:
            data = c.regs[d["rs"]] if d["mode"] != XferMode.IN else 0
            job = Job(d["mode"], d["n"], data, msb_first=c.ecfg_msb_first)
            if c.tick_source == TickSource.TIMER:
                self._ensure_timer_for_timed(c)
            if not self._post_timed(c, TimedOp("xfer", job=job)):
                return
            c.pc = next_pc
            return

        if op == Op.PULL:
            if not self.host_to_core:
                if d["nb"]:
                    c.regs[d["rd"]] = c.default_byte
                    c.under = True
                    c.last = False
                    c.cmd = False
                    c.pc = next_pc
                else:
                    c.waiting = True
                    c.pull_block = d["rd"]
                    c.wait_mask = 0
                    c.pc = next_pc
                return
            w = self.host_to_core.pop(0)
            c.regs[d["rd"]] = w.data
            c.last = w.last
            c.cmd = w.cmd
            c.z = w.data == 0
            c.pc = next_pc
            return

        if op == Op.PUSH:
            if len(self.core_to_host) >= HOST_FIFO_DEPTH:
                return
            self.core_to_host.append(HostWord(c.regs[d["rs"]], tag=d["tag"]))
            c.pc = next_pc
            return

        if op == Op.MFS:
            val = self._read_spr(c, d["spr"])
            if val is None:
                c.waiting = True
                c.mfs_rx = d["rd"]
                c.pc = next_pc
                return
            c.regs[d["rd"]] = val & 0xFF
            c.z = c.regs[d["rd"]] == 0
            c.pc = next_pc
            return

        if op == Op.MTS:
            self._write_spr(c, d["spr"], c.regs[d["rs"]])
            c.pc = next_pc
            return

    def _eval_cond(self, c: Context, cond: int) -> bool:
        if cond == JmpCond.AL:
            return True
        if cond == JmpCond.Z:
            return c.z
        if cond == JmpCond.NZ:
            return not c.z
        if cond == JmpCond.C:
            return c.c
        if cond == JmpCond.NC:
            return not c.c
        if cond == JmpCond.R1DEC:
            was = c.regs[1]
            c.regs[1] = (was - 1) & 0xFF
            c.z = c.regs[1] == 0
            return was != 0
        if JmpCond.E0 <= cond <= JmpCond.E3:
            return bool(c.evf & (1 << (cond - JmpCond.E0)))
        if cond == JmpCond.TK:
            return bool(c.evf & 0x10)
        if cond == JmpCond.LAST:
            return c.last
        if cond == JmpCond.CMD:
            return c.cmd
        if cond == JmpCond.HE:
            return len(self.host_to_core) == 0
        if cond == JmpCond.ERR:
            return c.miss or c.under or c.overrun or c.arb
        if cond == JmpCond.ARB:
            return c.arb
        return False

    def _alu(self, c: Context, fn: int, rd: int, rs: int) -> None:
        a, b = c.regs[rd], c.regs[rs]
        carry = False
        if fn == AluFn.MOV:
            r = b
        elif fn == AluFn.ADD:
            s = a + b
            r, carry = s & 0xFF, s > 255
        elif fn == AluFn.SUB:
            s = a - b
            r, carry = s & 0xFF, s < 0
        elif fn == AluFn.AND:
            r = a & b
        elif fn == AluFn.OR:
            r = a | b
        elif fn == AluFn.XOR:
            r = a ^ b
        elif fn == AluFn.CMP:
            s = a - b
            c.z = (s & 0xFF) == 0
            c.c = s < 0
            return
        elif fn == AluFn.SHR:
            carry = bool(a & 1)
            r = a >> 1
        else:
            r = a
        c.regs[rd] = r
        c.z = r == 0
        c.c = carry

    def _read_spr(self, c: Context, spr: int) -> Optional[int]:
        if spr == Spr.RX:
            if not c.result_valid:
                return None
            c.result_valid = False
            if c.result > 0xFF:
                c.c = bool((c.result >> 8) & 1)
            return c.result & 0xFF
        if spr == Spr.RXH:
            return (c.result >> 8) & 0xFF
        if spr == Spr.TIME_L:
            c.time_latch = c.time
            return c.time_latch & 0xFF
        if spr == Spr.TIME_H:
            return (c.time_latch >> 8) & 0xFF
        if spr == Spr.EVF:
            return c.evf & 0x1F
        if spr == Spr.ERR:
            return int(c.miss) | (int(c.under) << 1) | (int(c.overrun) << 2) | (int(c.arb) << 3)
        if spr == Spr.ECFG:
            return int(c.ecfg_msb_first)
        if spr == Spr.PC:
            return c.pc
        if spr == Spr.ID:
            return ID_VALUE
        return 0

    def _write_spr(self, c: Context, spr: int, val: int) -> None:
        val &= 0xFF
        if spr == Spr.ERR:
            if val & 1:
                c.miss = False
            if val & 2:
                c.under = False
            if val & 4:
                c.overrun = False
            if val & 8:
                c.arb = False
        elif spr == Spr.PER_L:
            c.per_fp = (c.per_fp & ~0xFF) | val
        elif spr == Spr.PER_M:
            c.per_fp = (c.per_fp & ~(0xFF << 8)) | (val << 8)
        elif spr == Spr.PER_H:
            c.per_fp = (c.per_fp & ~(0xF << 16)) | ((val & 0xF) << 16)
        elif spr == Spr.PHASE_L:
            c.phase = (c.phase & ~0xFF) | val
        elif spr == Spr.PHASE_H:
            c.phase = (c.phase & ~0xFF00) | (val << 8)
        elif spr == Spr.ECFG:
            c.ecfg_msb_first = bool(val & 1)
        elif spr == Spr.PC:
            c.pc = val & 0x3F

    def _service_waits(self, c: Context, tick: bool) -> None:
        if c.pull_block is not None and c.waiting:
            if self.host_to_core:
                rd = c.pull_block
                w = self.host_to_core.pop(0)
                c.regs[rd] = w.data
                c.last, c.cmd = w.last, w.cmd
                c.z = w.data == 0
                c.pull_block = None
                c.waiting = False
            return
        if c.mfs_rx is not None and c.waiting:
            if c.result_valid:
                rd = c.mfs_rx
                val = self._read_spr(c, Spr.RX)
                assert val is not None
                c.regs[rd] = val
                c.z = val == 0
                c.mfs_rx = None
                c.waiting = False
            return
        if not c.waiting:
            return
        # IN.T completes in _on_tick
        if c.timed_active and c.timed_active.kind == "in":
            return
        fired = 0
        ev_now = self._event_mask_now(c)
        for ei in range(N_EVENTS):
            if (c.wait_mask & (1 << ei)) and (ev_now & (1 << ei)):
                fired |= 1 << ei
        if (c.wait_mask & (1 << 4)) and tick:
            fired |= 1 << 4
        if c.wait_mask == 0:
            return
        if not fired:
            return
        c.evf = fired
        c.waiting = False
        if c.wait_tc == WaitTc.REARM:
            self._start_timer(c)
        elif c.wait_tc in (WaitTc.STOP, WaitTc.IDLE):
            self._stop_timer(c)

    def _check_traps(self, c: Context) -> None:
        for ei, e in enumerate(c.events):
            if e.trap and self._event_active(c, ei):
                self._do_trap(c, e.vector)
                c.evf = 1 << ei
                return

    def step(self) -> None:
        levels = [self._phys_level(p) for p in range(8)]
        self._sync_prev = list(self._sync1)
        for p in range(8):
            self._sync1[p] = self._sync0[p]
            self._sync0[p] = levels[p]

        for c in self.ctx:
            self._check_traps(c)

        ticks = []
        for c in self.ctx:
            tick = False
            if c.tick_source == TickSource.TIMER and c.timer_running:
                tick = self._emit_tick(c)
                c.time = (c.time + 1) & 0xFFFF
            elif c.tick_source == TickSource.PIN_EDGE:
                tick = self._emit_tick(c)
            ticks.append(tick)

        for ci, c in enumerate(self.ctx):
            had_timed = c.timed_active is not None
            if ticks[ci]:
                self._on_tick(c)
            # A WAIT on TICK only completes on a tick that did not feed a timed op.
            self._service_waits(c, ticks[ci] and not had_timed)

        for _ in range(N_CONTEXTS):
            ci = self.sched
            self.sched = (self.sched + 1) % N_CONTEXTS
            c = self.ctx[ci]
            if c.waiting:
                continue
            abs_pc = c.base + c.pc
            if abs_pc < IMEM_WORDS and decode(self.imem[abs_pc])["op"] in (
                Op.XFER,
                Op.SET,
                Op.IN,
            ):
                # may stall if timed slots full — _exec handles it
                pass
            self._exec(ci)
            break

        self._apply_drives()
        if self.enable_trace:
            self.trace.append({"cycle": self.cycle, "pc0": self.ctx[0].pc, "tick0": ticks[0]})
        self.cycle += 1

    def run(self, n: int) -> None:
        for _ in range(n):
            self.step()
