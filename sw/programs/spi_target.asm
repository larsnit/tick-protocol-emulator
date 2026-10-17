; SPI target mode 0 — isa-v0.1-draft §4.3
; tick=SCLK; EV0=CS fall; EV1=CS rise trap -> desel
; empty FIFO policy: send 0xFF

idle:  WAIT    ev0, idle       ; stop timer so SCLK while deselected is not MISS
       SET.E   miso=on
       PULL.NB r0
       XFER    r0, 8, both
loop:  PULL.NB r0
       XFER    r0, 8, both
       MFS     r1, RX
       PUSH    r1, DATA
       JMP     AL, loop
desel: SET.E   miso=off
       PUSH    r1, EOF
       JMP     AL, idle
