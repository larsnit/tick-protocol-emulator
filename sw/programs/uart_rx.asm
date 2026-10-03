; UART RX 8N1 — isa-v0.1-draft §4.2
; LP0=RX input; engine DIN=LP0 LSB first; EV0=RX fall; EV1=RX high
; PHASE = PER/2

start: WAIT   ev0, rearm
       IN.T   rx
       JMP    C, start
       XFER   9, in
       MFS    r0, RX
       JMP    NC, ferr
       PUSH   r0, DATA
       JMP    AL, start
ferr:  PUSH   r0, ERR
       WAIT   ev1, idle
       JMP    AL, start
