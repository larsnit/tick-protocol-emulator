`default_nettype none

// Formal harness for host_spi (docs/isa.md Host link):
//   1. IMEM_WRITE never asserts imem_we while still in the HI phase
//   2. host_wr never fires while host_full; a dropped push sets
//      LINKERR.OVERFLOW, which stays set until cleared by W1C
//   3. host_rd only for PULL after the DATA byte
module host_link_formal_top (
    input wire clk,
    input wire rst_n,
    input wire sclk_i,
    input wire mosi_i,
    input wire cs_n_i,
    input wire enable0,
    input wire err_any,
    input wire host_full,
    input wire host_empty,
    input wire [3:0] host_tx_count,
    input wire [3:0] host_rx_count,
    input wire [9:0] host_rdata,
    input wire [7:0] cfg_rdata,
    input wire [15:0] imem_hrdata
);
  wire miso, irq, run, soft_rst;
  wire cfg_we, cfg_re;
  wire [7:0] cfg_addr, cfg_wdata;
  wire imem_we, imem_hreq;
  wire [5:0] imem_waddr, imem_hraddr;
  wire [15:0] imem_wdata;
  wire host_wr, host_rd;
  wire [9:0] host_wdata;

  wire [3:0] f_linkerr;
  wire       f_imem_hi_phase, f_pull_want_data, f_push_dropped, f_w1c_overflow;
  wire [7:0] f_cmd_q;

  host_spi uut (
      .clk(clk),
      .rst_n(rst_n),
      .sclk_i(sclk_i),
      .mosi_i(mosi_i),
      .cs_n_i(cs_n_i),
      .miso_o(miso),
      .irq_o(irq),
      .run_o(run),
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
      .err_any(err_any),
      .f_linkerr(f_linkerr),
      .f_imem_hi_phase(f_imem_hi_phase),
      .f_pull_want_data(f_pull_want_data),
      .f_cmd_q(f_cmd_q),
      .f_push_dropped(f_push_dropped),
      .f_w1c_overflow(f_w1c_overflow)
  );

  initial assume (!rst_n);

  reg [1:0] rst_seen;
  initial rst_seen = 2'b00;
  always @(posedge clk) begin
    if (!rst_n) rst_seen <= 2'b01;
    else if (rst_seen == 2'b01) rst_seen <= 2'b11;
  end
  wire alive = rst_n && (rst_seen == 2'b11);

  wire overflow = f_linkerr[1];

  always @(posedge clk) begin
    if (alive) begin
      // 1) Never write a half-word: imem_we only after LO
      if (imem_we)
        assert ($past(f_imem_hi_phase));
      if (imem_we)
        assert (!f_imem_hi_phase);

      // 2a) Push issued only while !full
      if (host_wr)
        assert (!$past(host_full));

      // 2b) Dropped push sets OVERFLOW this cycle
      if (f_push_dropped)
        assert (overflow);

      // 2c) OVERFLOW sticky until W1C
      if ($past(overflow) && !overflow)
        assert (f_w1c_overflow);

      // 3) PULL consume only after DATA byte was in progress
      if (host_rd) begin
        assert ($past(f_cmd_q) == 8'h20);
        assert ($past(f_pull_want_data));
      end
    end
  end

  wire _unused = &{miso, irq, run, soft_rst, cfg_we, cfg_re, cfg_addr, cfg_wdata,
                   imem_waddr, imem_wdata, imem_hraddr, imem_hreq, host_wdata, enable0};
endmodule

`default_nettype wire
