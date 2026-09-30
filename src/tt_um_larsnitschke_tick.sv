/*
 * Copyright (c) 2026 Lars Nitschke
 * SPDX-License-Identifier: Apache-2.0
 *
 * Tiny Tapeout top: host load/control on ui_in, protocol pin on uio[0].
 *
 * ui_in[0]     : host_wr pulse (level-sensitive one-cycle via edge in TB)
 * ui_in[1]     : host_rd
 * ui_in[2]     : imem_we
 * ui_in[3]     : run
 * ui_in[7:4]   : host/imem low nibble mux select (see below)
 * uo_out[0]    : host_full
 * uo_out[1]    : host_empty
 * uo_out[2]    : dbg_waiting
 * uo_out[3]    : dbg_miss
 * uo_out[4]    : dbg_tick
 * uo_out[5]    : pin0 mirror
 * uio[0]       : protocol LP0 (TX)
 *
 * Parallel load path (for cocotb / bring-up):
 *   Drive 16-bit imem word / 10-bit host word on uio[7:1]+spare via
 *   a shift register loaded from successive ui writes — see test helpers.
 *   Simpler: dedicated parallel bus through uio when run=0.
 */

`default_nettype none

module tt_um_larsnitschke_tick (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);
  wire run = ui_in[3];
  wire imem_we = ui_in[2] & ~run;
  wire host_wr = ui_in[0] & ~run;
  wire host_rd = ui_in[1];

  // When !run, uio_in carries load data:
  // imem: {uio_in[7:0], ui_in[7:4], 4'h0 mixed} — use latched wide registers.
  // Practical bring-up bus:
  //   wdata_lo = uio_in
  //   wdata_hi = previous latched nibble from ui[7:4] on prior cycle — TB drives
  //   imem_waddr = latched addr on uio when ui[7:4]==0xA pattern
  //
  // Simplified fixed mapping for tests:
  //   imem_wdata = {uio_in, uio_in} when loading? No — use 8-bit at a time with addr.

  reg [5:0]  load_addr;
  reg [15:0] load_word;
  reg [9:0]  host_word;
  reg        prev_wr, prev_imem;

  wire wr_pulse = host_wr & ~prev_wr;
  wire im_pulse = imem_we & ~prev_imem;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prev_wr <= 1'b0;
      prev_imem <= 1'b0;
      load_addr <= 6'd0;
      load_word <= 16'h0;
      host_word <= 10'h0;
    end else begin
      prev_wr <= host_wr;
      prev_imem <= imem_we;
      // uio_in[5:0] = addr when ui_in[7:4]==4'hA and rising imem_we setup
      if (!run && ui_in[7:4] == 4'hA)
        load_addr <= uio_in[5:0];
      if (!run && ui_in[7:4] == 4'hB)
        load_word[7:0] <= uio_in;
      if (!run && ui_in[7:4] == 4'hC)
        load_word[15:8] <= uio_in;
      if (!run && ui_in[7:4] == 4'hD)
        host_word[7:0] <= uio_in;
      if (!run && ui_in[7:4] == 4'hE)
        host_word[9:8] <= uio_in[1:0];
    end
  end

  wire        host_full, host_empty;
  wire [9:0]  host_rdata;
  wire [5:0]  dbg_pc;
  wire        dbg_waiting, dbg_miss, dbg_tick;
  wire        pin0_out, pin0_oe;

  // Default PER = 8.0 → 8*16 = 128
  tick_core core (
      .clk(clk),
      .rst_n(rst_n),
      .imem_we(im_pulse),
      .imem_waddr(load_addr),
      .imem_wdata(load_word),
      .host_wr(wr_pulse),
      .host_wdata(host_word),
      .host_full(host_full),
      .host_rd(host_rd),
      .host_rdata(host_rdata),
      .host_empty(host_empty),
      .run(run),
      .cfg_per_fp(20'd128),
      .cfg_phase(16'd0),
      .cfg_msb_first(1'b0),
      .pin0_out(pin0_out),
      .pin0_oe(pin0_oe),
      .pin0_in(uio_in[0]),
      .dbg_pc(dbg_pc),
      .dbg_waiting(dbg_waiting),
      .dbg_miss(dbg_miss),
      .dbg_tick(dbg_tick),
      .dbg_timer_run(),
      .dbg_a_kind(),
      .dbg_p_kind()
  );

  assign uo_out = {1'b0, pin0_out, dbg_tick, dbg_miss, dbg_waiting, host_empty, host_full, host_rdata[0]};
  assign uio_out = {7'b0, pin0_out};
  assign uio_oe  = {7'b0, pin0_oe};

  wire _unused = &{ena, dbg_pc, host_rdata[9:1], 1'b0};

endmodule

`default_nettype wire
