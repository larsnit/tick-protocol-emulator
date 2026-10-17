; Host command dispatch via MTS PC (Stage 2b milestone).
; Command byte = absolute PC of handler. Handlers: ALU add, XFER out, PUSH result.
; Setup: LP0 push-pull DOUT; LP2 status; EV0 = host data; timer ticks.

idle:  WAIT   ev0
       PULL   r0
       MTS    PC, r0

; pad so handlers sit at known PCs (assembler fills labels)
hang:  JMP    AL, hang

; PC = h_add (add r1+=r2, push)
h_add: PULL   r1
       PULL   r2
       ALU    ADD r1, r2
       PUSH   r1, DATA
       JMP    AL, idle

; PC = h_xfer (XFER out r1, 8 bits)
h_xfer: PULL  r1
        XFER  r1, 8, out
        JMP   AL, idle

; PC = h_ping (SET lp2=1 then clear)
h_ping: SET   lp2=1
        SET   lp2=0
        JMP   AL, idle
