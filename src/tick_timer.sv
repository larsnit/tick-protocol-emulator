`default_nettype none

// tick_timer — fractional PER/PHASE down-counter.
// clk/rst_n/run: clock, reset, run gate.
// start/stop/rearm: next-state only (do not affect same-cycle tick).
// tick: combinational from registers only (for queue same-cycle consume).
// tick_r: registered tick (dbg).
// per_*/phase_*: MTS configuration writes.
// Implements ISA §1 timer tick stream and §3.2 PER/PHASE/TIME.
module tick_timer (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        run,
    input  wire        start,
    input  wire        stop,
    input  wire        rearm,
    input  wire [19:0] cfg_per_fp_init,
    input  wire [15:0] cfg_phase_init,
    input  wire        per_we,
    input  wire [1:0]  per_sel,
    input  wire [7:0]  per_wdata,
    input  wire        phase_we,
    input  wire        phase_hi,
    input  wire [7:0]  phase_wdata,
    output wire        tick,
    output reg         tick_r,
    output wire        timer_run,
    output wire [15:0] time_cnt,
    output wire [19:0] per_fp_obs,
    output wire [15:0] phase_cfg_obs
);
  reg [19:0] accum_q, per_fp_q;
  reg [15:0] phase_left_q, phase_cfg_q;
  reg        timer_run_q;
  reg [15:0] time_cnt_q;

  reg [19:0] accum_d, per_fp_d;
  reg [15:0] phase_left_d, phase_cfg_d;
  reg        timer_run_d;
  reg [15:0] time_cnt_d;
  reg        tick_comb;
  reg        do_tick;

  assign timer_run     = timer_run_q;
  assign time_cnt      = time_cnt_q;
  assign per_fp_obs    = per_fp_q;
  assign phase_cfg_obs = phase_cfg_q;
  // Same-cycle tick from registers only (ignores start/stop/rearm).
  assign tick = tick_comb;

  always @(*) begin
    tick_comb = 1'b0;
    do_tick   = 1'b0;
    if (run && timer_run_q) begin
      if (phase_left_q != 16'h0) begin
        if (phase_left_q == 16'd1)
          do_tick = 1'b1;
      end else if (accum_q + 20'd16 >= per_fp_q) begin
        do_tick = 1'b1;
      end
      tick_comb = do_tick;
    end
  end

  always @(*) begin
    accum_d      = accum_q;
    phase_left_d = phase_left_q;
    phase_cfg_d  = phase_cfg_q;
    per_fp_d     = per_fp_q;
    timer_run_d  = timer_run_q;
    time_cnt_d   = time_cnt_q;

    if (per_we) begin
      case (per_sel)
        2'd0: per_fp_d[7:0]   = per_wdata;
        2'd1: per_fp_d[15:8]  = per_wdata;
        2'd2: per_fp_d[19:16] = per_wdata[3:0];
        default: ;
      endcase
    end
    if (phase_we) begin
      if (phase_hi)
        phase_cfg_d[15:8] = phase_wdata;
      else
        phase_cfg_d[7:0] = phase_wdata;
    end

    if (run) begin
      if (timer_run_q) begin
        time_cnt_d = time_cnt_q + 16'd1;
        if (phase_left_q != 16'h0) begin
          phase_left_d = phase_left_q - 16'd1;
        end else if (accum_q + 20'd16 >= per_fp_q) begin
          accum_d = accum_q + 20'd16 - per_fp_q;
        end else begin
          accum_d = accum_q + 20'd16;
        end
      end
      // Last-wins: stop, then rearm, then start (matches monolithic NBA order).
      if (stop) begin
        timer_run_d  = 1'b0;
        accum_d      = 20'h0;
        phase_left_d = 16'h0;
      end
      if (rearm) begin
        timer_run_d  = 1'b1;
        accum_d      = 20'h0;
        time_cnt_d   = 16'h0;
        phase_left_d = phase_cfg_q;
      end
      if (start && !timer_run_q) begin
        timer_run_d  = 1'b1;
        accum_d      = 20'h0;
        time_cnt_d   = 16'h0;
        phase_left_d = phase_cfg_q;
      end
    end
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      timer_run_q  <= 1'b0;
      accum_q      <= 20'h0;
      phase_left_q <= 16'h0;
      time_cnt_q   <= 16'h0;
      tick_r       <= 1'b0;
      per_fp_q     <= cfg_per_fp_init;
      phase_cfg_q  <= cfg_phase_init;
    end else begin
      tick_r       <= run ? tick_comb : 1'b0;
      timer_run_q  <= run ? timer_run_d : timer_run_q;
      accum_q      <= run ? accum_d : accum_q;
      phase_left_q <= run ? phase_left_d : phase_left_q;
      time_cnt_q   <= run ? time_cnt_d : time_cnt_q;
      per_fp_q     <= per_fp_d;
      phase_cfg_q  <= phase_cfg_d;
    end
  end
endmodule

`default_nettype wire
