`default_nettype none

// tick_queue — two-slot timed queue, tick consume, bit engine, 4 LPs → 8 phys.
// Comb block 1 (after-tick): from queue registers + tick (+ event dequeue).
// Comb block 2 (next): from after-tick + post/pin/res/miss strobes from issue.
// IN.T is posted as kind=xfer with post_in_t=1 (no res_valid).
module tick_queue (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        run,
    input  wire        tick,
    input  wire        timer_run,
    input  wire [3:0]  lp_in,
    input  wire [1:0]  pinmode0,
    input  wire [1:0]  pinmode1,
    input  wire [1:0]  pinmode2,
    input  wire [1:0]  pinmode3,
    input  wire [2:0]  pinmap0,
    input  wire [2:0]  pinmap1,
    input  wire [2:0]  pinmap2,
    input  wire [2:0]  pinmap3,
    input  wire [3:0]  pinidle,
    input  wire [1:0]  dout_lp,
    input  wire [1:0]  din_lp,
    input  wire [1:0]  clk_lp,
    input  wire [1:0]  miss_pol,
    input  wire [7:0]  default_byte,
    input  wire        cfg_msb_first,
    // WAIT visibility (LATCHED pending or live pulse/level) per EV0–3.
    input  wire [3:0]  ev_wait,
    input  wire        trap_cancel,
    input  wire        waiting,
    input  wire [4:0]  wait_mask,
    input  wire [1:0]  wait_tc,
    input  wire        pull_block,
    input  wire        mfs_block,
    input  wire        post_en,
    input  wire [1:0]  post_kind,
    input  wire        post_oe,
    input  wire [3:0]  post_mask,
    input  wire [3:0]  post_val,
    input  wire [1:0]  post_mode,
    input  wire [3:0]  post_nm1,
    input  wire [7:0]  post_data,
    input  wire        post_msb,
    input  wire        post_in_t,
    input  wire [1:0]  post_lp,
    input  wire        miss_clear,
    input  wire        res_take,
    input  wire        pin_we,
    input  wire        pin_oe_mode,
    input  wire [3:0]  pin_mask,
    input  wire [3:0]  pin_val4,
    output wire [1:0]  at_a_kind,
    output wire [1:0]  at_p_kind,
    output wire        at_slots_full,
    output wire        event_wait_done,
    output wire        tick_wait_done,
    output wire        tcmd_stop,
    output wire        tcmd_rearm,
    output reg  [1:0]  a_kind,
    output reg  [1:0]  p_kind,
    output reg         miss,
    // Same-cycle miss pulse/sticky (after-tick at_miss, before miss_clear) so
    // JMP ERR sees MISS the cycle it is set without a miss_clear combo loop.
    output wire        miss_comb,
    output reg         res_valid,
    output reg  [15:0] result,
    output reg  [7:0]  uio_out,
    output reg  [7:0]  uio_oe,
    // Combinational drive (pre-pad register) for own-sample delay into sync
    output wire [7:0]  uio_out_comb,
    output wire [7:0]  uio_oe_comb,
    output reg         err_map_set,
    output reg         err_overrun_set,
    output reg         err_arb_set,
    output wire        in_t_done,
    output wire        in_t_bit,
    // MISS trap request (policy=TRAP); issue takes vector from miss_vec.
    output wire        miss_trap_req,
    output wire        stretching_obs
);
  localparam [1:0] PM_IN = 2'b00;
  localparam [1:0] PM_PP = 2'b01;
  localparam [1:0] PM_OD = 2'b10;

  wire [1:0] pm0 = pinmode0;
  wire [1:0] pm1 = pinmode1;
  wire [1:0] pm2 = pinmode2;
  wire [1:0] pm3 = pinmode3;

  reg        a_oe_q, p_oe_q, a_msb_q, p_msb_q, a_in_t_q, p_in_t_q;
  reg [3:0]  a_mask_q, p_mask_q, a_val_q, p_val_q;
  reg [1:0]  a_mode_q, p_mode_q, a_lp_q, p_lp_q;
  reg [3:0]  a_nm1_q, p_nm1_q, a_done_q;
  reg [7:0]  a_data_q, p_data_q;
  reg [15:0] a_res_q;
  reg [3:0]  drv_val_q, drv_oe_q;
  reg        stretching_q;
  reg        miss_trap_pulse;

  reg [1:0]  at_a_k, at_p_k;
  reg        at_a_oe, at_p_oe, at_a_msb, at_p_msb, at_a_in_t, at_p_in_t;
  reg [3:0]  at_a_mask, at_p_mask, at_a_val, at_p_val;
  reg [1:0]  at_a_mode, at_p_mode, at_a_lp, at_p_lp;
  reg [3:0]  at_a_nm1, at_p_nm1, at_a_done;
  reg [7:0]  at_a_data, at_p_data;
  reg [15:0] at_a_res;
  reg        at_event_done, at_tick_done;
  reg        at_tcmd_stop, at_tcmd_rearm;
  reg        at_miss;
  reg        at_res_valid;
  reg [15:0] at_result;
  reg [3:0]  at_drv_val, at_drv_oe;
  reg        at_stretching;
  reg        at_in_t_done, at_in_t_bit;
  reg [3:0]  rem, sh;
  reg        outb;
  reg [1:0]  sample_lp;
  reg [1:0]  mode_a;
  reg        bit_a;
  reg [1:0]  clk_i;

  reg [1:0]  a_kind_d, p_kind_d;
  reg        a_oe_d, p_oe_d, a_msb_d, p_msb_d, a_in_t_d, p_in_t_d;
  reg [3:0]  a_mask_d, p_mask_d, a_val_d, p_val_d;
  reg [1:0]  a_mode_d, p_mode_d, a_lp_d, p_lp_d;
  reg [3:0]  a_nm1_d, p_nm1_d, a_done_d;
  reg [7:0]  a_data_d, p_data_d;
  reg [15:0] a_res_d;
  reg        miss_d, res_valid_d;
  reg        stretching_d;
  assign miss_comb = at_miss;
  assign miss_trap_req = miss_trap_pulse;
  assign stretching_obs = stretching_q;
  reg [15:0] result_d;
  reg [3:0]  drv_val_d, drv_oe_d;

  reg [7:0]  map_out, map_oe;
  reg        map_err;
  reg        overrun_pulse, arb_pulse;
  reg [1:0]  mode_i, mode_b;
  reg        bit_i, bit_b, oe_i, driving;
  reg [2:0]  phys_i;
  reg [7:0]  seen_phys;

  assign at_a_kind       = at_a_k;
  assign at_p_kind       = at_p_k;
  assign at_slots_full   = (at_a_k != 2'd0) && (at_p_k != 2'd0);
  assign event_wait_done = at_event_done;
  assign tick_wait_done  = at_tick_done;
  assign tcmd_stop       = at_tcmd_stop;
  assign tcmd_rearm      = at_tcmd_rearm;
  // Same-cycle as tick (like event_wait_done) — must not be registered.
  assign in_t_done       = at_in_t_done;
  assign in_t_bit        = at_in_t_bit;
  assign uio_out_comb    = map_out;
  // Ungated: top forces pad OE=0 while !run (load bus). pin_raw must still see
  // idle map_oe so sync settles before run (avoids false EDGE_* on run rise).
  assign uio_oe_comb     = map_oe;
  wire _unused_q = &{sh[3], 1'b0};

  function automatic [1:0] pm_of(input [1:0] li);
    case (li)
      2'd0: pm_of = pm0;
      2'd1: pm_of = pm1;
      2'd2: pm_of = pm2;
      default: pm_of = pm3;
    endcase
  endfunction

  function automatic [2:0] map_of(input [1:0] li);
    case (li)
      2'd0: map_of = pinmap0;
      2'd1: map_of = pinmap1;
      2'd2: map_of = pinmap2;
      default: map_of = pinmap3;
    endcase
  endfunction

  always @(*) begin
    at_a_k = a_kind; at_p_k = p_kind;
    at_a_oe = a_oe_q; at_p_oe = p_oe_q;
    at_a_mask = a_mask_q; at_p_mask = p_mask_q;
    at_a_val = a_val_q; at_p_val = p_val_q;
    at_a_mode = a_mode_q; at_p_mode = p_mode_q;
    at_a_nm1 = a_nm1_q; at_p_nm1 = p_nm1_q;
    at_a_data = a_data_q; at_p_data = p_data_q;
    at_a_msb = a_msb_q; at_p_msb = p_msb_q;
    at_a_in_t = a_in_t_q; at_p_in_t = p_in_t_q;
    at_a_lp = a_lp_q; at_p_lp = p_lp_q;
    at_a_done = a_done_q; at_a_res = a_res_q;
    at_event_done = 1'b0;
    at_tick_done = 1'b0;
    at_tcmd_stop = 1'b0;
    at_tcmd_rearm = 1'b0;
    at_miss = miss;
    at_res_valid = res_valid;
    at_result = result;
    at_drv_val = drv_val_q;
    at_drv_oe = drv_oe_q;
    at_stretching = stretching_q;
    at_in_t_done = 1'b0;
    at_in_t_bit = 1'b0;
    rem = 4'd0;
    sh = 4'd0;
    outb = 1'b0;
    sample_lp = 2'd0;
    mode_a = 2'd0;
    bit_a = 1'b0;
    clk_i = clk_lp;
    overrun_pulse = 1'b0;
    arb_pulse = 1'b0;
    miss_trap_pulse = 1'b0;

    if (!run) begin
      at_drv_val = pinidle;
      at_drv_oe = 4'h0;
      at_stretching = 1'b0;
      // !run: OD idle-high starts with drv_val=0 (ISS Context default) so a
      // pre-trap SET.E still drives; trap/MISS paths below keep pinidle.
      if (pm0 == PM_PP) at_drv_oe[0] = 1'b1;
      else if (pm0 == PM_OD) begin at_drv_oe[0] = ~pinidle[0]; at_drv_val[0] = 1'b0; end
      if (pm1 == PM_PP) at_drv_oe[1] = 1'b1;
      else if (pm1 == PM_OD) begin at_drv_oe[1] = ~pinidle[1]; at_drv_val[1] = 1'b0; end
      if (pm2 == PM_PP) at_drv_oe[2] = 1'b1;
      else if (pm2 == PM_OD) begin at_drv_oe[2] = ~pinidle[2]; at_drv_val[2] = 1'b0; end
      if (pm3 == PM_PP) at_drv_oe[3] = 1'b1;
      else if (pm3 == PM_OD) begin at_drv_oe[3] = ~pinidle[3]; at_drv_val[3] = 1'b0; end
    end else if (trap_cancel) begin
      // Trap: cancel both slots, drive pins to idle (ISS _do_trap).
      // Keep OD drv_val=pinidle (do not force 0) so post-trap SET.E on
      // idle-high OD stays released (fuzz trial25).
      at_a_k = 2'd0;
      at_p_k = 2'd0;
      at_stretching = 1'b0;
      at_tcmd_stop = 1'b1;
      at_drv_val = pinidle;
      at_drv_oe = 4'h0;
      if (pm0 == PM_PP) at_drv_oe[0] = 1'b1;
      else if (pm0 == PM_OD) at_drv_oe[0] = ~pinidle[0];
      if (pm1 == PM_PP) at_drv_oe[1] = 1'b1;
      else if (pm1 == PM_OD) at_drv_oe[1] = ~pinidle[1];
      if (pm2 == PM_PP) at_drv_oe[2] = 1'b1;
      else if (pm2 == PM_OD) at_drv_oe[2] = ~pinidle[2];
      if (pm3 == PM_PP) at_drv_oe[3] = 1'b1;
      else if (pm3 == PM_OD) at_drv_oe[3] = ~pinidle[3];
    end else begin
      // Event-first timed WAIT dequeue. Skip when this cycle also ticks and
      // the mask includes TICK — tick path ORs both EVF bits (docs 6a).
      if (waiting && !pull_block && !mfs_block &&
          (at_a_k == 2'd3 || at_p_k == 2'd3) &&
          |(wait_mask[3:0] & ev_wait) &&
          !(tick && wait_mask[4])) begin
        if (at_a_k == 2'd3) begin
          at_a_k = at_p_k;
          at_a_oe = at_p_oe; at_a_mask = at_p_mask; at_a_val = at_p_val;
          at_a_mode = at_p_mode; at_a_nm1 = at_p_nm1; at_a_data = at_p_data;
          at_a_msb = at_p_msb; at_a_in_t = at_p_in_t; at_a_lp = at_p_lp;
          at_a_done = 4'd0; at_a_res = 16'h0;
          at_p_k = 2'd0;
        end else begin
          at_p_k = 2'd0;
        end
        at_event_done = 1'b1;
        if (wait_tc == 2'b01)
          at_tcmd_rearm = 1'b1;
        else if (wait_tc == 2'b10 || wait_tc == 2'b11)
          at_tcmd_stop = 1'b1;
      end

      if (tick) begin
        if (at_a_k == 2'd0) begin
          if (timer_run) begin
            at_miss = 1'b1;
            // MISS policies (FLAG leaves sticky bit only).
            if (miss_pol == 2'd1) begin
              // trap: cancel queue, idle pins; issue redirects PC (no pending clear).
              miss_trap_pulse = 1'b1;
              at_a_k = 2'd0;
              at_p_k = 2'd0;
              at_stretching = 1'b0;
              at_tcmd_stop = 1'b1;
              at_drv_val = pinidle;
              at_drv_oe = 4'h0;
              if (pm0 == PM_PP) at_drv_oe[0] = 1'b1;
              else if (pm0 == PM_OD) at_drv_oe[0] = ~pinidle[0];
              if (pm1 == PM_PP) at_drv_oe[1] = 1'b1;
              else if (pm1 == PM_OD) at_drv_oe[1] = ~pinidle[1];
              if (pm2 == PM_PP) at_drv_oe[2] = 1'b1;
              else if (pm2 == PM_OD) at_drv_oe[2] = ~pinidle[2];
              if (pm3 == PM_PP) at_drv_oe[3] = 1'b1;
              else if (pm3 == PM_OD) at_drv_oe[3] = ~pinidle[3];
            end else if (miss_pol == 2'd2) begin
              // send-default: inject OUT-8 default and consume this tick as bit 0
              at_a_k = 2'd2;
              at_a_mode = 2'd0; // OUT
              at_a_nm1 = 4'd7;
              at_a_data = default_byte;
              at_a_msb = cfg_msb_first;
              at_a_res = 16'h0;
              at_a_in_t = 1'b0;
              rem = 4'd8;
              sh = cfg_msb_first ? 4'd7 : 4'd0;
              outb = default_byte[sh[2:0]];
              mode_a = pm_of(dout_lp);
              if (mode_a == PM_OD) begin
                if (outb == 1'b0) begin
                  at_drv_val[dout_lp] = 1'b0;
                  at_drv_oe[dout_lp]  = 1'b1;
                end else begin
                  at_drv_oe[dout_lp] = 1'b0;
                end
              end else if (mode_a != PM_IN) begin
                at_drv_val[dout_lp] = outb;
                at_drv_oe[dout_lp]  = 1'b1;
              end
              at_a_done = 4'd1;
            end else if (miss_pol == 2'd3) begin
              // stretch: hold only CLK_LP low if open-drain
              at_stretching = 1'b1;
              if (pm_of(clk_i) == PM_OD) begin
                at_drv_val[clk_i] = 1'b0;
                at_drv_oe[clk_i]  = 1'b1;
              end
            end
          end
        end else if (at_a_k == 2'd1) begin
          if (at_stretching) begin
            at_stretching = 1'b0;
            if (pm_of(clk_i) == PM_OD)
              at_drv_oe[clk_i] = 1'b0;
          end
          for (int i = 0; i < 4; i = i + 1) begin
            if (at_a_mask[i]) begin
              mode_a = pm_of(i[1:0]);
              bit_a = at_a_val[i];
              if (at_a_oe) begin
                if (bit_a) at_drv_oe[i] = 1'b1;
                else       at_drv_oe[i] = 1'b0;
              end else if (mode_a == PM_OD) begin
                if (bit_a == 1'b0) begin
                  at_drv_val[i] = 1'b0;
                  at_drv_oe[i]  = 1'b1;
                end else begin
                  at_drv_oe[i] = 1'b0;
                end
              end else if (mode_a != PM_IN) begin
                at_drv_val[i] = bit_a;
                at_drv_oe[i]  = 1'b1;
              end
            end
          end
          at_a_k = at_p_k;
          at_a_oe = at_p_oe; at_a_mask = at_p_mask; at_a_val = at_p_val;
          at_a_mode = at_p_mode; at_a_nm1 = at_p_nm1; at_a_data = at_p_data;
          at_a_msb = at_p_msb; at_a_in_t = at_p_in_t; at_a_lp = at_p_lp;
          at_a_done = 4'd0; at_a_res = 16'h0;
          at_p_k = 2'd0;
        end else if (at_a_k == 2'd2) begin
          // Release stretch on first bit of a real job (ISS _engine_bit).
          if (at_stretching) begin
            at_stretching = 1'b0;
            if (pm_of(clk_i) == PM_OD)
              at_drv_oe[clk_i] = 1'b0;
          end
          if (at_a_in_t) begin
            at_in_t_done = 1'b1;
            at_in_t_bit  = lp_in[at_a_lp];
            at_a_k = at_p_k;
            at_a_oe = at_p_oe; at_a_mask = at_p_mask; at_a_val = at_p_val;
            at_a_mode = at_p_mode; at_a_nm1 = at_p_nm1; at_a_data = at_p_data;
            at_a_msb = at_p_msb; at_a_in_t = at_p_in_t; at_a_lp = at_p_lp;
            at_a_done = 4'd0; at_a_res = 16'h0;
            at_p_k = 2'd0;
          end else begin
            rem = at_a_nm1 + 4'd1 - at_a_done;
            sh = at_a_msb ? (rem - 4'd1) : at_a_done;
            outb = at_a_data[sh[2:0]];
            if (at_a_mode == 2'd0 || at_a_mode == 2'd2) begin
              mode_a = pm_of(dout_lp);
              if (mode_a == PM_OD) begin
                if (outb == 1'b0) begin
                  at_drv_val[dout_lp] = 1'b0;
                  at_drv_oe[dout_lp]  = 1'b1;
                end else begin
                  at_drv_oe[dout_lp] = 1'b0;
                end
              end else if (mode_a != PM_IN) begin
                at_drv_val[dout_lp] = outb;
                at_drv_oe[dout_lp]  = 1'b1;
              end
            end
            // ISS: pure IN samples dout_lp; BOTH samples din_lp
            sample_lp = (at_a_mode == 2'd1) ? dout_lp : din_lp;
            if (at_a_mode == 2'd1 || at_a_mode == 2'd2) begin
              if (at_a_msb) at_a_res = {at_a_res[14:0], lp_in[sample_lp]};
              else at_a_res[at_a_done] = lp_in[sample_lp];
            end
            // ARB: BOTH + OD DOUT, drive-1 (release) but sync readback is 0
            if (at_a_mode == 2'd2 && pm_of(dout_lp) == PM_OD &&
                outb == 1'b1 && lp_in[dout_lp] == 1'b0)
              arb_pulse = 1'b1;
            if (at_a_done == at_a_nm1) begin
              if (at_res_valid)
                overrun_pulse = 1'b1;
              if (at_a_mode == 2'd0) at_result = {8'h0, at_a_data};
              else at_result = at_a_res;
              at_res_valid = 1'b1;
              at_a_k = at_p_k;
              at_a_oe = at_p_oe; at_a_mask = at_p_mask; at_a_val = at_p_val;
              at_a_mode = at_p_mode; at_a_nm1 = at_p_nm1; at_a_data = at_p_data;
              at_a_msb = at_p_msb; at_a_in_t = at_p_in_t; at_a_lp = at_p_lp;
              at_a_done = 4'd0; at_a_res = 16'h0;
              at_p_k = 2'd0;
            end else begin
              at_a_done = at_a_done + 4'd1;
            end
          end
        end else if (at_a_k == 2'd3) begin
          // Timed WAIT consume ends stretch (ISS _end_stretch).
          if (at_stretching) begin
            at_stretching = 1'b0;
            if (pm_of(clk_i) == PM_OD)
              at_drv_oe[clk_i] = 1'b0;
          end
          at_tick_done = 1'b1;
          if (wait_tc == 2'b01)
            at_tcmd_rearm = 1'b1;
          else if (wait_tc == 2'b10 || wait_tc == 2'b11)
            at_tcmd_stop = 1'b1;
          at_a_k = at_p_k;
          at_a_oe = at_p_oe; at_a_mask = at_p_mask; at_a_val = at_p_val;
          at_a_mode = at_p_mode; at_a_nm1 = at_p_nm1; at_a_data = at_p_data;
          at_a_msb = at_p_msb; at_a_in_t = at_p_in_t; at_a_lp = at_p_lp;
          at_a_done = 4'd0; at_a_res = 16'h0;
          at_p_k = 2'd0;
        end
      end
    end
  end

  always @(*) begin
    a_kind_d = at_a_k; p_kind_d = at_p_k;
    a_oe_d = at_a_oe; p_oe_d = at_p_oe;
    a_mask_d = at_a_mask; p_mask_d = at_p_mask;
    a_val_d = at_a_val; p_val_d = at_p_val;
    a_mode_d = at_a_mode; p_mode_d = at_p_mode;
    a_nm1_d = at_a_nm1; p_nm1_d = at_p_nm1;
    a_data_d = at_a_data; p_data_d = at_p_data;
    a_msb_d = at_a_msb; p_msb_d = at_p_msb;
    a_in_t_d = at_a_in_t; p_in_t_d = at_p_in_t;
    a_lp_d = at_a_lp; p_lp_d = at_p_lp;
    a_done_d = at_a_done; a_res_d = at_a_res;
    miss_d = at_miss;
    res_valid_d = at_res_valid;
    result_d = at_result;
    drv_val_d = at_drv_val;
    drv_oe_d = at_drv_oe;
    stretching_d = at_stretching;

    if (miss_clear)
      miss_d = 1'b0;
    if (res_take)
      res_valid_d = 1'b0;

    mode_b = 2'd0;
    bit_b = 1'b0;
    if (run && pin_we) begin
      for (int i = 0; i < 4; i = i + 1) begin
        if (pin_mask[i]) begin
          mode_b = pm_of(i[1:0]);
          bit_b = pin_val4[i];
          if (pin_oe_mode) begin
            if (bit_b) drv_oe_d[i] = 1'b1;
            else       drv_oe_d[i] = 1'b0;
          end else if (mode_b == PM_OD) begin
            if (bit_b == 1'b0) begin
              drv_val_d[i] = 1'b0;
              drv_oe_d[i]  = 1'b1;
            end else begin
              drv_oe_d[i] = 1'b0;
            end
          end else if (mode_b != PM_IN) begin
            drv_val_d[i] = bit_b;
            drv_oe_d[i]  = 1'b1;
          end
        end
      end
    end

    if (run && post_en) begin
      if (at_a_k == 2'd0) begin
        a_kind_d = post_kind;
        a_in_t_d = post_in_t;
        a_lp_d = post_lp;
        if (post_kind == 2'd1) begin
          a_oe_d = post_oe; a_mask_d = post_mask; a_val_d = post_val;
        end else begin
          a_mode_d = post_mode; a_nm1_d = post_nm1; a_data_d = post_data;
          a_msb_d = post_msb; a_done_d = 4'd0; a_res_d = 16'h0;
        end
      end else begin
        p_kind_d = post_kind;
        p_in_t_d = post_in_t;
        p_lp_d = post_lp;
        if (post_kind == 2'd1) begin
          p_oe_d = post_oe; p_mask_d = post_mask; p_val_d = post_val;
        end else begin
          p_mode_d = post_mode; p_nm1_d = post_nm1; p_data_d = post_data;
          p_msb_d = post_msb;
        end
      end
    end

    // Map LPs → physical uio (lower LP index wins; second driver → MAP err).
    // Always map, including while !run: the top gates pad OE when !run so the
    // load bus still owns uio, but the core OE feeds pin_raw/own_d. If we left
    // map_oe=0 during load, sync sampled uio load traffic and produced false
    // EDGE_* pending when run rose (ISS keeps idle drives visible to sync).
    map_out = 8'h00;
    map_oe  = 8'h00;
    map_err = 1'b0;
    seen_phys = 8'h00;
    mode_i = 2'd0;
    bit_i = 1'b0;
    oe_i = 1'b0;
    driving = 1'b0;
    phys_i = 3'd0;
    for (int i = 0; i < 4; i = i + 1) begin
      mode_i = pm_of(i[1:0]);
      bit_i  = drv_val_d[i];
      oe_i   = drv_oe_d[i];
      phys_i = map_of(i[1:0]);
      driving = 1'b0;
      if (mode_i == PM_OD) begin
        if (bit_i == 1'b0 && oe_i) begin
          driving = 1'b1;
          bit_i = 1'b0;
        end
      end else if (mode_i == PM_PP) begin
        if (oe_i) driving = 1'b1;
      end
      if (driving) begin
        if (seen_phys[phys_i])
          map_err = 1'b1;
        else begin
          seen_phys[phys_i] = 1'b1;
          map_out[phys_i] = bit_i;
          map_oe[phys_i]  = 1'b1;
        end
      end
    end
  end

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      a_kind <= 2'd0; p_kind <= 2'd0;
      a_oe_q <= 1'b0; p_oe_q <= 1'b0;
      a_mask_q <= 4'h0; p_mask_q <= 4'h0;
      a_val_q <= 4'h0; p_val_q <= 4'h0;
      a_mode_q <= 2'd0; p_mode_q <= 2'd0;
      a_nm1_q <= 4'd0; p_nm1_q <= 4'd0;
      a_data_q <= 8'h0; p_data_q <= 8'h0;
      a_done_q <= 4'd0; a_res_q <= 16'h0;
      a_msb_q <= 1'b0; p_msb_q <= 1'b0;
      a_in_t_q <= 1'b0; p_in_t_q <= 1'b0;
      a_lp_q <= 2'd0; p_lp_q <= 2'd0;
      miss <= 1'b0;
      res_valid <= 1'b0; result <= 16'h0;
      drv_val_q <= 4'hF;
      drv_oe_q <= 4'h0;
      stretching_q <= 1'b0;
      uio_out <= 8'h00;
      uio_oe <= 8'h00;
      err_map_set <= 1'b0;
      err_overrun_set <= 1'b0;
      err_arb_set <= 1'b0;
    end else begin
      a_kind <= a_kind_d; p_kind <= p_kind_d;
      a_oe_q <= a_oe_d; p_oe_q <= p_oe_d;
      a_mask_q <= a_mask_d; p_mask_q <= p_mask_d;
      a_val_q <= a_val_d; p_val_q <= p_val_d;
      a_mode_q <= a_mode_d; p_mode_q <= p_mode_d;
      a_nm1_q <= a_nm1_d; p_nm1_q <= p_nm1_d;
      a_data_q <= a_data_d; p_data_q <= p_data_d;
      a_done_q <= a_done_d; a_res_q <= a_res_d;
      a_msb_q <= a_msb_d; p_msb_q <= p_msb_d;
      a_in_t_q <= a_in_t_d; p_in_t_q <= p_in_t_d;
      a_lp_q <= a_lp_d; p_lp_q <= p_lp_d;
      miss <= miss_d;
      res_valid <= res_valid_d; result <= result_d;
      drv_val_q <= drv_val_d;
      drv_oe_q <= drv_oe_d;
      stretching_q <= stretching_d;
      uio_out <= map_out;
      uio_oe  <= map_oe;
      err_map_set <= map_err;
      err_overrun_set <= overrun_pulse;
      err_arb_set <= arb_pulse;
    end
  end
endmodule

`default_nettype wire
