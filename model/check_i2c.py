"""I2C target helpers: clock an address byte on SCL/SDA and sample ACK."""

from __future__ import annotations

from model.machine import Machine


def _set_sda_scl(m: Machine, sda: int, scl: int) -> None:
    m.phys_ext[0] = sda
    m.phys_ext[1] = scl


def i2c_idle(m: Machine, cycles: int = 4) -> None:
    _set_sda_scl(m, 1, 1)
    for _ in range(cycles):
        m.step()


def i2c_start(m: Machine) -> None:
    """SDA falls while SCL high."""
    _set_sda_scl(m, 1, 1)
    m.step()
    _set_sda_scl(m, 0, 1)
    for _ in range(4):
        m.step()


def i2c_stop(m: Machine) -> None:
    """SDA rises while SCL high."""
    _set_sda_scl(m, 0, 1)
    for _ in range(2):
        m.step()
    _set_sda_scl(m, 1, 1)
    for _ in range(4):
        m.step()


def i2c_clock_byte_msb(m: Machine, data: int, sample_ack: bool = True) -> int | None:
    """Drive 8 data bits MSB first; each bit: SDA setup, SCL rise (tick), SCL fall.
    Returns sampled ACK (0=ACK) if sample_ack else None.
    """
    for bi in range(7, -1, -1):
        bit = (data >> bi) & 1
        _set_sda_scl(m, bit, 0)
        for _ in range(2):
            m.step()
        _set_sda_scl(m, bit, 1)  # rising SCL = tick
        for _ in range(2):
            m.step()
        _set_sda_scl(m, bit, 0)
        for _ in range(2):
            m.step()
    if not sample_ack:
        return None
    # Let the program compare + post the 1-bit ACK XFER.
    for _ in range(32):
        m.step()
        ta = m.ctx[0].timed_active
        if ta is not None and ta.kind == "xfer" and ta.job and ta.job.n_bits == 1:
            break
    _set_sda_scl(m, 1, 0)
    for _ in range(2):
        m.step()
    _set_sda_scl(m, 1, 1)
    for _ in range(3):
        m.step()
    if m.phys_oe[0] and not (m.phys_drive[0] & 1):
        ack = 0
    else:
        ack = 1
    _set_sda_scl(m, 1, 0)
    for _ in range(2):
        m.step()
    return ack


def i2c_clock_in_byte_msb(m: Machine) -> int:
    """Release SDA; sample 8 bits MSB-first on SCL rises (target driving)."""
    value = 0
    for _ in range(8):
        _set_sda_scl(m, 1, 0)
        for _ in range(2):
            m.step()
        _set_sda_scl(m, 1, 1)
        for _ in range(2):
            m.step()
        if m.phys_oe[0] and not (m.phys_drive[0] & 1):
            bit = 0
        else:
            bit = 1
        value = (value << 1) | bit
        _set_sda_scl(m, 1, 0)
        for _ in range(2):
            m.step()
    return value


def i2c_master_nack(m: Machine) -> None:
    """9th bit: master holds SDA high (NACK)."""
    _set_sda_scl(m, 1, 0)
    for _ in range(2):
        m.step()
    _set_sda_scl(m, 1, 1)
    for _ in range(2):
        m.step()
    _set_sda_scl(m, 1, 0)
    for _ in range(2):
        m.step()
