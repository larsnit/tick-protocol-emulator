; I2C target — address match then ACK; stretch on read
; EV0=START trap -> addr; EV1=STOP trap -> idle
; LP0=SDA OD, LP1=SCL OD; tick=SCL; miss=stretch

idle:  WAIT   ev0
addr:  XFER   8, in
       MFS    r0, RX
       LDI    r1, 0xfe
       ALU    AND r0, r1
       LDI    r1, 0x50
       ALU    CMP r0, r1
       JMP    NZ, nack
       ; ACK
       XFER   r2, 1, out
       ; r0 bit0 was R/W; if write, receive byte
       LDI    r1, 0x01
       ALU    AND r0, r1
       JMP    NZ, do_read
       XFER   8, in
       MFS    r0, RX
       PUSH   r0, DATA
       JMP    AL, idle
do_read:
       PULL.NB r0
       XFER   r0, 8, out
       JMP    AL, idle
nack:  ; release SDA (NACK = 1)
       LDI    r2, 0x01
       XFER   r2, 1, out
       JMP    AL, idle
