; WS2812 — send one GRB byte from host (generality check)
; LP0 = data out; PER set by host for T0H; stretch timing via SET.T gaps

idle:  WAIT  ev0
       PULL  r0
       ; bit loop using r1 as count
       LDI   r1, 8
bit:   SET.T tx=1
       ; high time: short = 0, long = 1 — branch on MSB
       ALU   MOV r2, r0
       ALU   SHR r0, r0
       JMP   C, one
       SET.T tx=0
       JMP   next
one:   ALU   MOV r2, r2
       ALU   MOV r2, r2
       SET.T tx=0
next:  JMP   r1--, bit
       JMP   idle
