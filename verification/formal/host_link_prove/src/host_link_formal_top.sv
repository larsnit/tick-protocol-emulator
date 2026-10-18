`default_nettype none

// Formal harness for host_spi link properties (docs/isa.md):
//   1. aborted IMEM_WRITE never writes a half-word
//   2. a dropped push never writes the FIFO (OVERFLOW on both RTL drop sites;
//      sticky bit vs W1C covered by directed cocotb tests)
//   3. PULL consumes an entry only after both bytes
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
  wire imem_we;
  wire [5:0] imem_waddr, imem_hraddr;
  wire [15:0] imem_wdata;
  wire host_wr, host_rd;
  wire [9:0] host_wdata;

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

  initial assume (!rst_n);

  reg saw_reset;
  initial saw_reset = 1'b0;
  always @(posedge clk) begin
    if (!rst_n) saw_reset <= 1'b1;
  end

  wire unit_open      = uut.unit_open;
  wire imem_hi_phase  = uut.imem_hi_phase;
  wire [7:0] cmd_q    = uut.cmd_q;
  wire pull_want_data = uut.pull_want_data;
  wire cs_rise        = uut.cs_rise;

  always @(posedge clk) begin
    if (rst_n && saw_reset) begin
      // 1) Aborted IMEM_WRITE never commits a half-word write
      if (cs_rise && unit_open && cmd_q == 8'h03 && imem_hi_phase)
        assert (!imem_we);
      // IMEM write pulse was issued only while !enable0 (sample decision cycle)
      if (imem_we)
        assert (!$past(enable0));

      // 2) Dropped push never writes
      if (host_wr)
        assert (!host_full);

      // 3) PULL consumes an entry only after both bytes
      if (host_rd) begin
        assert ($past(cmd_q) == 8'h20);
        assert ($past(pull_want_data));
      end
    end
  end

  wire _unused = &{miso, irq, run, soft_rst, cfg_we, cfg_re, cfg_addr, cfg_wdata,
                   imem_waddr, imem_wdata, imem_hraddr, host_wdata};
endmodule

`default_nettype wire
