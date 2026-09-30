`default_nettype none

// Formal wrapper. Strong MISS/tick properties are proven on the ISS
// (model/test_isa.py). This file checks reset hygiene and is a hook for
// deeper RTL proofs as the core grows.
module tick_formal_top (
    input wire clk,
    input wire rst_n
);
  wire host_full, host_empty;
  wire [9:0] host_rdata;
  wire [5:0] dbg_pc;
  wire dbg_waiting, dbg_miss, dbg_tick, dbg_timer_run;
  wire [1:0] dbg_a_kind;
  wire pin0_out, pin0_oe;

  tick_core uut (
      .clk(clk),
      .rst_n(rst_n),
      .imem_we(1'b0),
      .imem_waddr(6'h0),
      .imem_wdata(16'h0),
      .host_wr(1'b0),
      .host_wdata(10'h0),
      .host_full(host_full),
      .host_rd(1'b0),
      .host_rdata(host_rdata),
      .host_empty(host_empty),
      .run(1'b0),
      .cfg_per_fp(20'd128),
      .cfg_phase(16'd0),
      .cfg_msb_first(1'b0),
      .pin0_out(pin0_out),
      .pin0_oe(pin0_oe),
      .pin0_in(1'b1),
      .dbg_pc(dbg_pc),
      .dbg_waiting(dbg_waiting),
      .dbg_miss(dbg_miss),
      .dbg_tick(dbg_tick),
      .dbg_timer_run(dbg_timer_run),
      .dbg_a_kind(dbg_a_kind)
  );

  // While held in reset, sticky miss is clear and the engine is empty.
  always @(posedge clk) begin
    if (!rst_n) begin
      assert (!dbg_miss);
      assert (dbg_a_kind == 2'b00);
      assert (!dbg_timer_run);
    end
  end
endmodule

`default_nettype wire
