; UART TX 8N1 — isa-v0.1-draft §4.1
; Setup: LP0=TX push-pull idle 1; engine DOUT=LP0 LSB first; tick=timer;
; EV0 = host data available

idle:  WAIT   ev0
       PULL   r0
frame: SET.T  tx=0
       XFER   r0, 8, out
       SET.T  tx=1
       JMP    HE, done
       PULL   r0
       JMP    AL, frame
done:  WAIT   tick, stop
       JMP    AL, idle
