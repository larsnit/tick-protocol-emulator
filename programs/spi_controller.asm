; SPI controller mode 0 — one transaction of N bytes from host
; LP0=MOSI, LP1=MISO, LP2=SCLK, LP3=CS
; tick=timer; EV0=host data

idle:  WAIT   ev0
       SET    cs=0
next:  PULL   r0
       XFER   r0, 8, both
       MFS    r1, RX
       PUSH   r1, DATA
       JMP    HE, end
       JMP    AL, next
end:   WAIT   tick, stop
       SET    cs=1
       JMP    AL, idle
