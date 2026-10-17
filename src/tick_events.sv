`default_nettype none

// tick_events — 4 event selectors: live detect, LATCHED pending, trap priority.
// Pin events use lp_in / lp_prev (post-sync, post-glitch). Host data/space are levels.
module tick_events (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        run,
    input  wire [3:0]  lp_in,
    // Levels matching the sync snap target (pin_raw→LP). Used on RUN rise so
    // lp_prev matches post-snap lp_in (pre-snap lp_in would invent EDGE/QUAL).
    input  wire [3:0]  lp_snap,
    input  wire        host_data,
    input  wire        host_space,
    input  wire [7:0]  ev0_cfg,
    input  wire [7:0]  ev0_trap,
    input  wire [7:0]  ev1_cfg,
    input  wire [7:0]  ev1_trap,
    input  wire [7:0]  ev2_cfg,
    input  wire [7:0]  ev2_trap,
    input  wire [7:0]  ev3_cfg,
    input  wire [7:0]  ev3_trap,
    // Write-1 clear (EVCLR / WAIT consume / event trap winner)
    input  wire        pending_clear_en,
    input  wire [3:0]  pending_clear_mask,
    output wire [3:0]  ev_live,
    output wire [3:0]  ev_wait,
    output wire [3:0]  ev_pending,
    output wire        trap_req,
    output wire [5:0]  trap_vec,
    output wire [3:0]  trap_ev_bit
);
  reg [3:0] lp_prev_q;
  reg [3:0] pending_q;
  reg        run_q;

  wire [7:0] cfg  [0:3];
  wire [7:0] trap [0:3];
  assign cfg[0]  = ev0_cfg;  assign trap[0] = ev0_trap;
  assign cfg[1]  = ev1_cfg;  assign trap[1] = ev1_trap;
  assign cfg[2]  = ev2_cfg;  assign trap[2] = ev2_trap;
  assign cfg[3]  = ev3_cfg;  assign trap[3] = ev3_trap;

  function automatic is_edge_kind(input [3:0] kind);
    is_edge_kind = (kind == 4'd2) || (kind == 4'd3) || (kind == 4'd4) || (kind == 4'd5);
  endfunction

  function automatic live_of(
      input [3:0] kind,
      input [1:0] pin,
      input [1:0] qual,
      input [3:0] now,
      input [3:0] prev,
      input       hdata,
      input       hspace
  );
    reg p, q, pp;
    begin
      p  = now[pin];
      pp = prev[pin];
      q  = now[qual];
      case (kind)
        4'd0: live_of = (p == 1'b0);                         // LEVEL_LOW
        4'd1: live_of = (p == 1'b1);                         // LEVEL_HIGH
        4'd2: live_of = (pp == 1'b0) && (p == 1'b1);         // EDGE_RISE
        4'd3: live_of = (pp == 1'b1) && (p == 1'b0);         // EDGE_FALL
        4'd4: live_of = (q == 1'b1) && (pp == 1'b1) && (p == 1'b0); // QUAL_FALL
        4'd5: live_of = (q == 1'b1) && (pp == 1'b0) && (p == 1'b1); // QUAL_RISE
        4'd6: live_of = hdata;                               // HOST_DATA
        4'd7: live_of = hspace;                              // HOST_SPACE
        default: live_of = 1'b0;
      endcase
    end
  endfunction

  wire [3:0] live_w;
  wire [3:0] latched_w;
  wire [3:0] trap_en_w;
  wire [5:0] vec_w [0:3];
  genvar gi;
  generate
    for (gi = 0; gi < 4; gi = gi + 1) begin : g_ev
      assign live_w[gi] = live_of(
          cfg[gi][3:0], cfg[gi][5:4], cfg[gi][7:6],
          lp_in, lp_prev_q, host_data, host_space
      );
      assign latched_w[gi] = trap[gi][7] & is_edge_kind(cfg[gi][3:0]);
      assign trap_en_w[gi] = trap[gi][0];
      assign vec_w[gi]     = trap[gi][6:1];
    end
  endgenerate

  assign ev_live = live_w;
  assign ev_pending = pending_q;

  // WAIT visibility: LATCHED edges use pending OR this-cycle live edge
  // (ISS _update_ev_pending then _event_for_wait in the same step).
  assign ev_wait[0] = latched_w[0] ? (pending_q[0] | live_w[0]) : live_w[0];
  assign ev_wait[1] = latched_w[1] ? (pending_q[1] | live_w[1]) : live_w[1];
  assign ev_wait[2] = latched_w[2] ? (pending_q[2] | live_w[2]) : live_w[2];
  assign ev_wait[3] = latched_w[3] ? (pending_q[3] | live_w[3]) : live_w[3];

  // Trap priority: lower event index wins; live edge (not pending).
  // On RUN rise, suppress *pin* traps only: sync snaps that cycle but combo
  // live can still see pre-snap load-bus levels. HOST_DATA / HOST_SPACE do not
  // use the pin path and must still trap (ISS; fuzz trial26).
  wire       run_rise = run & ~run_q;
  reg        trap_req_c;
  reg [5:0]  trap_vec_c;
  reg [3:0]  trap_bit_c;
  integer ti;
  always @(*) begin
    trap_req_c = 1'b0;
    trap_vec_c = 6'd0;
    trap_bit_c = 4'h0;
    for (ti = 0; ti < 4; ti = ti + 1) begin
      if (!trap_req_c && trap_en_w[ti] && live_w[ti]) begin
        if (run_rise && (cfg[ti][3:0] < 4'd6)) begin
          // pin level/edge/qual: skip on RUN rise
        end else begin
          trap_req_c = 1'b1;
          trap_vec_c = vec_w[ti];
          trap_bit_c = 4'h1 << ti;
        end
      end
    end
  end
  assign trap_req    = run & trap_req_c;
  assign trap_vec    = trap_vec_c;
  assign trap_ev_bit = trap_bit_c;

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      lp_prev_q  <= 4'hF;
      pending_q  <= 4'h0;
      run_q      <= 1'b0;
    end else begin
      run_q <= run;
      if (!run) begin
        lp_prev_q  <= lp_in;
        pending_q  <= 4'h0;
      end else if (!run_q) begin
        // Rising run: snap prev to lp_snap (same as sync's pin_raw target), not
        // pre-snap lp_in — otherwise the next cycle sees a phantom EDGE/QUAL.
        lp_prev_q  <= lp_snap;
        pending_q  <= 4'h0;
      end else begin
        lp_prev_q <= lp_in;
        // Set latched pending from live edges; then apply clears (trap/WAIT/EVCLR).
        if (pending_clear_en)
          pending_q <= (pending_q | (live_w & latched_w)) & ~pending_clear_mask;
        else
          pending_q <= (pending_q | (live_w & latched_w));
      end
    end
  end
endmodule

`default_nettype wire
