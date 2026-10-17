; I2C controller — write one byte (engine clock; no SCL-release wait)
; LP0=SDA open-drain, LP1=SCL open-drain
; Setup: CLK_EN=1, CPOL=1 (SCL idle high), CPHA=1, DOUT=DIN=LP0, CLK=LP1
; tick=timer; PER = half SCL period; EV0=host data
; START/STOP are SET.T on the timer (docs §4). Stretch wait deferred.

idle:  WAIT   ev0
       PULL   r0                 ; address<<1 | W from host
       ; START: SDA/SCL high → SDA low → SCL low
       SET.T  sda=1
       SET.T  scl=1
       SET.T  sda=0
       SET.T  scl=0
       XFER   r0, 8, both
       XFER   1, in              ; ACK bit
       MFS    r1, RX
       ALU    MOV r1, r1         ; Z := (ACK==0)
       JMP    NZ, nak            ; SDA high during ACK = NAK
       PULL   r0                 ; data byte
       XFER   r0, 8, both
       XFER   1, in
nak:   ; STOP: SDA low, SCL high, SDA high
       SET.T  sda=0
       SET.T  scl=1
       SET.T  sda=1
       WAIT   tick, stop
       JMP    AL, idle
