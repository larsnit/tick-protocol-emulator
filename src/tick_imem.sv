`default_nettype none

// tick_imem — 64×16 instruction memory, sync write, single async read.
// Host IMEM_READ shares the fetch port (only legal while ctx0 disabled).
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

  assign rdata = mem[raddr];

  always @(posedge clk or negedge rst_n) begin : seq_imem
    if (!rst_n) begin
      for (int i = 0; i < 64; i = i + 1)
        mem[i] <= 16'h0;
    end else if (we) begin
      mem[waddr] <= wdata;
    end
  end
endmodule

`default_nettype wire
