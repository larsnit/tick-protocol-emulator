; UART RX 8N1 — docs/isa.md §5.2
; LP0=RX input; engine DIN=LP0 LSB first; EV0=RX fall (LATCHED); EV1=RX high
; PHASE = PER/2. Clear EV0 pending after each XFER so back-to-back frames
; at short PER are not lost, and a stale one is not reused.

start: WAIT   ev0, rearm
       IN.T   rx
       JMP    C, start
       XFER   9, in
       LDI    r1, 0x01
       MTS    EVCLR, r1
       MFS    r0, RX
       JMP    NC, ferr
       PUSH   r0, DATA
       JMP    AL, start
ferr:  PUSH   r0, ERR
       WAIT   ev1, idle
       JMP    AL, start
