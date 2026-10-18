`default_nettype none

// Formal wrapper: queue invariant + host-link properties.
module tick_formal_top (
    input wire        clk,
    input wire        rst_n,
    input wire        run,
    input wire        soft_rst,
    input wire        imem_we,
    input wire [5:0]  imem_waddr,
    input wire [15:0] imem_wdata,
    input wire        host_wr,
    input wire [9:0]  host_wdata,
    input wire        host_rd,
    input wire [7:0]  uio_in
);
  wire host_full, host_empty, enable0, err_any;
  wire [9:0] host_rdata;
  wire [3:0] host_tx_count, host_rx_count;
  wire [15:0] imem_hrdata;
  wire [5:0] dbg_pc;
  wire dbg_waiting, dbg_miss, dbg_tick, dbg_timer_run;
  wire [1:0] dbg_a_kind, dbg_p_kind;
  wire [7:0] uio_out, uio_oe;
  wire [7:0] cfg_rdata;

  reg        cfg_we, cfg_re;
  reg [7:0]  cfg_addr, cfg_wdata;
  reg [3:0]  init_cnt;
  reg        init_done;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      init_cnt  <= 4'd0;
      init_done <= 1'b0;
      cfg_we    <= 1'b0;
      cfg_re    <= 1'b0;
      cfg_addr  <= 8'h00;
      cfg_wdata <= 8'h00;
    end else begin
      cfg_we <= 1'b0;
      cfg_re <= 1'b0;
      if (!init_done) begin
        init_cnt <= init_cnt + 4'd1;
        case (init_cnt)
          4'd1: begin cfg_we <= 1'b1; cfg_addr <= 8'h12; cfg_wdata <= 8'h01; end
          4'd2: begin cfg_we <= 1'b1; cfg_addr <= 8'h19; cfg_wdata <= 8'h80; end
          4'd3: begin cfg_we <= 1'b1; cfg_addr <= 8'h00; cfg_wdata <= 8'h01; end
          4'd4: init_done <= 1'b1;
          default: ;
        endcase
      end
    end
  end

  wire run_g = run & init_done;

  tick_core uut (
      .clk(clk),
      .rst_n(rst_n),
      .soft_rst(soft_rst & init_done),
      .imem_we(imem_we & init_done),
      .imem_waddr(imem_waddr),
      .imem_wdata(imem_wdata),
      .imem_hreq(1'b0),
      .imem_hraddr(6'h0),
      .imem_hrdata(imem_hrdata),
      .host_wr(host_wr & init_done),
      .host_wdata(host_wdata),
      .host_full(host_full),
      .host_rd(host_rd),
      .host_rdata(host_rdata),
      .host_empty(host_empty),
      .host_tx_count(host_tx_count),
      .host_rx_count(host_rx_count),
      .enable0(enable0),
      .err_any(err_any),
      .run(run_g),
      .cfg_we(cfg_we),
      .cfg_re(cfg_re),
      .cfg_addr(cfg_addr),
      .cfg_wdata(cfg_wdata),
      .cfg_rdata(cfg_rdata),
      .uio_in(uio_in),
      .uio_out(uio_out),
      .uio_oe(uio_oe),
      .dbg_pc(dbg_pc),
      .dbg_waiting(dbg_waiting),
      .dbg_miss(dbg_miss),
      .dbg_tick(dbg_tick),
      .dbg_timer_run(dbg_timer_run),
      .dbg_a_kind(dbg_a_kind),
      .dbg_p_kind(dbg_p_kind)
  );

  initial assume (!rst_n);

  reg saw_reset;
  initial saw_reset = 1'b0;
  always @(posedge clk) begin
    if (!rst_n)
      saw_reset <= 1'b1;
  end

  always @(posedge clk) begin
    if (rst_n && saw_reset) begin
      if (dbg_p_kind != 2'b00)
        assert (dbg_a_kind != 2'b00);
    end
  end

  wire _unused = &{host_full, host_empty, host_rdata, host_tx_count, host_rx_count,
                   enable0, err_any, imem_hrdata, uio_out, uio_oe, cfg_rdata,
                   dbg_pc, dbg_waiting, dbg_miss, dbg_tick, dbg_timer_run};
endmodule

`default_nettype wire
