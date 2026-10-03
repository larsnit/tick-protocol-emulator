; WS2812 — send one GRB byte from host (MSB first)
; LP0 = data out push-pull idle 0; PER = T0H time unit
; bit0 = 1 high + 2 low; bit1 = 2 high + 1 low (in tick units)

idle:  WAIT  ev0
       PULL  r0
       LDI   r1, 8
bit:   ALU   ADD r0, r0
       JMP   C, one
       SET.T tx=1
       SET.T tx=0
       SET.T tx=0
       JMP   next
one:   SET.T tx=1
       SET.T tx=1
       SET.T tx=0
next:  JMP   r1--, bit
       ; ≥50 µs latch left to the host (timer stop / idle)
       WAIT  tick, stop
       JMP   idle
