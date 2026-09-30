; I2C target — address match then ACK; stretch on read
; EV0=START (qual SDA fall while SCL high); EV1=STOP trap → idle
; LP0=SDA OD, LP1=SCL OD; tick=SCL rise; miss=stretch; MSB first
; 7-bit address 0x28 → expect address byte 0x50 (write) / 0x51 (read)

idle:  WAIT   ev0
addr:  XFER   8, in
       MFS    r0, RX
       ALU    MOV r3, r0
       LDI    r1, 0xfe
       ALU    AND r0, r1
       LDI    r1, 0x50
       ALU    CMP r0, r1
       JMP    NZ, nack
       ; ACK: drive SDA low for one SCL tick
       LDI    r2, 0x00
       XFER   r2, 1, out
       ; R/W was LSB of address byte
       ALU    MOV r0, r3
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
nack:  LDI    r2, 0x01
       XFER   r2, 1, out
       JMP    AL, idle
