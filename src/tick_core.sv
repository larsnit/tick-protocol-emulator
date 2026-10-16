`default_nettype none

// tick_core — wire-only top for the single-context Tick subset.
// Instantiates: tick_imem, host_fifo×2, tick_timer, tick_queue, tick_issue.
// Cycle dataflow: timer.tick → queue after-tick → issue → queue/timer/FIFO next.
// Encoding matches sw/tick/isa.py. Implements ISA §1–§3 single-context RTL.
module tick_core (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        imem_we,
    input  wire [5:0]  imem_waddr,
    input  wire [15:0] imem_wdata,
    input  wire        host_wr,
    input  wire [9:0]  host_wdata,
    output wire        host_full,
    input  wire        host_rd,
    output reg  [9:0]  host_rdata,
    output wire        host_empty,
    input  wire        run,
    input  wire [19:0] cfg_per_fp,
    input  wire [15:0] cfg_phase,
    input  wire        cfg_msb_first,
    output wire        pin0_out,
    output wire        pin0_oe,
    input  wire        pin0_in,
    output wire [5:0]  dbg_pc,
    output wire        dbg_waiting,
    output wire        dbg_miss,
    output wire        dbg_tick,
    output wire        dbg_timer_run,
    output wire [1:0]  dbg_a_kind,
    output wire [1:0]  dbg_p_kind
);
  wire [15:0] instr;
  wire [5:0]  pc;

  tick_imem u_imem (
      .clk(clk),
      .rst_n(rst_n),
      .we(imem_we),
      .waddr(imem_waddr),
      .wdata(imem_wdata),
      .raddr(pc),
      .rdata(instr)
  );

  wire       tx_full, tx_empty, rx_full, rx_empty;
  wire [9:0] tx_rdata, rx_rdata_c;
  wire       tx_rd, rx_wr;
  wire [9:0] rx_wdata;

  host_fifo #(.DEPTH(8), .WIDTH(10)) u_tx (
      .clk(clk),
      .rst_n(rst_n),
      .wr(host_wr),
      .wdata(host_wdata),
      .full(tx_full),
      .rd(tx_rd),
      .rdata(tx_rdata),
      .empty(tx_empty)
  );

  host_fifo #(.DEPTH(8), .WIDTH(10)) u_rx (
      .clk(clk),
      .rst_n(rst_n),
      .wr(rx_wr),
      .wdata(rx_wdata),
      .full(rx_full),
      .rd(host_rd),
      .rdata(rx_rdata_c),
      .empty(rx_empty)
  );

  // Registered host_rdata matches the monolithic core (one flop stage).
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      host_rdata <= 10'h0;
    else
      host_rdata <= rx_rdata_c;
  end

  assign host_full  = tx_full;
  assign host_empty = rx_empty;

  wire        tick, tick_r, timer_run;
  wire [15:0] time_cnt;
  wire [19:0] per_fp_obs;
  wire [15:0] phase_cfg_obs;
  wire        i_start, i_stop, i_rearm;
  wire        q_stop, q_rearm;
  reg         t_start, t_stop, t_rearm;
  wire        per_we, phase_we, phase_hi;
  wire [1:0]  per_sel;
  wire [7:0]  per_wdata, phase_wdata;

  // Issue commands override queue (later in original monolithic order).
  always @(*) begin
    t_stop  = q_stop;
    t_rearm = q_rearm;
    t_start = 1'b0;
    if (i_stop) begin
      t_stop  = 1'b1;
      t_rearm = 1'b0;
    end
    if (i_rearm) begin
      t_rearm = 1'b1;
      t_stop  = 1'b0;
    end
    if (i_start)
      t_start = 1'b1;
  end

  tick_timer u_timer (
      .clk(clk),
      .rst_n(rst_n),
      .run(run),
      .start(t_start),
      .stop(t_stop),
      .rearm(t_rearm),
      .cfg_per_fp_init(cfg_per_fp),
      .cfg_phase_init(cfg_phase),
      .per_we(per_we),
      .per_sel(per_sel),
      .per_wdata(per_wdata),
      .phase_we(phase_we),
      .phase_hi(phase_hi),
      .phase_wdata(phase_wdata),
      .tick(tick),
      .tick_r(tick_r),
      .timer_run(timer_run),
      .time_cnt(time_cnt),
      .per_fp_obs(per_fp_obs),
      .phase_cfg_obs(phase_cfg_obs)
  );

  wire [1:0]  at_a_kind, at_p_kind;
  wire        at_slots_full;
  wire        event_wait_done, tick_wait_done;
  wire        miss, res_valid;
  wire [15:0] result;
  wire [1:0]  a_kind, p_kind;
  wire        waiting;
  wire [4:0]  wait_mask;
  wire [1:0]  wait_tc;
  wire        pull_block, mfs_block;
  wire        post_en, post_oe, post_msb;
  wire [1:0]  post_kind, post_mode;
  wire [3:0]  post_mask, post_val, post_nm1;
  wire [7:0]  post_data;
  wire        miss_clear, res_take;
  wire        pin_we, pin_oe_mode, pin_val;
  wire        host_data = !tx_empty;

  tick_queue u_queue (
      .clk(clk),
      .rst_n(rst_n),
      .run(run),
      .tick(tick),
      .timer_run(timer_run),
      .pin0_in(pin0_in),
      .host_data(host_data),
      .waiting(waiting),
      .wait_mask(wait_mask),
      .wait_tc(wait_tc),
      .pull_block(pull_block),
      .mfs_block(mfs_block),
      .post_en(post_en),
      .post_kind(post_kind),
      .post_oe(post_oe),
      .post_mask(post_mask),
      .post_val(post_val),
      .post_mode(post_mode),
      .post_nm1(post_nm1),
      .post_data(post_data),
      .post_msb(post_msb),
      .miss_clear(miss_clear),
      .res_take(res_take),
      .pin_we(pin_we),
      .pin_oe_mode(pin_oe_mode),
      .pin_val(pin_val),
      .at_a_kind(at_a_kind),
      .at_p_kind(at_p_kind),
      .at_slots_full(at_slots_full),
      .event_wait_done(event_wait_done),
      .tick_wait_done(tick_wait_done),
      .tcmd_stop(q_stop),
      .tcmd_rearm(q_rearm),
      .a_kind(a_kind),
      .p_kind(p_kind),
      .miss(miss),
      .res_valid(res_valid),
      .result(result),
      .pin0_out(pin0_out),
      .pin0_oe(pin0_oe)
  );

  tick_issue u_issue (
      .clk(clk),
      .rst_n(rst_n),
      .run(run),
      .instr(instr),
      .at_a_kind(at_a_kind),
      .at_p_kind(at_p_kind),
      .at_slots_full(at_slots_full),
      .event_wait_done(event_wait_done),
      .tick_wait_done(tick_wait_done),
      .timer_run(timer_run),
      .cfg_msb_first(cfg_msb_first),
      .tx_empty(tx_empty),
      .tx_rdata(tx_rdata),
      .tx_rd(tx_rd),
      .rx_full(rx_full),
      .rx_wr(rx_wr),
      .rx_wdata(rx_wdata),
      .res_valid(res_valid),
      .result(result),
      .res_take(res_take),
      .miss_clear(miss_clear),
      .post_en(post_en),
      .post_kind(post_kind),
      .post_oe(post_oe),
      .post_mask(post_mask),
      .post_val(post_val),
      .post_mode(post_mode),
      .post_nm1(post_nm1),
      .post_data(post_data),
      .post_msb(post_msb),
      .pin_we(pin_we),
      .pin_oe_mode(pin_oe_mode),
      .pin_val(pin_val),
      .tcmd_start(i_start),
      .tcmd_stop(i_stop),
      .tcmd_rearm(i_rearm),
      .per_we(per_we),
      .per_sel(per_sel),
      .per_wdata(per_wdata),
      .phase_we(phase_we),
      .phase_hi(phase_hi),
      .phase_wdata(phase_wdata),
      .pc(pc),
      .waiting(waiting),
      .wait_mask_obs(wait_mask),
      .wait_tc_obs(wait_tc),
      .pull_block_obs(pull_block),
      .mfs_block_obs(mfs_block)
  );

  assign dbg_pc        = pc;
  assign dbg_waiting   = waiting;
  assign dbg_miss      = miss;
  assign dbg_tick      = tick_r;
  assign dbg_timer_run = timer_run;
  assign dbg_a_kind    = a_kind;
  assign dbg_p_kind    = p_kind;

  wire _unused = &{time_cnt, per_fp_obs, phase_cfg_obs, 1'b0};
endmodule

`default_nettype wire
