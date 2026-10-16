/*
 * Copyright (c) 2026 Lars Nitschke
 * SPDX-License-Identifier: Apache-2.0
 *
 * Tiny Tapeout top: host load/control on ui_in, protocol pins on uio[7:0].
 *
 * Pinout (parallel bring-up; host SPI shim deferred):
 *   ui_in[0]     : host_wr
 *   ui_in[1]     : host_rd
 *   ui_in[2]     : imem_we
 *   ui_in[3]     : run
 *   ui_in[7:4]   : load mux select
 *   uo_out       : while !run = cfg readback latch; while run = status
 *   uio[7:0]     : 8 protocol pins (logical pins mapped via config)
 *
 * Parallel cfg nibbles (docs/isa.md): 0x9 CFG_ADDR, 0xF CFG_WR, 0x8 CFG_RD.
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
  wire [3:0] nibble = ui_in[7:4];

  reg [5:0]  load_addr;
  reg [15:0] load_word;
  reg [9:0]  host_word;
  reg        prev_wr, prev_imem;
  reg        prev_f, prev_8;
  reg [7:0]  cfg_addr_latch;
  reg [7:0]  cfg_rdata_latch;
  reg        cfg_re_d;

  wire wr_pulse = host_wr & ~prev_wr;
  wire im_pulse = imem_we & ~prev_imem;
  wire cfg_wr_pulse = (!run) & (nibble == 4'hF) & ~prev_f;
  wire cfg_re_pulse = (!run) & (nibble == 4'h8) & ~prev_8;

  wire [7:0] cfg_rdata;
  wire [7:0] core_uio_out, core_uio_oe;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      prev_wr <= 1'b0;
      prev_imem <= 1'b0;
      prev_f <= 1'b0;
      prev_8 <= 1'b0;
      load_addr <= 6'd0;
      load_word <= 16'h0;
      host_word <= 10'h0;
      cfg_addr_latch <= 8'h00;
      cfg_rdata_latch <= 8'h00;
      cfg_re_d <= 1'b0;
    end else begin
      prev_wr <= host_wr;
      prev_imem <= imem_we;
      prev_f <= (!run) & (nibble == 4'hF);
      prev_8 <= (!run) & (nibble == 4'h8);
      cfg_re_d <= cfg_re_pulse;
      if (cfg_re_d)
        cfg_rdata_latch <= cfg_rdata;

      if (!run && nibble == 4'hA)
        load_addr <= uio_in[5:0];
      if (!run && nibble == 4'hB)
        load_word[7:0] <= uio_in;
      if (!run && nibble == 4'hC)
        load_word[15:8] <= uio_in;
      if (!run && nibble == 4'hD)
        host_word[7:0] <= uio_in;
      if (!run && nibble == 4'hE)
        host_word[9:8] <= uio_in[1:0];
      if (!run && nibble == 4'h9)
        cfg_addr_latch <= uio_in;
      if (cfg_wr_pulse)
        cfg_addr_latch <= cfg_addr_latch + 8'd1;
    end
  end

  wire        host_full, host_empty;
  wire [9:0]  host_rdata;
  wire [5:0]  dbg_pc;
  wire        dbg_waiting, dbg_miss, dbg_tick;
  wire        dbg_timer_run;
  wire [1:0]  dbg_a_kind, dbg_p_kind;

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
      .cfg_we(cfg_wr_pulse),
      .cfg_re(cfg_re_pulse),
      .cfg_addr(cfg_addr_latch),
      .cfg_wdata(uio_in),
      .cfg_rdata(cfg_rdata),
      .uio_in(uio_in),
      .uio_out(core_uio_out),
      .uio_oe(core_uio_oe),
      .dbg_pc(dbg_pc),
      .dbg_waiting(dbg_waiting),
      .dbg_miss(dbg_miss),
      .dbg_tick(dbg_tick),
      .dbg_timer_run(dbg_timer_run),
      .dbg_a_kind(dbg_a_kind),
      .dbg_p_kind(dbg_p_kind)
  );

  // !run: full-byte cfg readback. run: status (pin0 mirror on bit6).
  assign uo_out = run
      ? {1'b0, core_uio_out[0], dbg_tick, dbg_miss, dbg_waiting, host_empty, host_full, host_rdata[0]}
      : cfg_rdata_latch;

  assign uio_out = core_uio_out;
  assign uio_oe  = run ? core_uio_oe : 8'h00;

  wire _unused = &{ena, dbg_pc, host_rdata[9:1], dbg_timer_run, dbg_a_kind, dbg_p_kind, 1'b0};
endmodule

`default_nettype wire
