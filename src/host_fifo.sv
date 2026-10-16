`default_nettype none

// host_fifo — synchronous FIFO for host↔core words.
// clk/rst_n: clock and active-low reset.
// wr/wdata: push when wr && !full.
// rd: pop when rd && !empty; rdata is combinational mem[rptr].
// full/empty: occupancy flags.
// Implements ISA §2 host FIFOs (10-bit words: data + LAST + CMD).
module host_fifo #(
    parameter integer DEPTH = 8,
    parameter integer WIDTH = 10
) (
    input  wire             clk,
    input  wire             rst_n,
    input  wire             wr,
    input  wire [WIDTH-1:0] wdata,
    output wire             full,
    input  wire             rd,
    output wire [WIDTH-1:0] rdata,
    output wire             empty
);
  localparam integer AW = $clog2(DEPTH);

  reg [WIDTH-1:0] mem_q [0:DEPTH-1];
  reg [AW-1:0]    wptr_q, rptr_q;
  reg [AW-1:0]    wptr_d, rptr_d;

  assign full  = ((wptr_q + {{(AW-1){1'b0}}, 1'b1}) == rptr_q);
  assign empty = (wptr_q == rptr_q);
  assign rdata = mem_q[rptr_q];

  always @(*) begin
    wptr_d = wptr_q;
    rptr_d = rptr_q;
    if (wr && !full)
      wptr_d = wptr_q + {{(AW-1){1'b0}}, 1'b1};
    if (rd && !empty)
      rptr_d = rptr_q + {{(AW-1){1'b0}}, 1'b1};
  end

  always @(posedge clk or negedge rst_n) begin : seq_fifo
    if (!rst_n) begin
      wptr_q <= {AW{1'b0}};
      rptr_q <= {AW{1'b0}};
      for (int i = 0; i < DEPTH; i = i + 1)
        mem_q[i] <= {WIDTH{1'b0}};
    end else begin
      if (wr && !full)
        mem_q[wptr_q] <= wdata;
      wptr_q <= wptr_d;
      rptr_q <= rptr_d;
    end
  end
endmodule

`default_nettype wire
