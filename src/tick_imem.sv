`default_nettype none

// tick_imem — 64×16 instruction memory with sync write, async read.
// Ports: we/waddr/wdata (write), raddr/rdata (combinational read).
// Implements ISA §2 shared instruction memory.
module tick_imem (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        we,
    input  wire [5:0]  waddr,
    input  wire [15:0] wdata,
    input  wire [5:0]  raddr,
    output wire [15:0] rdata
);
  reg [15:0] mem[0:63];
  integer    ii;

  assign rdata = mem[raddr];

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      for (ii = 0; ii < 64; ii = ii + 1)
        mem[ii] <= 16'h0;
    end else if (we) begin
      mem[waddr] <= wdata;
    end
  end
endmodule

`default_nettype wire
