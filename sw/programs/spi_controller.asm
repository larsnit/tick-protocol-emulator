; SPI controller mode 0 — engine clock (docs/isa.md §4, §5.3 companion)
; LP0=MOSI, LP1=MISO, LP2=SCLK, LP3=CS
; Setup: CLK_EN=1, CPOL=0, CPHA=0, DOUT=LP0, DIN=LP1, CLK=LP2
; tick=timer; PER = half bit period; EV0=host data
; First MOSI bit is driven when XFER is posted (CPHA=0).

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
