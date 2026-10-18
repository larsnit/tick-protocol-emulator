/*
 * Copyright (c) 2026 Lars Nitschke
 * SPDX-License-Identifier: Apache-2.0
 *
 * Tiny Tapeout top: 4-pin SPI host link on ui/uo; protocol pins on uio[7:0].
 *
 *   ui[0] SCLK   ui[1] MOSI   ui[2] CS_n   ui[3..7] reserved (tie low)
 *   uo[0] MISO   uo[1] IRQ    uo[2] RUN    uo[3] ERR
 *   uo[4] MISS   uo[5] TICK   uo[6..7] reserved (0)
 *   uio[7:0] protocol only (always)
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
  wire        spi_run, soft_rst;
  wire        cfg_we, cfg_re;
  wire [7:0]  cfg_addr, cfg_wdata, cfg_rdata;
  wire        imem_we, imem_hreq;
  wire [5:0]  imem_waddr, imem_hraddr;
  wire [15:0] imem_wdata, imem_hrdata;
  wire        host_wr, host_rd, host_full, host_empty;
  wire [9:0]  host_wdata, host_rdata;
  wire [3:0]  host_tx_count, host_rx_count;
  wire        enable0, err_any;
  wire        miso, irq;
  wire [5:0]  dbg_pc;
  wire        dbg_waiting, dbg_miss, dbg_tick, dbg_timer_run;
  wire [1:0]  dbg_a_kind, dbg_p_kind;

  host_spi u_host (
      .clk(clk),
      .rst_n(rst_n),
      .sclk_i(ui_in[0]),
      .mosi_i(ui_in[1]),
      .cs_n_i(ui_in[2]),
      .miso_o(miso),
      .irq_o(irq),
      .run_o(spi_run),
      .soft_rst_o(soft_rst),
      .cfg_we(cfg_we),
      .cfg_re(cfg_re),
      .cfg_addr(cfg_addr),
      .cfg_wdata(cfg_wdata),
      .cfg_rdata(cfg_rdata),
      .imem_we(imem_we),
      .imem_waddr(imem_waddr),
      .imem_wdata(imem_wdata),
      .imem_hreq(imem_hreq),
      .imem_hraddr(imem_hraddr),
      .imem_hrdata(imem_hrdata),
      .host_wr(host_wr),
      .host_wdata(host_wdata),
      .host_full(host_full),
      .host_rd(host_rd),
      .host_rdata(host_rdata),
      .host_empty(host_empty),
      .host_tx_count(host_tx_count),
      .host_rx_count(host_rx_count),
      .enable0(enable0),
      .err_any(err_any)
  );

  wire [7:0] core_uio_out, core_uio_oe;

  tick_core core (
      .clk(clk),
      .rst_n(rst_n),
      .soft_rst(soft_rst),
      .imem_we(imem_we),
      .imem_waddr(imem_waddr),
      .imem_wdata(imem_wdata),
      .imem_hreq(imem_hreq),
      .imem_hraddr(imem_hraddr),
      .imem_hrdata(imem_hrdata),
      .host_wr(host_wr),
      .host_wdata(host_wdata),
      .host_full(host_full),
      .host_rd(host_rd),
      .host_rdata(host_rdata),
      .host_empty(host_empty),
      .host_tx_count(host_tx_count),
      .host_rx_count(host_rx_count),
      .enable0(enable0),
      .err_any(err_any),
      .run(spi_run),
      .cfg_we(cfg_we),
      .cfg_re(cfg_re),
      .cfg_addr(cfg_addr),
      .cfg_wdata(cfg_wdata),
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

  // Pads Hi-Z while !RUN (pins inputs). Queue still computes idle map_oe
  // combinationally so pin sync settles before run rise.
  assign uio_out = core_uio_out;
  assign uio_oe  = spi_run ? core_uio_oe : 8'h00;

  assign uo_out = {2'b00, dbg_tick, dbg_miss, err_any, spi_run, irq, miso};

  wire _unused = &{ena, ui_in[7:3], dbg_pc, dbg_waiting, dbg_timer_run,
                   dbg_a_kind, dbg_p_kind, 1'b0};
endmodule

`default_nettype wire
