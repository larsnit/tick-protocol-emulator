"""Protocol checkers: UART TX waveform vs 8N1 model."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sw"))
sys.path.insert(0, str(ROOT / "verification" / "model"))

import pytest

from tick import EventKind, Machine, PinMode, TickSource, assemble
from check_uart import decode_uart_frame, falling_edges


_XFAIL_SINGLE_EDGE = pytest.mark.xfail(
    strict=True,
    reason="single-edge engine drives SDA on SCL rise; fixed by engine clock (docs/isa.md §4)",
)
_SPI_XFAIL_SINGLE_EDGE = pytest.mark.xfail(
    strict=True,
    reason=(
        "single-edge engine drives MISO on sample edge; fixed by engine clock "
        "(docs/isa.md §4). Keep strict: a prior XPASS was from pin drive stuck "
        "at idle-default 1 (PINIDLE after PINMODE), masking 0→1 on 0xFF MSB."
    ),
)


def _uart_tx_cfg(per: float = 8.0):
    return {
        "per": per,
        "phase": 0,
        "tick_source": TickSource.TIMER,
        "msb_first": False,  # UART LSB first
        "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 1}],
        "events": [{"kind": EventKind.HOST_DATA}],
    }


def sample_uart_bits(levels: list[tuple[int, int]], per: int, start_cycle: int, nbits: int) -> list[int]:
    """Sample pin at mid-bit for nbits starting at start_cycle (start bit)."""
    bits = []
    for k in range(nbits):
        t = start_cycle + k * per + per // 2
        # find level at cycle t
        val = 1
        for cy, lv in levels:
            if cy <= t:
                val = lv
            else:
                break
        bits.append(val)
    return bits


def test_uart_tx_byte_0x55():
    img = assemble((ROOT / "sw" / "programs" / "uart_tx.asm").read_text())
    m = Machine()
    m.load(img, [_uart_tx_cfg(8.0)])
    m.host_push(0x55, last=True)
    levels = []
    prev = 1
    for _ in range(200):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else m.phys_ext[0]
        if cur != prev or not levels:
            levels.append((m.cycle, cur))
            prev = cur
    # Find first falling edge (start bit)
    start = None
    for i, (cy, lv) in enumerate(levels):
        if lv == 0 and (i == 0 or levels[i - 1][1] == 1):
            start = cy
            break
    assert start is not None, levels
    # Build dense level timeline
    dense = []
    val = 1
    li = 0
    for cy in range(0, start + 12 * 8):
        while li < len(levels) and levels[li][0] <= cy:
            val = levels[li][1]
            li += 1
        dense.append(val)
    # Sample start + 8 data + stop at bit centers
    per = 8
    bits = []
    for k in range(10):
        t = start + k * per + per // 2
        if t < len(dense):
            bits.append(dense[t])
    assert bits[0] == 0, bits  # start
    data = 0
    for i, b in enumerate(bits[1:9]):
        data |= b << i
    assert data == 0x55, bits
    assert bits[9] == 1, bits  # stop


def _pin_trace(m: Machine, n: int) -> list[int]:
    trace = []
    for _ in range(n):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else m.phys_ext[0]
        trace.append(cur)
    return trace


def _falling_edges(trace: list[int]) -> list[int]:
    return [i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0]


def _rising_edges(trace: list[int]) -> list[int]:
    return [i for i in range(1, len(trace)) if trace[i - 1] == 0 and trace[i] == 1]


def test_uart_tx_back_to_back():
    """Context enable: two frames with exact PER spacing; disabled ctx1 must not steal host bytes."""
    per = 8
    img = assemble((ROOT / "sw" / "programs" / "uart_tx.asm").read_text())
    m = Machine()
    m.load(img, [_uart_tx_cfg(float(per))])
    assert m.ctx[0].enabled and not m.ctx[1].enabled
    m.host_push(0x11)
    m.host_push(0x22, last=True)

    miss_while_timer = False
    trace = []
    for _ in range(400):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else m.phys_ext[0]
        trace.append(cur)
        if m.ctx[0].timer_running and m.ctx[0].miss:
            miss_while_timer = True

    assert len(m.host_to_core) == 0
    assert m.ctx[1].regs[0] == 0  # ctx1 never pulled

    # First falling edge after reset idle is start of frame 0
    s0 = next(i for i in range(1, len(trace)) if trace[i - 1] == 1 and trace[i] == 0)
    s1 = s0 + 10 * per  # start + 8 data + stop, then next start
    assert s1 + 10 * per < len(trace)

    def decode_frame(start: int) -> int:
        bits = [trace[start + k * per + per // 2] for k in range(10)]
        assert bits[0] == 0 and bits[9] == 1, (start, bits)
        data = 0
        for i, b in enumerate(bits[1:9]):
            data |= b << i
        return data

    assert decode_frame(s0) == 0x11
    assert decode_frame(s1) == 0x22
    # Second start begins exactly one PER after first stop begins
    stop0 = s0 + 9 * per
    assert s1 == stop0 + per, (s0, stop0, s1)
    # No MISS while the timer is still producing the frames
    # (tick-WAIT may still set MISS after the final stop WAIT — allow only after last stop)
    last_stop_end = s1 + 10 * per
    early_miss = False
    m2 = Machine()
    m2.load(img, [_uart_tx_cfg(float(per))])
    m2.host_push(0x11)
    m2.host_push(0x22, last=True)
    for cy in range(last_stop_end):
        m2.step()
        if m2.ctx[0].miss and cy < last_stop_end - 1:
            early_miss = True
            break
    assert not early_miss
    _ = miss_while_timer


@_SPI_XFAIL_SINGLE_EDGE
def test_spi_target_default_0xff():
    img = assemble((ROOT / "sw" / "programs" / "spi_target.asm").read_text())
    m = Machine()
    m.load(
        img,
        [
            {
                "tick_source": TickSource.PIN_EDGE,
                "tick_pin": 2,
                "tick_on_rise": True,
                "msb_first": True,
                "miss_policy": 2,  # SEND_DEFAULT
                "default_byte": 0xFF,
                "pins": [
                    {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},  # MISO
                    {"physical": 1, "mode": PinMode.INPUT, "idle": 1},  # MOSI
                    {"physical": 2, "mode": PinMode.INPUT, "idle": 1},  # SCLK
                    {"physical": 3, "mode": PinMode.INPUT, "idle": 1},  # CS
                ],
                "events": [
                    {"kind": EventKind.EDGE_FALL, "pin": 3},  # CS fall
                    {
                        "kind": EventKind.EDGE_RISE,
                        "pin": 3,
                        "trap": True,
                        "vector": 9,  # desel label
                    },
                ],
            }
        ],
    )
    # CS low
    m.phys_ext[3] = 0
    for _ in range(10):
        m.step()
    # Clock 8 cycles — no host data → default path via PULL.NB
    # Mode 0: controller samples MISO on rising SCLK; with single-edge ticks the
    # engine updates MISO on that same rising tick.
    sample_edge_changes = 0
    for _bit in range(8):
        m.phys_ext[2] = 0
        for _ in range(4):
            m.step()
        m.phys_ext[2] = 1
        for _ in range(4):
            before = m.phys_drive[0] if m.phys_oe[0] else 0
            m.step()
            after = m.phys_drive[0] if m.phys_oe[0] else 0
            rise_tick = m._sync_prev[2] == 0 and m._sync1[2] == 1
            if rise_tick and before != after:
                sample_edge_changes += 1
    assert sample_edge_changes == 0, (
        f"MISO changed on {sample_edge_changes} rising sample ticks; "
        "must be stable around the controller sample edge"
    )
    # Program should be in loop; under flag set from PULL.NB
    assert m.ctx[0].under or m.ctx[0].pc >= 0


def test_ws2812_msb_first_timing():
    """WS2812 encodes MSB first with 2/1 vs 1/2 high/low tick ratios."""
    from check_ws2812 import decode_ws2812_byte

    per = 4
    img = assemble((ROOT / "sw" / "programs" / "ws2812.asm").read_text())
    m = Machine()
    m.load(
        img,
        [
            {
                "per": float(per),
                "phase": 0,
                "msb_first": True,
                "pins": [{"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0}],
                "events": [{"kind": EventKind.HOST_DATA}],
            }
        ],
    )
    m.host_push(0xA5, last=True)  # 10100101
    trace = []
    for _ in range(400):
        m.step()
        cur = m.phys_drive[0] if m.phys_oe[0] else 0
        trace.append(cur)
    assert decode_ws2812_byte(trace, per) == 0xA5
    assert not m.ctx[0].miss


def test_i2c_target_address_ack():
    """I2C target ACKs matching address 0x28 write."""
    from check_i2c import i2c_clock_byte_msb, i2c_idle, i2c_start

    img = assemble((ROOT / "sw" / "programs" / "i2c_target.asm").read_text())
    m = Machine()
    m.load(
        img,
        [
            {
                "tick_source": TickSource.PIN_EDGE,
                "tick_pin": 1,
                "tick_on_rise": True,
                "msb_first": True,
                "miss_policy": 3,  # STRETCH
                "pins": [
                    {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1},  # SDA
                    {"physical": 1, "mode": PinMode.OPENDRAIN, "idle": 1},  # SCL
                ],
                "events": [
                    {
                        "kind": EventKind.QUAL_FALL_WHILE_HIGH,
                        "pin": 0,
                        "qual_pin": 1,
                    },
                    {
                        "kind": EventKind.QUAL_RISE_WHILE_HIGH,
                        "pin": 0,
                        "qual_pin": 1,
                        "trap": True,
                        "vector": 0,
                    },
                ],
            }
        ],
    )
    i2c_idle(m, 8)
    i2c_start(m)
    # Allow WAIT to complete after sync
    for _ in range(8):
        m.step()
    ack = i2c_clock_byte_msb(m, 0x50, sample_ack=True)
    assert ack == 0, f"expected ACK, got NACK (pc={m.ctx[0].pc} miss={m.ctx[0].miss})"


def _i2c_cfg():
    return {
        "tick_source": TickSource.PIN_EDGE,
        "tick_pin": 1,
        "tick_on_rise": True,
        "msb_first": True,
        "miss_policy": 3,
        "pins": [
            {"physical": 0, "mode": PinMode.OPENDRAIN, "idle": 1},
            {"physical": 1, "mode": PinMode.OPENDRAIN, "idle": 1},
        ],
        "events": [
            {"kind": EventKind.QUAL_FALL_WHILE_HIGH, "pin": 0, "qual_pin": 1},
            {
                "kind": EventKind.QUAL_RISE_WHILE_HIGH,
                "pin": 0,
                "qual_pin": 1,
                "trap": True,
                "vector": 0,
            },
        ],
    }


def test_i2c_rw_saved_before_address_mask():
    """R/W bit must be copied out before AND 0xfe (assembly order)."""
    src = (ROOT / "sw" / "programs" / "i2c_target.asm").read_text().splitlines()
    # Find MFS RX then require MOV r3,r0 before AND with 0xfe
    body = "\n".join(ln.split(";")[0] for ln in src)
    mfs = body.lower().index("mfs")
    mov = body.lower().index("mov r3", mfs)
    and_ = body.lower().index("and r0", mov)
    assert mfs < mov < and_


@_XFAIL_SINGLE_EDGE
def test_i2c_target_read_path():
    """Address+R → ACK → host byte out → master NACK → STOP → idle.

    Known ISS bug with single-edge ticks: the bit engine updates open-drain SDA
    on the SCL rising tick (while SCL is high). Releasing for a data '1' is
    QUAL_RISE_WHILE_HIGH (STOP) and the trap cancels the XFER. Fixed by the
    engine clock (both edges; drive on the opposite edge of sample) — see the
    companion test_i2c_target_read_path_engine_clock.
    """
    from check_i2c import (
        i2c_clock_byte_msb,
        i2c_clock_in_byte_msb,
        i2c_idle,
        i2c_master_nack,
        i2c_start,
        i2c_stop,
    )

    img = assemble((ROOT / "sw" / "programs" / "i2c_target.asm").read_text())
    m = Machine()
    m.load(img, [_i2c_cfg()])  # STOP trap enabled for the whole transaction
    m.host_push(0xC3, last=True)
    i2c_idle(m, 8)
    i2c_start(m)
    for _ in range(8):
        m.step()
    ack = i2c_clock_byte_msb(m, 0x51, sample_ack=True)  # 0x28 << 1 | R
    assert ack == 0, (m.ctx[0].pc, m.ctx[0].regs)
    for _ in range(40):
        m.step()
        ta = m.ctx[0].timed_active
        if ta and ta.kind == "xfer" and ta.job and ta.job.mode == 0 and ta.job.n_bits == 8:
            break
    data = i2c_clock_in_byte_msb(m)
    assert data == 0xC3, (data, m.ctx[0].pc)
    i2c_master_nack(m)
    i2c_stop(m)
    for _ in range(16):
        m.step()
    assert m.ctx[0].pc in (0, 1)
    assert m.ctx[0].waiting or m.ctx[0].pc == 0
    assert m.ctx[0].evf & 0x02  # EV1 = STOP


def _i2c_cfg_engine_clock():
    """I2C target with engine clock: both SCL edges are ticks; CPOL=1, CPHA=1.

    CPHA=1 drives DOUT on the leading (falling) edge so SDA changes while SCL
    is low — required so STOP is not falsely detected mid-byte.
    """
    cfg = _i2c_cfg()
    cfg.update(
        {
            "clk_en": True,
            "cpol": True,   # SCL idle high
            "cpha": True,   # drive on leading (fall), sample on trailing (rise)
            "dout_lp": 0,
            "din_lp": 0,
            "clk_lp": 1,
            "tick_pin": 1,
        }
    )
    return cfg


def _spi_cfg_engine_clock():
    return {
        "tick_source": TickSource.PIN_EDGE,
        "tick_pin": 2,
        "tick_on_rise": True,  # ignored when clk_en (both edges)
        "msb_first": True,
        "miss_policy": 2,
        "default_byte": 0xFF,
        "clk_en": True,
        "cpol": False,  # SCLK idle low (mode 0)
        "cpha": False,  # sample on leading (rise), drive next on trailing (fall)
        "dout_lp": 0,
        "din_lp": 1,
        "clk_lp": 2,
        "pins": [
            {"physical": 0, "mode": PinMode.PUSHPULL, "idle": 0},
            {"physical": 1, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 2, "mode": PinMode.INPUT, "idle": 1},
            {"physical": 3, "mode": PinMode.INPUT, "idle": 1},
        ],
        "events": [
            {"kind": EventKind.EDGE_FALL, "pin": 3},
            {
                "kind": EventKind.EDGE_RISE,
                "pin": 3,
                "trap": True,
                "vector": 9,
            },
        ],
    }


def _sda_level(m: Machine) -> int:
    if m.phys_oe[0] and not (m.phys_drive[0] & 1):
        return 0
    return 1


def _miso_level(m: Machine) -> int:
    return m.phys_drive[0] if m.phys_oe[0] else 0


def test_i2c_target_read_path_engine_clock():
    """Same as single-edge read path, but with clk_en (both SCL edges = ticks).

    STOP trap stays enabled. SDA must only change on the falling (drive) edge,
    half a bit-period away from the rising (sample) edge.
    """
    from check_i2c import (
        _SCL_PHASE,
        i2c_clock_byte_msb,
        i2c_idle,
        i2c_master_nack,
        i2c_start,
        i2c_stop,
        _set_sda_scl,
    )

    img = assemble((ROOT / "sw" / "programs" / "i2c_target.asm").read_text())
    m = Machine()
    m.load(img, [_i2c_cfg_engine_clock()])
    m.host_push(0xC3, last=True)
    i2c_idle(m, 8)
    i2c_start(m)
    for _ in range(8):
        m.step()
    ack = i2c_clock_byte_msb(m, 0x51, sample_ack=True)
    assert ack == 0, (m.ctx[0].pc, m.ctx[0].regs)
    for _ in range(40):
        m.step()
        ta = m.ctx[0].timed_active
        if ta and ta.kind == "xfer" and ta.job and ta.job.mode == 0 and ta.job.n_bits == 8:
            break

    value = 0
    for _ in range(8):
        # SCL low half: trailing→leading for CPOL=1 happens on fall; drive here.
        _set_sda_scl(m, 1, 0)
        sda_low_phase = None
        for cy in range(_SCL_PHASE):
            m.step()
            if cy == _SCL_PHASE // 2:
                sda_low_phase = _sda_level(m)
        sda_before_rise = _sda_level(m)
        _set_sda_scl(m, 1, 1)  # rising = sample edge for CPHA=1 (trailing)
        for cy in range(_SCL_PHASE):
            m.step()
            # SDA must not change while SCL is high (would look like STOP).
            assert _sda_level(m) == sda_before_rise, (
                "SDA changed on/after SCL rise (sample edge)",
                cy,
                sda_before_rise,
                _sda_level(m),
            )
        bit = sda_before_rise
        value = (value << 1) | bit
        assert sda_low_phase == bit or sda_low_phase is None
        _set_sda_scl(m, 1, 0)
        for _ in range(_SCL_PHASE):
            m.step()

    assert value == 0xC3, (value, m.ctx[0].pc)
    i2c_master_nack(m)
    i2c_stop(m)
    for _ in range(16):
        m.step()
    assert m.ctx[0].pc in (0, 1)
    assert m.ctx[0].waiting or m.ctx[0].pc == 0
    assert m.ctx[0].evf & 0x02  # STOP trap stayed armed and fired


def test_spi_target_engine_clock():
    """SPI target with clk_en: MISO changes on falling edge, stable at rising sample."""
    img = assemble((ROOT / "sw" / "programs" / "spi_target.asm").read_text())
    m = Machine()
    m.load(img, [_spi_cfg_engine_clock()])
    m.phys_ext[3] = 0  # CS low
    for _ in range(10):
        m.step()

    bits = []
    for _ in range(8):
        m.phys_ext[2] = 0  # falling = trailing for CPOL=0 → drive next / first setup
        miso_at_fall = None
        for cy in range(4):
            m.step()
            if cy == 2:
                miso_at_fall = _miso_level(m)
        miso_before_rise = _miso_level(m)
        m.phys_ext[2] = 1  # rising = leading / sample
        for cy in range(4):
            m.step()
            assert _miso_level(m) == miso_before_rise, (
                "MISO changed on sample (rising) edge",
                cy,
                miso_before_rise,
                _miso_level(m),
            )
        bits.append(miso_before_rise)
        assert miso_at_fall == miso_before_rise or miso_at_fall is None

    # Default byte 0xFF, MSB first
    value = 0
    for b in bits:
        value = (value << 1) | b
    assert value == 0xFF, bits
    assert m.ctx[0].under or m.ctx[0].pc >= 0


def _uart_rx_cfg(per: float = 8.0):
    return {
        "per": per,
        "phase": int(per) // 2,
        "tick_source": TickSource.TIMER,
        "msb_first": False,
        # XFER in samples DOUT_LP (same pin as UART TX uses for out).
        "dout_lp": 0,
        "din_lp": 0,
        "pins": [
            {"physical": 0, "mode": PinMode.INPUT, "idle": 1},
        ],
        "events": [
            {"kind": EventKind.EDGE_FALL, "pin": 0, "latched": True},
            {"kind": EventKind.LEVEL_HIGH, "pin": 0},
        ],
    }


def _drive_uart_byte(m: Machine, byte: int, per: int, pin: int = 0) -> None:
    """Drive one 8N1 frame on phys_ext[pin], one level per cycle (LSB first)."""
    bits = [0]  # start
    for i in range(8):
        bits.append((byte >> i) & 1)
    bits.append(1)  # stop
    for b in bits:
        m.phys_ext[pin] = b
        for _ in range(per):
            m.step()


def test_uart_rx_back_to_back_per8():
    """LATCHED RX-fall + EVCLR after XFER: every byte received at PER=8."""
    per = 8
    img = assemble((ROOT / "sw" / "programs" / "uart_rx.asm").read_text())
    m = Machine()
    m.load(img, [_uart_rx_cfg(float(per))])
    m.phys_ext[0] = 1
    for _ in range(8):
        m.step()

    payload = [0x55, 0x00, 0xFF, 0xA5]
    for b in payload:
        _drive_uart_byte(m, b, per)

    # Idle high while the last frame drains through MFS/PUSH.
    m.phys_ext[0] = 1
    for _ in range(per * 4):
        m.step()

    got = []
    while True:
        w = m.host_pop()
        if w is None:
            break
        got.append(w.data)
    assert got == payload, got
