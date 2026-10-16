`default_nettype none

// tick_queue — two-slot timed queue, tick consume, bit engine, pins, result.
// Comb block 1 (after-tick): from queue registers + tick (+ event dequeue).
// Comb block 2 (next): from after-tick + post/pin/res/miss strobes from issue.
// No always_comb reads a signal it assigns. Implements ISA §1 queue + timed ops.
module tick_queue (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        run,
    input  wire        tick,
    input  wire        timer_run,
    input  wire        pin0_in,
    input  wire        host_data,
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
    input  wire        miss_clear,
    input  wire        res_take,
    input  wire        pin_we,
    input  wire        pin_oe_mode,
    input  wire        pin_val,
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
    output reg         res_valid,
    output reg  [15:0] result,
    output reg         pin0_out,
    output reg         pin0_oe
);
  // ---- registers ----
  reg        a_oe_q, p_oe_q, a_msb_q, p_msb_q;
  reg [3:0]  a_mask_q, p_mask_q, a_val_q, p_val_q;
  reg [1:0]  a_mode_q, p_mode_q;
  reg [3:0]  a_nm1_q, p_nm1_q, a_done_q;
  reg [7:0]  a_data_q, p_data_q;
  reg [15:0] a_res_q;

  // ---- after-tick (comb block 1 outputs) ----
  reg [1:0]  at_a_k, at_p_k;
  reg        at_a_oe, at_p_oe, at_a_msb, at_p_msb;
  reg [3:0]  at_a_mask, at_p_mask, at_a_val, at_p_val;
  reg [1:0]  at_a_mode, at_p_mode;
  reg [3:0]  at_a_nm1, at_p_nm1, at_a_done;
  reg [7:0]  at_a_data, at_p_data;
  reg [15:0] at_a_res;
  reg        at_event_done, at_tick_done;
  reg        at_tcmd_stop, at_tcmd_rearm;
  reg        at_miss;
  reg        at_res_valid;
  reg [15:0] at_result;
  reg        at_pin0_out, at_pin0_oe;
  reg [3:0]  rem, sh;
  reg        outb;

  // ---- next-state (comb block 2) ----
  reg [1:0]  a_kind_d, p_kind_d;
  reg        a_oe_d, p_oe_d, a_msb_d, p_msb_d;
  reg [3:0]  a_mask_d, p_mask_d, a_val_d, p_val_d;
  reg [1:0]  a_mode_d, p_mode_d;
  reg [3:0]  a_nm1_d, p_nm1_d, a_done_d;
  reg [7:0]  a_data_d, p_data_d;
  reg [15:0] a_res_d;
  reg        miss_d, res_valid_d;
  reg [15:0] result_d;
  reg        pin0_out_d, pin0_oe_d;

  assign at_a_kind       = at_a_k;
  assign at_p_kind       = at_p_k;
  assign at_slots_full   = (at_a_k != 2'd0) && (at_p_k != 2'd0);
  assign event_wait_done = at_event_done;
  assign tick_wait_done  = at_tick_done;
  assign tcmd_stop       = at_tcmd_stop;
  assign tcmd_rearm      = at_tcmd_rearm;
  // wait_mask[4:1]: soft-WAIT events handled in issue; queue only needs EV0.
  // sh[3]: XFER subset is ≤8 bits so only sh[2:0] indexes a_data.
  wire _unused_q = &{wait_mask[4:1], sh[3], 1'b0};

  // ---- Comb 1: after-tick from registers + tick (+ event dequeue) ----
  always @(*) begin
    at_a_k = a_kind; at_p_k = p_kind;
    at_a_oe = a_oe_q; at_p_oe = p_oe_q;
    at_a_mask = a_mask_q; at_p_mask = p_mask_q;
    at_a_val = a_val_q; at_p_val = p_val_q;
    at_a_mode = a_mode_q; at_p_mode = p_mode_q;
    at_a_nm1 = a_nm1_q; at_p_nm1 = p_nm1_q;
    at_a_data = a_data_q; at_p_data = p_data_q;
    at_a_msb = a_msb_q; at_p_msb = p_msb_q;
    at_a_done = a_done_q; at_a_res = a_res_q;
    at_event_done = 1'b0;
    at_tick_done = 1'b0;
    at_tcmd_stop = 1'b0;
    at_tcmd_rearm = 1'b0;
    at_miss = miss;
    at_res_valid = res_valid;
    at_result = result;
    at_pin0_out = pin0_out;
    at_pin0_oe = pin0_oe;
    rem = 4'd0;
    sh = 4'd0;
    outb = 1'b0;

    // Comb 1: registers + tick + event dequeue only (no issue strobes).
    if (!run) begin
      at_pin0_oe = 1'b0;
    end else begin
      if (waiting && !pull_block && !mfs_block &&
          (at_a_k == 2'd3 || at_p_k == 2'd3) && wait_mask[0] && host_data) begin
        if (at_a_k == 2'd3) begin
          at_a_k = at_p_k;
          at_a_oe = at_p_oe; at_a_mask = at_p_mask; at_a_val = at_p_val;
          at_a_mode = at_p_mode; at_a_nm1 = at_p_nm1; at_a_data = at_p_data;
          at_a_msb = at_p_msb; at_a_done = 4'd0; at_a_res = 16'h0;
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
          if (timer_run)
            at_miss = 1'b1;
        end else if (at_a_k == 2'd1) begin
          if (at_a_mask[0]) begin
            if (at_a_oe) at_pin0_oe = at_a_val[0];
            else begin at_pin0_out = at_a_val[0]; at_pin0_oe = 1'b1; end
          end
          at_a_k = at_p_k;
          at_a_oe = at_p_oe; at_a_mask = at_p_mask; at_a_val = at_p_val;
          at_a_mode = at_p_mode; at_a_nm1 = at_p_nm1; at_a_data = at_p_data;
          at_a_msb = at_p_msb; at_a_done = 4'd0; at_a_res = 16'h0;
          at_p_k = 2'd0;
        end else if (at_a_k == 2'd2) begin
          rem = at_a_nm1 + 4'd1 - at_a_done;
          sh = at_a_msb ? (rem - 4'd1) : at_a_done;
          outb = at_a_data[sh[2:0]];
          if (at_a_mode == 2'd0 || at_a_mode == 2'd2) begin
            at_pin0_out = outb;
            at_pin0_oe = 1'b1;
          end
          if (at_a_mode == 2'd1 || at_a_mode == 2'd2) begin
            if (at_a_msb) at_a_res = {at_a_res[14:0], pin0_in};
            else at_a_res[at_a_done] = pin0_in;
          end
          if (at_a_done == at_a_nm1) begin
            if (at_a_mode == 2'd0) at_result = {8'h0, at_a_data};
            else at_result = at_a_res;
            at_res_valid = 1'b1;
            at_a_k = at_p_k;
            at_a_oe = at_p_oe; at_a_mask = at_p_mask; at_a_val = at_p_val;
            at_a_mode = at_p_mode; at_a_nm1 = at_p_nm1; at_a_data = at_p_data;
            at_a_msb = at_p_msb; at_a_done = 4'd0; at_a_res = 16'h0;
            at_p_k = 2'd0;
          end else begin
            at_a_done = at_a_done + 4'd1;
          end
        end else if (at_a_k == 2'd3) begin
          at_tick_done = 1'b1;
          if (wait_tc == 2'b01)
            at_tcmd_rearm = 1'b1;
          else if (wait_tc == 2'b10 || wait_tc == 2'b11)
            at_tcmd_stop = 1'b1;
          at_a_k = at_p_k;
          at_a_oe = at_p_oe; at_a_mask = at_p_mask; at_a_val = at_p_val;
          at_a_mode = at_p_mode; at_a_nm1 = at_p_nm1; at_a_data = at_p_data;
          at_a_msb = at_p_msb; at_a_done = 4'd0; at_a_res = 16'h0;
          at_p_k = 2'd0;
        end
      end
    end
  end

  // ---- Comb 2: next state = after-tick + post + issue strobes ----
  always @(*) begin
    a_kind_d = at_a_k; p_kind_d = at_p_k;
    a_oe_d = at_a_oe; p_oe_d = at_p_oe;
    a_mask_d = at_a_mask; p_mask_d = at_p_mask;
    a_val_d = at_a_val; p_val_d = at_p_val;
    a_mode_d = at_a_mode; p_mode_d = at_p_mode;
    a_nm1_d = at_a_nm1; p_nm1_d = at_p_nm1;
    a_data_d = at_a_data; p_data_d = at_p_data;
    a_msb_d = at_a_msb; p_msb_d = at_p_msb;
    a_done_d = at_a_done; a_res_d = at_a_res;
    miss_d = at_miss;
    res_valid_d = at_res_valid;
    result_d = at_result;
    pin0_out_d = at_pin0_out;
    pin0_oe_d = at_pin0_oe;

    if (miss_clear)
      miss_d = 1'b0;
    if (res_take)
      res_valid_d = 1'b0;
    if (run && pin_we) begin
      if (pin_oe_mode) pin0_oe_d = pin_val;
      else begin pin0_out_d = pin_val; pin0_oe_d = 1'b1; end
    end

    if (run && post_en) begin
      if (at_a_k == 2'd0) begin
        a_kind_d = post_kind;
        if (post_kind == 2'd1) begin
          a_oe_d = post_oe; a_mask_d = post_mask; a_val_d = post_val;
        end else begin
          a_mode_d = post_mode; a_nm1_d = post_nm1; a_data_d = post_data;
          a_msb_d = post_msb; a_done_d = 4'd0; a_res_d = 16'h0;
        end
      end else begin
        p_kind_d = post_kind;
        if (post_kind == 2'd1) begin
          p_oe_d = post_oe; p_mask_d = post_mask; p_val_d = post_val;
        end else begin
          p_mode_d = post_mode; p_nm1_d = post_nm1; p_data_d = post_data;
          p_msb_d = post_msb;
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
      miss <= 1'b0;
      res_valid <= 1'b0; result <= 16'h0;
      pin0_out <= 1'b1; pin0_oe <= 1'b0;
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
      miss <= miss_d;
      res_valid <= res_valid_d; result <= result_d;
      pin0_out <= pin0_out_d; pin0_oe <= pin0_oe_d;
    end
  end
endmodule

`default_nettype wire
