`default_nettype none

// tick_core — wire-only top for the single-context Tick subset.
// Instantiates: tick_imem, host_fifo×2, tick_cfg, tick_timer, tick_queue, tick_issue.
// Sync: own-drive delay 1 + 2-flop sync (+ optional glitch) → lp_in[3:0].
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
    input  wire        cfg_we,
    input  wire        cfg_re,
    input  wire [7:0]  cfg_addr,
    input  wire [7:0]  cfg_wdata,
    output wire [7:0]  cfg_rdata,
    input  wire [7:0]  uio_in,
    output wire [7:0]  uio_out,
    output wire [7:0]  uio_oe,
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
  // fetch_pc / imem placed after trap sources (Icarus: no use-before-declare).

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

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
      host_rdata <= 10'h0;
    else
      host_rdata <= rx_rdata_c;
  end

  assign host_full  = tx_full;
  assign host_empty = rx_empty;

  wire        enable0;
  wire [2:0]  pinmap0, pinmap1, pinmap2, pinmap3;
  wire [1:0]  pinmode0, pinmode1, pinmode2, pinmode3;
  wire [3:0]  pinidle;
  wire [1:0]  dout_lp, din_lp, clk_lp;
  wire        msb_first, clk_en, cpol, cpha;
  wire        tick_src, tick_rise;
  wire [1:0]  tick_pin, miss_pol;
  wire [5:0]  miss_vec;
  wire [7:0]  default_byte;
  wire [19:0] per_fp;
  wire [15:0] phase_cfg;
  wire [5:0]  cfg_base, cfg_bound;
  wire [3:0]  glitch;
  wire [7:0]  ev0_cfg, ev0_trap, ev1_cfg, ev1_trap;
  wire [7:0]  ev2_cfg, ev2_trap, ev3_cfg, ev3_trap;
  wire [7:0]  err_bits;
  wire        err_map_set, err_under_set, err_overrun_set, err_arb_set;
  wire        err_clear;
  wire [7:0]  err_clear_mask;
  wire        per_we, phase_we, phase_hi, ecfg_we;
  wire [1:0]  per_sel;
  wire [7:0]  per_wdata, phase_wdata, ecfg_wdata;

  tick_cfg u_cfg (
      .clk(clk),
      .rst_n(rst_n),
      .cfg_we(cfg_we),
      .cfg_re(cfg_re),
      .cfg_addr(cfg_addr),
      .cfg_wdata(cfg_wdata),
      .cfg_rdata(cfg_rdata),
      .per_we(per_we),
      .per_sel(per_sel),
      .per_wdata(per_wdata),
      .phase_we(phase_we),
      .phase_hi(phase_hi),
      .phase_wdata(phase_wdata),
      .ecfg_we(ecfg_we),
      .ecfg_wdata(ecfg_wdata),
      .err_map_set(err_map_set),
      .err_under_set(err_under_set),
      .err_overrun_set(err_overrun_set),
      .err_arb_set(err_arb_set),
      .err_clear(err_clear),
      .err_clear_mask(err_clear_mask),
      .err_bits(err_bits),
      .enable0(enable0),
      .pinmap0(pinmap0),
      .pinmap1(pinmap1),
      .pinmap2(pinmap2),
      .pinmap3(pinmap3),
      .pinmode0(pinmode0),
      .pinmode1(pinmode1),
      .pinmode2(pinmode2),
      .pinmode3(pinmode3),
      .pinidle(pinidle),
      .dout_lp(dout_lp),
      .din_lp(din_lp),
      .clk_lp(clk_lp),
      .msb_first(msb_first),
      .clk_en(clk_en),
      .cpol(cpol),
      .cpha(cpha),
      .tick_src(tick_src),
      .tick_rise(tick_rise),
      .tick_pin(tick_pin),
      .miss_pol(miss_pol),
      .miss_vec(miss_vec),
      .default_byte(default_byte),
      .per_fp(per_fp),
      .phase(phase_cfg),
      .base(cfg_base),
      .bound(cfg_bound),
      .glitch(glitch),
      .ev0_cfg(ev0_cfg),
      .ev0_trap(ev0_trap),
      .ev1_cfg(ev1_cfg),
      .ev1_trap(ev1_trap),
      .ev2_cfg(ev2_cfg),
      .ev2_trap(ev2_trap),
      .ev3_cfg(ev3_cfg),
      .ev3_trap(ev3_trap)
  );

  wire internal_run = run & enable0;

  wire        tick, tick_r, timer_run;
  wire [15:0] time_cnt;
  wire [19:0] per_fp_obs;
  wire [15:0] phase_cfg_obs;
  wire        i_start, i_stop, i_rearm;
  wire        q_stop, q_rearm;
  reg         t_start, t_stop, t_rearm;

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
      .run(internal_run),
      .start(t_start),
      .stop(t_stop),
      .rearm(t_rearm),
      .per_fp(per_fp),
      .phase_cfg(phase_cfg),
      .tick(tick),
      .tick_r(tick_r),
      .timer_run(timer_run),
      .time_cnt(time_cnt),
      .per_fp_obs(per_fp_obs),
      .phase_cfg_obs(phase_cfg_obs)
  );

  // ---- Pin sync path (READBACK_LATENCY=3 → own delay 1 + sync depth 2) ----
  wire [7:0] q_uio_out, q_uio_oe, q_uio_out_c, q_uio_oe_c;
  reg  [7:0] own_d;
  reg  [7:0] sync0, sync1;
  reg  [7:0] maj0, maj1, maj2;
  wire [7:0] filt;
  wire [7:0] pin_raw;
  wire [3:0] lp_in;

  // RUN rising: snap the whole sync/majority pipeline to pin_raw (ISS enable
  // snap). Otherwise load-bus residue still in sync1/filt makes LEVEL_* traps
  // fire before the post-run inputs have propagated.
  reg run_q_sync;
  wire run_rise_sync = internal_run & ~run_q_sync;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      own_d      <= 8'hFF;
      sync0      <= 8'hFF;
      sync1      <= 8'hFF;
      maj0       <= 8'hFF;
      maj1       <= 8'hFF;
      maj2       <= 8'hFF;
      run_q_sync <= 1'b0;
    end else begin
      run_q_sync <= internal_run;
      own_d <= q_uio_out_c;
      if (run_rise_sync) begin
        sync0 <= pin_raw;
        sync1 <= pin_raw;
        maj0  <= pin_raw;
        maj1  <= pin_raw;
        maj2  <= pin_raw;
      end else begin
        sync0 <= pin_raw;
        sync1 <= sync0;
        maj0  <= sync0;
        maj1  <= maj0;
        maj2  <= maj1;
      end
    end
  end

  generate
    for (genvar gi = 0; gi < 8; gi = gi + 1) begin : g_pin
      assign pin_raw[gi] = q_uio_oe_c[gi] ? own_d[gi] : uio_in[gi];
      assign filt[gi] = (maj0[gi] & maj1[gi]) | (maj0[gi] & maj2[gi]) | (maj1[gi] & maj2[gi]);
    end
  endgenerate

  wire [2:0] pmap0_w = pinmap0;
  wire [2:0] pmap1_w = pinmap1;
  wire [2:0] pmap2_w = pinmap2;
  wire [2:0] pmap3_w = pinmap3;

  assign lp_in[0] = glitch[0] ? filt[pmap0_w] : sync1[pmap0_w];
  assign lp_in[1] = glitch[1] ? filt[pmap1_w] : sync1[pmap1_w];
  assign lp_in[2] = glitch[2] ? filt[pmap2_w] : sync1[pmap2_w];
  assign lp_in[3] = glitch[3] ? filt[pmap3_w] : sync1[pmap3_w];

  // RUN-rise edge detector prev-sample: map pin_raw (sync snap target). Glitch
  // majority of three identical samples is the sample itself.
  wire [3:0] lp_snap;
  assign lp_snap[0] = pin_raw[pmap0_w];
  assign lp_snap[1] = pin_raw[pmap1_w];
  assign lp_snap[2] = pin_raw[pmap2_w];
  assign lp_snap[3] = pin_raw[pmap3_w];

  assign uio_out = q_uio_out;
  assign uio_oe  = q_uio_oe;

  wire [1:0]  at_a_kind, at_p_kind;
  wire        at_slots_full;
  wire        event_wait_done, tick_wait_done;
  wire        miss, miss_comb, res_valid;
  wire [15:0] result;
  wire [1:0]  a_kind, p_kind;
  wire        waiting;
  wire [4:0]  wait_mask;
  wire [1:0]  wait_tc;
  wire        pull_block, mfs_block;
  wire        post_en, post_oe, post_msb, post_in_t;
  wire [1:0]  post_kind, post_mode, post_lp;
  wire [3:0]  post_mask, post_val, post_nm1;
  wire [7:0]  post_data;
  wire        miss_clear, res_take;
  wire        pin_we, pin_oe_mode;
  wire [3:0]  pin_mask, pin_val4;
  wire        in_t_done, in_t_bit;
  wire        host_data = !tx_empty;
  wire        host_space = !rx_full;
  wire [3:0]  ev_live, ev_wait, ev_pending;
  wire        event_trap_req;
  wire [5:0]  event_trap_vec;
  wire [3:0]  event_trap_bit;
  wire        miss_trap_req;
  wire        pending_clear_en;
  wire [3:0]  pending_clear_mask;
  wire        stretching_obs;
  // Event traps suppress tick consume this cycle (ISS: trap before emit).
  wire        tick_eff = tick & ~event_trap_req;
  wire        trap_cancel = event_trap_req;

  tick_events u_events (
      .clk(clk),
      .rst_n(rst_n),
      .run(internal_run),
      .lp_in(lp_in),
      .lp_snap(lp_snap),
      .host_data(host_data),
      .host_space(host_space),
      .ev0_cfg(ev0_cfg),
      .ev0_trap(ev0_trap),
      .ev1_cfg(ev1_cfg),
      .ev1_trap(ev1_trap),
      .ev2_cfg(ev2_cfg),
      .ev2_trap(ev2_trap),
      .ev3_cfg(ev3_cfg),
      .ev3_trap(ev3_trap),
      .pending_clear_en(pending_clear_en),
      .pending_clear_mask(pending_clear_mask),
      .ev_live(ev_live),
      .ev_wait(ev_wait),
      .ev_pending(ev_pending),
      .trap_req(event_trap_req),
      .trap_vec(event_trap_vec),
      .trap_ev_bit(event_trap_bit)
  );

  tick_queue u_queue (
      .clk(clk),
      .rst_n(rst_n),
      .run(internal_run),
      .tick(tick_eff),
      .timer_run(timer_run),
      .lp_in(lp_in),
      .pinmode0(pinmode0),
      .pinmode1(pinmode1),
      .pinmode2(pinmode2),
      .pinmode3(pinmode3),
      .pinmap0(pinmap0),
      .pinmap1(pinmap1),
      .pinmap2(pinmap2),
      .pinmap3(pinmap3),
      .pinidle(pinidle),
      .dout_lp(dout_lp),
      .din_lp(din_lp),
      .clk_lp(clk_lp),
      .miss_pol(miss_pol),
      .default_byte(default_byte),
      .cfg_msb_first(msb_first),
      .ev_wait(ev_wait),
      .trap_cancel(trap_cancel),
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
      .post_in_t(post_in_t),
      .post_lp(post_lp),
      .miss_clear(miss_clear),
      .res_take(res_take),
      .pin_we(pin_we),
      .pin_oe_mode(pin_oe_mode),
      .pin_mask(pin_mask),
      .pin_val4(pin_val4),
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
      .miss_comb(miss_comb),
      .res_valid(res_valid),
      .result(result),
      .uio_out(q_uio_out),
      .uio_oe(q_uio_oe),
      .uio_out_comb(q_uio_out_c),
      .uio_oe_comb(q_uio_oe_c),
      .err_map_set(err_map_set),
      .err_overrun_set(err_overrun_set),
      .err_arb_set(err_arb_set),
      .in_t_done(in_t_done),
      .in_t_bit(in_t_bit),
      .miss_trap_req(miss_trap_req),
      .stretching_obs(stretching_obs)
  );

  // On trap, ISS redirects PC then issues the vector insn in the same cycle.
  wire [5:0] fetch_pc = event_trap_req ? event_trap_vec
                      : (miss_trap_req ? miss_vec : pc);

  tick_imem u_imem (
      .clk(clk),
      .rst_n(rst_n),
      .we(imem_we),
      .waddr(imem_waddr),
      .wdata(imem_wdata),
      .raddr(fetch_pc),
      .rdata(instr)
  );

  tick_issue u_issue (
      .clk(clk),
      .rst_n(rst_n),
      .run(run),
      .ctx_enable(enable0),
      .instr(instr),
      .at_a_kind(at_a_kind),
      .at_p_kind(at_p_kind),
      .at_slots_full(at_slots_full),
      .event_wait_done(event_wait_done),
      .tick_wait_done(tick_wait_done),
      .timer_run(timer_run),
      .cfg_msb_first(msb_first),
      .cfg_clk_en(clk_en),
      .cfg_cpha(cpha),
      .cfg_cpol(cpol),
      .default_byte(default_byte),
      .time_cnt(time_cnt),
      .lp_in(lp_in),
      .in_t_done(in_t_done),
      .in_t_bit(in_t_bit),
      // miss_comb: same-cycle MISS (ISS applies tick before JMP); sticky miss_q lags 1 cy.
      .err_bits({err_bits[7:1], miss_comb | err_bits[0]}),
      .tx_empty(tx_empty),
      .ev_wait(ev_wait),
      .ev_pending(ev_pending),
      .trap_req(event_trap_req),
      .trap_vec(event_trap_vec),
      .trap_ev_bit(event_trap_bit),
      .miss_trap_req(miss_trap_req),
      .miss_vec(miss_vec),
      .tx_rdata(tx_rdata),
      .tx_rd(tx_rd),
      .rx_full(rx_full),
      .rx_wr(rx_wr),
      .rx_wdata(rx_wdata),
      .res_valid(res_valid),
      .result(result),
      .res_take(res_take),
      .miss_clear(miss_clear),
      .err_clear(err_clear),
      .err_clear_mask(err_clear_mask),
      .err_under_set(err_under_set),
      .post_en(post_en),
      .post_kind(post_kind),
      .post_oe(post_oe),
      .post_mask(post_mask),
      .post_val(post_val),
      .post_mode(post_mode),
      .post_nm1(post_nm1),
      .post_data(post_data),
      .post_msb(post_msb),
      .post_in_t(post_in_t),
      .post_lp(post_lp),
      .pin_we(pin_we),
      .pin_oe_mode(pin_oe_mode),
      .pin_mask(pin_mask),
      .pin_val4(pin_val4),
      .tcmd_start(i_start),
      .tcmd_stop(i_stop),
      .tcmd_rearm(i_rearm),
      .per_we(per_we),
      .per_sel(per_sel),
      .per_wdata(per_wdata),
      .phase_we(phase_we),
      .phase_hi(phase_hi),
      .phase_wdata(phase_wdata),
      .ecfg_we(ecfg_we),
      .ecfg_wdata(ecfg_wdata),
      .pc(pc),
      .waiting(waiting),
      .wait_mask_obs(wait_mask),
      .wait_tc_obs(wait_tc),
      .pull_block_obs(pull_block),
      .mfs_block_obs(mfs_block),
      .pending_clear_en(pending_clear_en),
      .pending_clear_mask(pending_clear_mask)
  );

  assign dbg_pc        = pc;
  assign dbg_waiting   = waiting;
  assign dbg_miss      = miss;
  assign dbg_tick      = tick_r;
  assign dbg_timer_run = timer_run;
  assign dbg_a_kind    = a_kind;
  assign dbg_p_kind    = p_kind;

  wire _unused = &{per_fp_obs, phase_cfg_obs, cfg_base, cfg_bound,
                   tick_src, tick_rise, tick_pin, ev_live, stretching_obs, 1'b0};
endmodule

`default_nettype wire
