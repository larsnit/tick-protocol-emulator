; I2C controller — write one byte to 7-bit address (simplified)
; LP0=SDA open-drain, LP1=SCL open-drain
; START/STOP via SET with timer idle; data via XFER both

       ; START: SDA high, SCL high, then SDA low
start: SET    sda=1
       SET    scl=1
       SET    sda=0
       SET    scl=0
       ; address << 1 | 0 (write) in r0 from host
       WAIT   ev0
       PULL   r0
       XFER   r0, 8, both
       ; ACK bit: release SDA, pulse via 1-bit in
       XFER   1, in
       MFS    r1, RX
       JMP    C, nak
       PULL   r0
       XFER   r0, 8, both
       XFER   1, in
nak:   ; STOP: SDA low, SCL high, SDA high
       SET    sda=0
       SET    scl=1
       SET    sda=1
       JMP    AL, start
