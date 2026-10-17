`default_nettype none

// host_fifo — synchronous FIFO for host↔core words.
// clk/rst_n: clock and active-low reset.
// wr/wdata: push when wr && !full (or wr&&rd when full — same-cycle replace).
// rd: pop when rd && !empty; rdata is combinational mem[rptr].
// full/empty: occupancy flags.
// Implements ISA §2 host FIFOs (10-bit words: data + LAST + CMD).
//
// Occupancy uses an explicit count so DEPTH entries are usable. A pointer-only
// "full = (wptr+1==rptr)" scheme only stores DEPTH-1 words and desynced ISS
// (HOST_FIFO_DEPTH=8) on the 8th PUSH.
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
  localparam integer CW = AW + 1;

  reg [WIDTH-1:0] mem_q [0:DEPTH-1];
  reg [AW-1:0]    wptr_q, rptr_q;
  reg [AW-1:0]    wptr_d, rptr_d;
  reg [CW-1:0]    count_q, count_d;
  reg             do_wr, do_rd;

  assign full  = (count_q == CW'(DEPTH));
  assign empty = (count_q == {CW{1'b0}});
  assign rdata = mem_q[rptr_q];

  always @(*) begin
    // Same-cycle wr+rd when full keeps occupancy at DEPTH (ISS list append/pop).
    do_rd = rd && !empty;
    do_wr = wr && (!full || do_rd);
    wptr_d  = wptr_q;
    rptr_d  = rptr_q;
    count_d = count_q;
    if (do_wr)
      wptr_d = wptr_q + AW'(1);
    if (do_rd)
      rptr_d = rptr_q + AW'(1);
    case ({do_wr, do_rd})
      2'b10: count_d = count_q + CW'(1);
      2'b01: count_d = count_q - CW'(1);
      default: count_d = count_q;
    endcase
  end

  always @(posedge clk or negedge rst_n) begin : seq_fifo
    if (!rst_n) begin
      wptr_q  <= {AW{1'b0}};
      rptr_q  <= {AW{1'b0}};
      count_q <= {CW{1'b0}};
      for (int i = 0; i < DEPTH; i = i + 1)
        mem_q[i] <= {WIDTH{1'b0}};
    end else begin
      if (do_wr)
        mem_q[wptr_q] <= wdata;
      wptr_q  <= wptr_d;
      rptr_q  <= rptr_d;
      count_q <= count_d;
    end
  end
endmodule

`default_nettype wire
