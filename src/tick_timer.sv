`default_nettype none

// tick_timer — fractional PER/PHASE down-counter.
// PER/PHASE are live inputs from tick_cfg (same regs as MTS); timer only reads.
// start/stop/rearm: next-state only (do not affect same-cycle tick).
// tick: combinational from registers only (for queue same-cycle consume).
module tick_timer (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        run,
    input  wire        start,
    input  wire        stop,
    input  wire        rearm,
    input  wire [19:0] per_fp,
    input  wire [15:0] phase_cfg,
    output wire        tick,
    output reg         tick_r,
    output wire        timer_run,
    output wire [15:0] time_cnt,
    output wire [19:0] per_fp_obs,
    output wire [15:0] phase_cfg_obs
);
  reg [19:0] accum_q;
  reg [15:0] phase_left_q;
  reg        timer_run_q;
  reg [15:0] time_cnt_q;

  reg [19:0] accum_d;
  reg [15:0] phase_left_d;
  reg        timer_run_d;
  reg [15:0] time_cnt_d;
  reg        tick_comb;
  reg        do_tick;

  assign timer_run     = timer_run_q;
  assign time_cnt      = time_cnt_q;
  assign per_fp_obs    = per_fp;
  assign phase_cfg_obs = phase_cfg;
  assign tick = tick_comb;

  always @(*) begin
    tick_comb = 1'b0;
    do_tick   = 1'b0;
    if (run && timer_run_q) begin
      if (phase_left_q != 16'h0) begin
        if (phase_left_q == 16'd1)
          do_tick = 1'b1;
      end else if (accum_q + 20'd16 >= per_fp) begin
        do_tick = 1'b1;
      end
      tick_comb = do_tick;
    end
  end

  always @(*) begin
    accum_d      = accum_q;
    phase_left_d = phase_left_q;
    timer_run_d  = timer_run_q;
    time_cnt_d   = time_cnt_q;

    if (run) begin
      if (timer_run_q) begin
        time_cnt_d = time_cnt_q + 16'd1;
        if (phase_left_q != 16'h0) begin
          phase_left_d = phase_left_q - 16'd1;
        end else if (accum_q + 20'd16 >= per_fp) begin
          accum_d = accum_q + 20'd16 - per_fp;
        end else begin
          accum_d = accum_q + 20'd16;
        end
      end
      if (stop) begin
        timer_run_d  = 1'b0;
        accum_d      = 20'h0;
        phase_left_d = 16'h0;
      end
      if (rearm) begin
        timer_run_d  = 1'b1;
        accum_d      = 20'h0;
        time_cnt_d   = 16'h0;
        phase_left_d = phase_cfg;
      end
      // Use !timer_run_d (after stop), not !timer_run_q: trap stop + same-cycle
      // SET.T start must restart (ISS; fuzz trial83).
      if (start && !timer_run_d) begin
        timer_run_d  = 1'b1;
        accum_d      = 20'h0;
        time_cnt_d   = 16'h0;
        phase_left_d = phase_cfg;
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
    end else begin
      tick_r       <= run ? tick_comb : 1'b0;
      timer_run_q  <= run ? timer_run_d : timer_run_q;
      accum_q      <= run ? accum_d : accum_q;
      phase_left_q <= run ? phase_left_d : phase_left_q;
      time_cnt_q   <= run ? time_cnt_d : time_cnt_q;
    end
  end
endmodule

`default_nettype wire
