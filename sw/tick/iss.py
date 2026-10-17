"""Cycle-accurate instruction-set simulator for the Tick ISA."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional

from .isa import (
    DEFAULT_BYTE,
    HOST_FIFO_DEPTH,
    ID_VALUE,
    IMEM_WORDS,
    N_CONTEXTS,
    N_EVENTS,
    N_LOGICAL_PINS,
    READBACK_LATENCY,
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

# 2 synchroniser flops on every input. Own-drive feedback into that path is
# delayed by (READBACK_LATENCY - 2) so IN sees a same-context SET from cycle N
# in cycle N+READBACK_LATENCY (docs/isa.md).
_SYNC_DEPTH = 2
_OWN_SAMPLE_DELAY = READBACK_LATENCY - _SYNC_DEPTH
assert _OWN_SAMPLE_DELAY >= 0


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
    glitch_filter: bool = False


@dataclass
class EventCfg:
    kind: EventKind = EventKind.LEVEL_HIGH
    pin: int = 0
    qual_pin: int = 1
    trap: bool = False
    vector: int = 0
    latched: bool = False  # edge modes only; PULSE=False, LATCHED=True


@dataclass
class Job:
    mode: int
    n_bits: int
    data: int
    bits_done: int = 0
    result: int = 0
    msb_first: bool = True
    half: int = 0  # 0=leading, 1=trailing when ecfg_clk_en


@dataclass
class TimedOp:
    kind: str  # set | xfer | in | wait
    mask: int = 0
    val: int = 0
    oe: bool = False
    job: Optional[Job] = None
    lp: int = 0
    wait_mask: int = 0
    wait_tc: int = 0


@dataclass
class Context:
    regs: list[int] = field(default_factory=lambda: [0, 0, 0, 0])
    pc: int = 0
    base: int = 0
    bound: int = IMEM_WORDS
    enabled: bool = False  # host must configure a context before it issues
    z: bool = False
    c: bool = False
    evf: int = 0
    last: bool = False
    cmd: bool = False
    miss: bool = False
    under: bool = False
    overrun: bool = False
    arb: bool = False
    map_err: bool = False
    cfg_err: bool = False
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
    miss_vector: int = 0
    default_byte: int = DEFAULT_BYTE
    ecfg_msb_first: bool = True
    ecfg_clk_en: bool = False  # engine clock: two ticks/bit + drive CLK
    ecfg_cpha: bool = False
    ecfg_cpol: bool = False  # idle level of CLK when inactive
    dout_lp: int = 0  # engine pin selection
    din_lp: int = 1
    clk_lp: int = 2
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
    ev_pending: int = 0  # latched-edge pending flags, bits 0..3 = EV0..EV3
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
        # End-of-previous-cycle pin sample feeding the synchroniser.
        self._pin_sample = [1] * 8
        # Delayed copy of own drives into the sample path (not the wire).
        self._own_delay = [[1] * 8 for _ in range(max(1, _OWN_SAMPLE_DELAY))]
        # Extra history for optional 3-sample majority after the 2-flop sync.
        self._maj_hist = [[1, 1, 1] for _ in range(8)]
        self._filt = [1] * 8
        self._filt_prev = [1] * 8
        self.double_drive = False
        self.trace: list[dict] = []
        self.enable_trace = False
        # After enable/RUN-rise snap: suppress pin traps for one step (RTL
        # run_rise); HOST_DATA / HOST_SPACE still fire.
        self._pin_trap_suppress = False
        # Flat config image (docs/isa.md §2.1); ENABLE at 0x00.
        self.cfg_mem = [0] * 0x50
        self.cfg_addr = 0
        self.cfg_rdata_latch = 0

    def load(self, image: list[int], configs: Optional[list[dict]] = None) -> None:
        self.imem = [0] * IMEM_WORDS
        for i, w in enumerate(image):
            self.imem[i] = w & 0xFFFF
        if configs:
            for i, cfg in enumerate(configs):
                self.configure(i, cfg)

    def configure(self, ci: int, cfg: dict) -> None:
        """Dict convenience: packs §2.1 bytes then applies them (enables context)."""
        from .cfg import dict_to_bytes

        # Load-time path: keep disabled until all context bytes are written.
        self.ctx[ci].enabled = False
        blobs = dict_to_bytes(ci, cfg, enable_mask=None)
        for addr, val in sorted(blobs.items()):
            if addr == 0x00:
                continue
            self.cfg_write(addr, val)
        self.ctx[ci].pc = 0
        mask = self.cfg_mem[0] & 3
        if cfg.get("enabled", True):
            mask |= 1 << ci
        else:
            mask &= ~(1 << ci)
        self.cfg_write(0x00, mask)

    def _snap_inputs_after_enable(self) -> None:
        """Match RTL RUN-rise: settle sync to idle drives; clear pending; no edge.

        Sync flops reset to 1; push-pull idle=0 then feeds the sample path and
        would look like EDGE_FALL without this snap (RTL settles while !run and
        clears pending / snaps lp_prev on RUN rise — docs/isa.md).
        """
        self._apply_drives()
        cur = [self.phys_drive[q] & 1 for q in range(8)]
        self._own_delay = [list(cur) for _ in self._own_delay]
        self._pin_sample = self._sample_pins_for_sync()
        for p in range(8):
            s = self._pin_sample[p] & 1
            self._sync0[p] = s
            self._sync1[p] = s
            self._sync_prev[p] = s
            self._maj_hist[p] = [s, s, s]
            self._filt[p] = s
            self._filt_prev[p] = s
        for c in self.ctx:
            c.ev_pending = 0
        self._pin_trap_suppress = True

    def cfg_write(self, addr: int, val: int) -> None:
        """Write one config byte (same rules as the RTL config port)."""
        from . import cfg as C

        addr &= 0xFF
        val &= 0xFF
        if addr == C.ADDR_ENABLE:
            prev = self.cfg_mem[addr] & 3
            self.cfg_mem[addr] = val & 3
            for i in range(N_CONTEXTS):
                self.ctx[i].enabled = bool(val & (1 << i))
            # Rising enable on any context → snap inputs (RTL RUN-rise analogue).
            if (val & 3) & ~prev:
                self._snap_inputs_after_enable()
            return
        if addr < 0x10 or addr >= 0x50:
            return
        ci = 0 if addr < C.CTX1_BASE else 1
        if self.ctx[ci].enabled:
            self.ctx[ci].cfg_err = True
            return
        self.cfg_mem[addr] = val
        self._apply_cfg_byte(ci, addr, val)

    def cfg_read(self, addr: int) -> int:
        addr &= 0xFF
        if addr < len(self.cfg_mem):
            return self.cfg_mem[addr] & 0xFF
        return 0

    def _apply_cfg_byte(self, ci: int, addr: int, val: int) -> None:
        from . import cfg as C

        c = self.ctx[ci]
        off = addr - C.ctx_base(ci)
        if off == C.OFF_PINMAP_LO:
            c.pins[0].physical = val & 7
            c.pins[1].physical = (val >> 4) & 7
        elif off == C.OFF_PINMAP_HI:
            c.pins[2].physical = val & 7
            c.pins[3].physical = (val >> 4) & 7
        elif off == C.OFF_PINMODE:
            for i in range(4):
                c.pins[i].mode = PinMode((val >> (2 * i)) & 3)
                c.drive_oe &= ~(1 << i)  # reset OE; mode INPUT until drive
                if c.pins[i].mode == PinMode.PUSHPULL:
                    c.drive_oe |= 1 << i
                    c.drive_val = (c.drive_val & ~(1 << i)) | ((c.pins[i].idle & 1) << i)
                elif c.pins[i].mode == PinMode.OPENDRAIN:
                    if c.pins[i].idle:
                        c.drive_oe &= ~(1 << i)
                    else:
                        c.drive_oe |= 1 << i
                        c.drive_val &= ~(1 << i)
        elif off == C.OFF_PINIDLE:
            # PINMODE is at a lower address so it often runs first while idle is
            # still the dataclass default (1). Re-apply drive when idle arrives.
            for i in range(4):
                c.pins[i].idle = (val >> i) & 1
                mode = c.pins[i].mode
                if mode == PinMode.PUSHPULL:
                    c.drive_oe |= 1 << i
                    c.drive_val = (c.drive_val & ~(1 << i)) | ((c.pins[i].idle & 1) << i)
                elif mode == PinMode.OPENDRAIN:
                    if c.pins[i].idle:
                        c.drive_oe &= ~(1 << i)
                    else:
                        c.drive_oe |= 1 << i
                        c.drive_val &= ~(1 << i)
        elif off == C.OFF_ENGINE:
            c.dout_lp = val & 3
            c.din_lp = (val >> 2) & 3
            c.clk_lp = (val >> 4) & 3
            c.ecfg_msb_first = bool(val & 0x40)
            c.ecfg_clk_en = bool(val & 0x80)
            self._sync_clk_tick_pin(c)
        elif off == C.OFF_CLKCFG:
            c.ecfg_cpol = bool(val & 1)
            c.ecfg_cpha = bool(val & 2)
        elif off == C.OFF_TICK:
            c.tick_source = TickSource(val & 1)
            c.tick_on_rise = bool(val & 2)
            c.tick_pin = (val >> 2) & 3
            self._sync_clk_tick_pin(c)
        elif off == C.OFF_MISS:
            c.miss_policy = MissPolicy(val & 3)
            c.miss_vector = (val >> 2) & 0x3F
        elif off == C.OFF_DEFAULT:
            c.default_byte = val
        elif off == C.OFF_PER_L:
            c.per_fp = (c.per_fp & ~0xFF) | val
        elif off == C.OFF_PER_M:
            c.per_fp = (c.per_fp & ~(0xFF << 8)) | (val << 8)
        elif off == C.OFF_PER_H:
            c.per_fp = (c.per_fp & ~(0xF << 16)) | ((val & 0xF) << 16)
        elif off == C.OFF_PHASE_L:
            c.phase = (c.phase & ~0xFF) | val
        elif off == C.OFF_PHASE_H:
            c.phase = (c.phase & ~0xFF00) | (val << 8)
        elif off == C.OFF_BASE:
            c.base = val & 0x3F
        elif off == C.OFF_BOUND:
            b = val & 0x3F
            c.bound = 64 if b == 0 else b
        elif off == C.OFF_GLITCH:
            for i in range(4):
                c.pins[i].glitch_filter = bool(val & (1 << i))
        elif C.OFF_EV0_CFG <= off <= C.OFF_EV0_TRAP + 6:
            ei = (off - C.OFF_EV0_CFG) // 2
            if (off - C.OFF_EV0_CFG) % 2 == 0:
                c.events[ei].kind = EventKind(val & 0xF)
                c.events[ei].pin = (val >> 4) & 3
                c.events[ei].qual_pin = (val >> 6) & 3
            else:
                c.events[ei].trap = bool(val & 1)
                c.events[ei].vector = (val >> 1) & 0x3F
                c.events[ei].latched = bool(val & 0x80)

    def _sync_clk_tick_pin(self, c: Context) -> None:
        if c.ecfg_clk_en and c.tick_source == TickSource.PIN_EDGE:
            if c.tick_pin != c.clk_lp:
                c.cfg_err = True
            c.tick_pin = c.clk_lp

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
        # Per physical pin: collect (ci, li, bit) drives; lower LP wins within a
        # context, higher context index wins across contexts (legacy).
        drives: list[list[tuple[int, int, int]]] = [[] for _ in range(8)]
        for ci, c in enumerate(self.ctx):
            seen_phys: dict[int, int] = {}
            for li in range(N_LOGICAL_PINS):
                phys = c.pins[li].physical
                if not (0 <= phys <= 7):
                    continue
                mode = c.pins[li].mode
                bit = (c.drive_val >> li) & 1
                oe = (c.drive_oe >> li) & 1
                if mode == PinMode.INPUT:
                    continue
                driving = False
                if mode == PinMode.OPENDRAIN:
                    if bit == 0 and oe:
                        driving = True
                        bit = 0
                else:
                    if oe:
                        driving = True
                if not driving:
                    continue
                if phys in seen_phys:
                    c.map_err = True
                    # lower LP already recorded wins
                    continue
                seen_phys[phys] = li
                drives[phys].append((ci, li, bit))
        self.double_drive = False
        for p in range(8):
            if len(drives[p]) > 1:
                self.double_drive = True
                # Across contexts: highest context index wins
                _, _, val = max(drives[p], key=lambda x: x[0])
                self.phys_oe[p] = 1
                self.phys_drive[p] = val
            elif len(drives[p]) == 1:
                _, _, val = drives[p][0]
                self.phys_oe[p] = 1
                self.phys_drive[p] = val
            else:
                self.phys_oe[p] = 0

    def _pin_now(self, c: Context, li: int) -> int:
        phys = c.pins[li].physical
        if c.pins[li].glitch_filter:
            return self._filt[phys]
        return self._sync1[phys]

    def _pin_prev(self, c: Context, li: int) -> int:
        phys = c.pins[li].physical
        if c.pins[li].glitch_filter:
            return self._filt_prev[phys]
        return self._sync_prev[phys]

    def _logical_in(self, c: Context, li: int) -> int:
        return self._pin_now(c, li)

    @staticmethod
    def _is_edge_kind(kind: EventKind) -> bool:
        return kind in (
            EventKind.EDGE_RISE,
            EventKind.EDGE_FALL,
            EventKind.QUAL_FALL_WHILE_HIGH,
            EventKind.QUAL_RISE_WHILE_HIGH,
        )

    def _event_active(self, c: Context, ei: int) -> bool:
        """Live pulse/level this cycle (traps and latch-update use this)."""
        e = c.events[ei]
        if e.kind == EventKind.HOST_DATA:
            return len(self.host_to_core) > 0
        if e.kind == EventKind.HOST_SPACE:
            return len(self.core_to_host) < HOST_FIFO_DEPTH
        pin = self._logical_in(c, e.pin)
        prev = self._pin_prev(c, e.pin)
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

    def _event_for_wait(self, c: Context, ei: int) -> bool:
        """WAIT visibility: LATCHED edges use pending; else live pulse/level."""
        e = c.events[ei]
        if e.latched and self._is_edge_kind(e.kind):
            return bool(c.ev_pending & (1 << ei))
        return self._event_active(c, ei)

    def _event_mask_now(self, c: Context) -> int:
        """WAIT event mask (pending for LATCHED edges)."""
        m = 0
        for ei in range(N_EVENTS):
            if self._event_for_wait(c, ei):
                m |= 1 << ei
        return m

    def _update_ev_pending(self, c: Context) -> None:
        for ei, e in enumerate(c.events):
            if e.latched and self._is_edge_kind(e.kind) and self._event_active(c, ei):
                c.ev_pending |= 1 << ei

    def _clear_ev_pending(self, c: Context, mask: int) -> None:
        c.ev_pending &= ~(mask & 0xF)

    def _emit_tick(self, c: Context) -> bool:
        if c.tick_source == TickSource.PIN_EDGE:
            pin = self._pin_now(c, c.tick_pin)
            prev = self._pin_prev(c, c.tick_pin)
            if c.ecfg_clk_en:
                # Both edges are ticks (engine clock, target mode).
                return prev != pin
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
            self._end_stretch(c)
            self._do_set(c, op.mask, op.val, oe=op.oe)
            self._promote(c)
        elif op.kind == "in":
            self._end_stretch(c)
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
        elif op.kind == "wait":
            # Tick consumed; OR any same-cycle events in the mask (docs rule 6a).
            self._end_stretch(c)
            fired = 1 << 4
            ev_now = self._event_mask_now(c)
            for ei in range(N_EVENTS):
                if (op.wait_mask & (1 << ei)) and (ev_now & (1 << ei)):
                    fired |= 1 << ei
            c.evf = fired
            self._clear_ev_pending(c, fired)
            c.waiting = False
            if op.wait_tc == WaitTc.REARM:
                self._start_timer(c)
            elif op.wait_tc in (WaitTc.STOP, WaitTc.IDLE):
                self._stop_timer(c)
            self._promote(c)

    def _apply_wait_tc(self, c: Context, tc: int) -> None:
        if tc == WaitTc.REARM:
            self._start_timer(c)
        elif tc in (WaitTc.STOP, WaitTc.IDLE):
            self._stop_timer(c)

    def _try_event_complete_wait(self, c: Context, tick: bool = False) -> bool:
        """Event-first dequeue of a timed WAIT (non-tick events).

        If this cycle also has a tick and the wait mask includes TICK, skip:
        ``_on_tick`` consumes the tick and ORs event bits into EVF (docs 6a).
        """
        if not c.waiting or c.pull_block is not None or c.mfs_rx is not None:
            return False
        where = None
        op = None
        if c.timed_active is not None and c.timed_active.kind == "wait":
            where, op = "a", c.timed_active
        elif c.timed_pending is not None and c.timed_pending.kind == "wait":
            where, op = "p", c.timed_pending
        if op is None:
            return False
        if tick and (op.wait_mask & (1 << 4)):
            return False
        fired = 0
        ev_now = self._event_mask_now(c)
        for ei in range(N_EVENTS):
            if (op.wait_mask & (1 << ei)) and (ev_now & (1 << ei)):
                fired |= 1 << ei
        if not fired:
            return False
        if where == "a":
            self._promote(c)
        else:
            c.timed_pending = None
        c.evf = fired
        self._clear_ev_pending(c, fired)
        c.waiting = False
        self._apply_wait_tc(c, op.wait_tc)
        return True

    def _apply_miss(self, c: Context) -> None:
        if c.miss_policy == MissPolicy.FLAG:
            return
        if c.miss_policy == MissPolicy.TRAP:
            self._do_trap(c, c.miss_vector)
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
            # Hold only the configured clock logical pin low (open-drain).
            clk = c.clk_lp & 3
            if c.pins[clk].mode == PinMode.OPENDRAIN:
                c.drive_val &= ~(1 << clk)
                c.drive_oe |= 1 << clk

    def _drive_lp(self, c: Context, lp: int, bit: int, oe: bool = True) -> None:
        mode = c.pins[lp].mode
        if mode == PinMode.OPENDRAIN:
            if bit == 0 and oe:
                c.drive_val &= ~(1 << lp)
                c.drive_oe |= 1 << lp
            else:
                c.drive_oe &= ~(1 << lp)
        elif mode == PinMode.INPUT:
            return
        else:
            c.drive_val = (c.drive_val & ~(1 << lp)) | ((bit & 1) << lp)
            if oe:
                c.drive_oe |= 1 << lp
            else:
                c.drive_oe &= ~(1 << lp)

    def _clk_active_level(self, c: Context) -> int:
        return 0 if c.ecfg_cpol else 1

    def _clk_idle_level(self, c: Context) -> int:
        return 1 if c.ecfg_cpol else 0

    def _sample_din(self, c: Context, job: Job) -> None:
        lp = c.din_lp if job.mode != XferMode.IN else c.dout_lp
        in_bit = self._logical_in(c, lp)
        if job.msb_first:
            job.result = ((job.result << 1) | in_bit) & 0xFFFF
        else:
            job.result = (job.result | (in_bit << job.bits_done)) & 0xFFFF

    def _out_bit(self, job: Job) -> int:
        remaining = job.n_bits - job.bits_done
        shift = (remaining - 1) if job.msb_first else job.bits_done
        return (job.data >> shift) & 1

    def _end_stretch(self, c: Context) -> None:
        """Release MISS stretch when a timed job is consumed (docs: until a job arrives)."""
        if not c.stretching:
            return
        c.stretching = False
        clk = c.clk_lp & 3
        if c.pins[clk].mode == PinMode.OPENDRAIN:
            c.drive_oe &= ~(1 << clk)

    def _engine_bit(self, c: Context, job: Optional[Job]) -> None:
        assert job is not None
        self._end_stretch(c)

        if c.ecfg_clk_en:
            # Engine clock: two ticks per bit.
            # Controller (timer ticks): drive CLK_LP. Target (pin-edge): do not.
            drive_clk = c.tick_source == TickSource.TIMER
            outb = self._out_bit(job)
            if job.half == 0:
                if c.ecfg_cpha:
                    # CPHA=1: leading updates data + clock active
                    if job.mode in (XferMode.OUT, XferMode.BOTH):
                        self._drive_lp(c, c.dout_lp, outb)
                    if drive_clk:
                        self._drive_lp(c, c.clk_lp, self._clk_active_level(c))
                else:
                    # CPHA=0: data already valid (first bit on post); sample + clock active
                    if job.mode in (XferMode.IN, XferMode.BOTH):
                        self._sample_din(c, job)
                    if drive_clk:
                        self._drive_lp(c, c.clk_lp, self._clk_active_level(c))
                job.half = 1
                return
            # trailing
            if c.ecfg_cpha:
                if job.mode in (XferMode.IN, XferMode.BOTH):
                    self._sample_din(c, job)
                if drive_clk:
                    self._drive_lp(c, c.clk_lp, self._clk_idle_level(c))
            else:
                if drive_clk:
                    self._drive_lp(c, c.clk_lp, self._clk_idle_level(c))
                if job.mode in (XferMode.OUT, XferMode.BOTH) and job.bits_done + 1 < job.n_bits:
                    # data for next bit changes on trailing edge
                    job.bits_done += 1
                    self._drive_lp(c, c.dout_lp, self._out_bit(job))
                    job.bits_done -= 1
            if job.mode == XferMode.BOTH and c.pins[c.dout_lp].mode == PinMode.OPENDRAIN:
                if outb == 1 and self._logical_in(c, c.dout_lp) == 0:
                    c.arb = True
            job.half = 0
            job.bits_done += 1
            return

        # Single-tick /bit (UART, SPI target on external SCLK, …)
        out_bit = self._out_bit(job)
        if job.mode in (XferMode.OUT, XferMode.BOTH):
            self._drive_lp(c, c.dout_lp, out_bit)
        if job.mode in (XferMode.IN, XferMode.BOTH):
            self._sample_din(c, job)
            if job.mode == XferMode.BOTH and c.pins[c.dout_lp].mode == PinMode.OPENDRAIN:
                if out_bit == 1 and self._logical_in(c, c.dout_lp) == 0:
                    c.arb = True
        job.bits_done += 1

    def _do_trap(self, c: Context, vector: int, *, clear_pending: int = 0) -> None:
        """Trap: cancel queue, idle pins, PC:=vector. Clear only clear_pending latched bits."""
        c.pc = vector & 0x3F
        c.waiting = False
        c.timed_active = None
        c.timed_pending = None
        c.stretching = False
        c.pull_block = None
        c.mfs_rx = None
        self._clear_ev_pending(c, clear_pending)
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
            mask = d["evmask"]
            if mask & (1 << 4):
                # Timed WAIT: occupies a queue slot (draft rule 2).
                self._ensure_timer_for_timed(c)
                if not self._post_timed(
                    c, TimedOp("wait", wait_mask=mask, wait_tc=tc)
                ):
                    return
            c.waiting = True
            c.wait_mask = mask
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
            n = d["n"]
            if d["mode"] in (XferMode.OUT, XferMode.BOTH) and n > 8:
                raise ValueError("XFER out/both width must be 1..8")
            job = Job(d["mode"], n, data, msb_first=c.ecfg_msb_first)
            if c.tick_source == TickSource.TIMER:
                self._ensure_timer_for_timed(c)
            if not self._post_timed(c, TimedOp("xfer", job=job)):
                return
            # CPHA=0 + engine clock: first DOUT bit when the job is posted.
            if (
                c.ecfg_clk_en
                and not c.ecfg_cpha
                and d["mode"] in (XferMode.OUT, XferMode.BOTH)
            ):
                self._drive_lp(c, c.dout_lp, self._out_bit(job))
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
            # MTS PC is a computed jump: write_spr sets pc; do not advance.
            if d["spr"] != Spr.PC:
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
            # Any sticky ERR bit (MISS/UNDER/OVERRUN/ARB/MAP/CFG).
            return bool(self._read_spr(c, Spr.ERR))
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
            return int(c.miss) | (int(c.under) << 1) | (int(c.overrun) << 2) | (int(c.arb) << 3) | (int(c.map_err) << 4) | (int(c.cfg_err) << 5)
        if spr == Spr.ECFG:
            return (
                int(c.ecfg_msb_first)
                | (int(c.ecfg_clk_en) << 1)
                | (int(c.ecfg_cpha) << 2)
                | (int(c.ecfg_cpol) << 3)
            )
        if spr == Spr.PC:
            return c.pc
        if spr == Spr.ID:
            return ID_VALUE
        if spr == Spr.EVCLR:
            return c.ev_pending & 0xF
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
            if val & 16:
                c.map_err = False
            if val & 32:
                c.cfg_err = False
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
            c.ecfg_clk_en = bool(val & 2)
            c.ecfg_cpha = bool(val & 4)
            c.ecfg_cpol = bool(val & 8)
        elif spr == Spr.PC:
            c.pc = val & 0x3F
        elif spr == Spr.EVCLR:
            self._clear_ev_pending(c, val)

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
        # Timed WAIT (kind=wait) completes in _on_tick / _try_event_complete_wait.
        if c.timed_active and c.timed_active.kind == "wait":
            return
        if c.timed_pending and c.timed_pending.kind == "wait":
            return
        # IN.T completes in _on_tick
        if c.timed_active and c.timed_active.kind == "in":
            return
        fired = 0
        ev_now = self._event_mask_now(c)
        for ei in range(N_EVENTS):
            if (c.wait_mask & (1 << ei)) and (ev_now & (1 << ei)):
                fired |= 1 << ei
        # Soft WAIT never includes tick; tick-bearing WAIT is a timed op.
        if c.wait_mask == 0:
            return
        if not fired:
            return
        c.evf = fired
        self._clear_ev_pending(c, fired)
        c.waiting = False
        self._apply_wait_tc(c, c.wait_tc)

    def _check_traps(self, c: Context) -> None:
        # Same-cycle priority: lower event index wins; EVF reports the winner.
        # Clears only that event's latched pending (MISS traps clear none).
        # Pin traps skipped for one cycle after enable snap (docs RUN-rise).
        for ei, e in enumerate(c.events):
            if not (e.trap and self._event_active(c, ei)):
                continue
            if self._pin_trap_suppress and e.kind.value < EventKind.HOST_DATA.value:
                continue
            self._do_trap(c, e.vector, clear_pending=(1 << ei))
            c.evf = 1 << ei
            return

    def _sample_pins_for_sync(self) -> list[int]:
        """Levels captured at end of cycle for the next cycle's synchroniser."""
        levels = []
        for p in range(8):
            if self.phys_oe[p]:
                # Own drive enters the sync path after _OWN_SAMPLE_DELAY cycles.
                levels.append(self._own_delay[-1][p] & 1)
            else:
                levels.append(self.phys_ext[p] & 1)
        return levels

    def _shift_own_delay(self) -> None:
        cur = [self.phys_drive[p] & 1 for p in range(8)]
        if _OWN_SAMPLE_DELAY == 0:
            self._own_delay = [cur]
        else:
            self._own_delay = [cur] + self._own_delay[:-1]

    def step(self) -> None:
        # Synchronisers sample the previous cycle's end-of-cycle pin capture.
        levels = list(self._pin_sample)
        self._sync_prev = list(self._sync1)
        self._filt_prev = list(self._filt)
        for p in range(8):
            self._sync1[p] = self._sync0[p]
            self._sync0[p] = levels[p]
            self._maj_hist[p] = [self._sync1[p]] + self._maj_hist[p][:2]
            s = sum(self._maj_hist[p])
            self._filt[p] = 1 if s >= 2 else 0

        for c in self.ctx:
            if not c.enabled:
                continue
            self._update_ev_pending(c)
            self._check_traps(c)
        self._pin_trap_suppress = False

        ticks = []
        for c in self.ctx:
            tick = False
            if c.enabled:
                if c.tick_source == TickSource.TIMER and c.timer_running:
                    tick = self._emit_tick(c)
                    c.time = (c.time + 1) & 0xFFFF
                elif c.tick_source == TickSource.PIN_EDGE:
                    tick = self._emit_tick(c)
            ticks.append(tick)

        for ci, c in enumerate(self.ctx):
            if not c.enabled:
                continue
            # Event-first: dequeue timed WAIT on non-tick events before the tick.
            # Same-cycle event+tick (mask includes TICK) is handled in _on_tick.
            self._try_event_complete_wait(c, tick=ticks[ci])
            if ticks[ci]:
                self._on_tick(c)
            # Soft event waits / PULL / MFS (tick-bearing WAIT handled above).
            self._service_waits(c, False)

        for _ in range(N_CONTEXTS):
            ci = self.sched
            self.sched = (self.sched + 1) % N_CONTEXTS
            c = self.ctx[ci]
            if not c.enabled or c.waiting:
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
        # Wire updates immediately for external observers; sync path is delayed.
        # Capture sync sample from the delayed own-drive *before* shifting the delay.
        self._pin_sample = self._sample_pins_for_sync()
        self._shift_own_delay()
        if self.enable_trace:
            self.trace.append({"cycle": self.cycle, "pc0": self.ctx[0].pc, "tick0": ticks[0]})
        self.cycle += 1

    def run(self, n: int) -> None:
        for _ in range(n):
            self.step()
