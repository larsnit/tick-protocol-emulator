`default_nettype none

// Formal wrapper with free inputs. Queue invariant catches timed-queue ordering bugs.
module tick_formal_top (
    input wire        clk,
    input wire        rst_n,
    input wire        run,
    input wire        imem_we,
    input wire [5:0]  imem_waddr,
    input wire [15:0] imem_wdata,
    input wire        host_wr,
    input wire [9:0]  host_wdata,
    input wire        host_rd,
    input wire        pin0_in
);
  wire host_full, host_empty;
  wire [9:0] host_rdata;
  wire [5:0] dbg_pc;
  wire dbg_waiting, dbg_miss, dbg_tick, dbg_timer_run;
  wire [1:0] dbg_a_kind, dbg_p_kind;
  wire pin0_out, pin0_oe;

  // Constant integer PER = 8.0 cycles
  localparam [19:0] PER_FP = 20'd128;

  tick_core uut (
      .clk(clk),
      .rst_n(rst_n),
      .imem_we(imem_we),
      .imem_waddr(imem_waddr),
      .imem_wdata(imem_wdata),
      .host_wr(host_wr),
      .host_wdata(host_wdata),
      .host_full(host_full),
      .host_rd(host_rd),
      .host_rdata(host_rdata),
      .host_empty(host_empty),
      .run(run),
      .cfg_per_fp(PER_FP),
      .cfg_phase(16'd0),
      .cfg_msb_first(1'b0),
      .pin0_out(pin0_out),
      .pin0_oe(pin0_oe),
      .pin0_in(pin0_in),
      .dbg_pc(dbg_pc),
      .dbg_waiting(dbg_waiting),
      .dbg_miss(dbg_miss),
      .dbg_tick(dbg_tick),
      .dbg_timer_run(dbg_timer_run),
      .dbg_a_kind(dbg_a_kind),
      .dbg_p_kind(dbg_p_kind)
  );

  // Start in reset so anyinit cannot violate the invariant before rst.
  initial assume (!rst_n);

  reg saw_reset;
  initial saw_reset = 1'b0;
  always @(posedge clk) begin
    if (!rst_n)
      saw_reset <= 1'b1;
  end

  // Queue invariant: pending implies active occupied (pending ⇒ active).
  // Only after a completed reset edge so flops are known.
  always @(posedge clk) begin
    if (rst_n && saw_reset) begin
      if (dbg_p_kind != 2'b00)
        assert (dbg_a_kind != 2'b00);
    end
  end

  // Reset hygiene: one cycle after rst_n sampled low, state is clear.
  always @(posedge clk) begin
    if ($past(!rst_n) && saw_reset) begin
      assert (!dbg_miss);
      assert (dbg_a_kind == 2'b00);
      assert (dbg_p_kind == 2'b00);
    end
  end
endmodule

`default_nettype wire
