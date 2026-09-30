`default_nettype none

// Tick protocol-emulator core — single context (time-multiplex of 2 deferred).
// Encoding matches model/opcodes.py. Cycle order: timer → engine → waits → issue.
// W2: queue posts are placed into the *post-tick* occupancy (ISS order).

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
    output reg         pin0_out,
    output reg         pin0_oe,
    input  wire        pin0_in,
    output wire [5:0]  dbg_pc,
    output wire        dbg_waiting,
    output wire        dbg_miss,
    output wire        dbg_tick,
    output wire        dbg_timer_run,
    output wire [1:0]  dbg_a_kind,
    output wire [1:0]  dbg_p_kind
);
  reg [15:0] imem [0:63];
  integer ii;

  reg [9:0] txfifo [0:7];
  reg [9:0] rxfifo [0:7];
  reg [2:0] tx_w, tx_r, rx_w, rx_r;
  wire tx_full  = ((tx_w + 3'd1) == tx_r);
  wire tx_empty = (tx_w == tx_r);
  wire rx_full  = ((rx_w + 3'd1) == rx_r);
  wire rx_empty = (rx_w == rx_r);
  assign host_full  = tx_full;
  assign host_empty = rx_empty;

  reg [5:0] pc;
  reg [7:0] rf [0:3];
  reg z, c, last_f, cmd_f, miss;
  reg waiting;
  reg [4:0] wait_mask;
  reg [1:0] wait_tc;
  reg pull_block;
  reg [1:0] pull_rd;
  reg mfs_block;
  reg [1:0] mfs_rd;

  reg timer_run;
  reg [19:0] accum;
  reg [15:0] phase_left;
  reg [15:0] time_cnt;
  reg tick;
  reg [19:0] per_fp;
  reg [15:0] phase_cfg;
  reg        msb_cfg;

  reg [1:0] a_kind, p_kind; // 0 empty 1 set 2 xfer 3 wait
  reg a_oe, p_oe;
  reg [3:0] a_mask, p_mask, a_val, p_val;
  reg [1:0] a_mode, p_mode;
  reg [3:0] a_nm1, p_nm1;
  reg [7:0] a_data, p_data;
  reg [3:0] a_done;
  reg [15:0] a_res;
  reg a_msb, p_msb;
  reg res_valid;
  reg [15:0] result;

  assign dbg_pc = pc;
  assign dbg_waiting = waiting;
  assign dbg_miss = miss;
  assign dbg_tick = tick;
  assign dbg_timer_run = timer_run;
  assign dbg_a_kind = a_kind;
  assign dbg_p_kind = p_kind;

  wire [15:0] instr = imem[pc];
  wire [3:0] op = instr[15:12];
  wire host_data = !tx_empty;

  always @(posedge clk or negedge rst_n) begin : main
    reg do_tick;
    reg [3:0] rem, sh;
    reg outb;
    reg [7:0] tmp;
    reg [8:0] sum;
    reg take;
    reg issued;
    reg [5:0] next_pc;
    reg stalled;
    reg had_timed;
    // Post-tick queue occupancy (blocking)
    reg [1:0] a_k, p_k;
    reg        a_oe_n, p_oe_n, a_msb_n, p_msb_n;
    reg [3:0]  a_mask_n, p_mask_n, a_val_n, p_val_n;
    reg [1:0]  a_mode_n, p_mode_n;
    reg [3:0]  a_nm1_n, p_nm1_n, a_done_n;
    reg [7:0]  a_data_n, p_data_n;
    reg [15:0] a_res_n;
    reg        slots_full_n;
    reg        xfer_done;
    reg        do_post;
    reg [1:0]  post_kind;
    reg        post_oe;
    reg [3:0]  post_mask, post_val, post_nm1;
    reg [1:0]  post_mode;
    reg [7:0]  post_data;
    reg        post_msb;
    reg        waiting_n;

    if (!rst_n) begin
      for (ii = 0; ii < 64; ii = ii + 1) imem[ii] <= 16'h0;
      for (ii = 0; ii < 4; ii = ii + 1) rf[ii] <= 8'h0;
      tx_w <= 3'd0; tx_r <= 3'd0; rx_w <= 3'd0; rx_r <= 3'd0;
      host_rdata <= 10'h0;
      pc <= 6'd0;
      z <= 1'b0; c <= 1'b0; last_f <= 1'b0; cmd_f <= 1'b0; miss <= 1'b0;
      waiting <= 1'b0; wait_mask <= 5'h0; wait_tc <= 2'b0;
      pull_block <= 1'b0; mfs_block <= 1'b0;
      timer_run <= 1'b0; accum <= 20'h0; phase_left <= 16'h0; time_cnt <= 16'h0; tick <= 1'b0;
      per_fp <= cfg_per_fp; phase_cfg <= cfg_phase; msb_cfg <= cfg_msb_first;
      a_kind <= 2'd0; p_kind <= 2'd0; res_valid <= 1'b0; result <= 16'h0;
      pin0_out <= 1'b1; pin0_oe <= 1'b0; // OE off until run
    end else begin
      tick <= 1'b0;
      if (imem_we) imem[imem_waddr] <= imem_wdata;
      if (host_wr && !tx_full) begin
        txfifo[tx_w] <= host_wdata;
        tx_w <= tx_w + 3'd1;
      end
      if (host_rd && !rx_empty) rx_r <= rx_r + 3'd1;
      host_rdata <= rxfifo[rx_r];

      if (!run) begin
        // W12: pads high-Z while the host loads / is idle
        pin0_oe <= 1'b0;
      end else begin
        do_tick = 1'b0;
        if (timer_run) begin
          time_cnt <= time_cnt + 16'd1;
          if (phase_left != 16'h0) begin
            if (phase_left == 16'd1) do_tick = 1'b1;
            phase_left <= phase_left - 16'd1;
          end else if (accum + 20'd16 >= per_fp) begin
            accum <= accum + 20'd16 - per_fp;
            do_tick = 1'b1;
          end else begin
            accum <= accum + 20'd16;
          end
        end
        tick <= do_tick;
        had_timed = (a_kind != 2'd0);
        waiting_n = waiting;

        // Snapshot queue into blocking next-state
        a_k = a_kind; p_k = p_kind;
        a_oe_n = a_oe; p_oe_n = p_oe;
        a_mask_n = a_mask; p_mask_n = p_mask;
        a_val_n = a_val; p_val_n = p_val;
        a_mode_n = a_mode; p_mode_n = p_mode;
        a_nm1_n = a_nm1; p_nm1_n = p_nm1;
        a_data_n = a_data; p_data_n = p_data;
        a_msb_n = a_msb; p_msb_n = p_msb;
        a_done_n = a_done; a_res_n = a_res;
        xfer_done = 1'b0;

        // Event-first: dequeue timed WAIT on host-data (EV0) before tick consume.
        if (waiting_n && !pull_block && !mfs_block &&
            (a_k == 2'd3 || p_k == 2'd3) && wait_mask[0] && host_data) begin
          if (a_k == 2'd3) begin
            a_k = p_k;
            a_oe_n = p_oe_n; a_mask_n = p_mask_n; a_val_n = p_val_n;
            a_mode_n = p_mode_n; a_nm1_n = p_nm1_n; a_data_n = p_data_n; a_msb_n = p_msb_n;
            a_done_n = 4'd0; a_res_n = 16'h0;
            p_k = 2'd0;
          end else begin
            p_k = 2'd0;
          end
          waiting_n = 1'b0;
          if (wait_tc == 2'b01) begin
            timer_run <= 1'b1; accum <= 20'h0; time_cnt <= 16'h0; phase_left <= phase_cfg;
          end else if (wait_tc == 2'b10 || wait_tc == 2'b11) begin
            timer_run <= 1'b0; accum <= 20'h0; phase_left <= 16'h0;
          end
        end

        if (do_tick) begin
          if (a_k == 2'd0) begin
            if (timer_run) miss <= 1'b1;
          end else if (a_k == 2'd1) begin
            if (a_mask_n[0]) begin
              if (a_oe_n) pin0_oe <= a_val_n[0];
              else begin pin0_out <= a_val_n[0]; pin0_oe <= 1'b1; end
            end
            // promote pending → active
            a_k = p_k;
            a_oe_n = p_oe_n; a_mask_n = p_mask_n; a_val_n = p_val_n;
            a_mode_n = p_mode_n; a_nm1_n = p_nm1_n; a_data_n = p_data_n; a_msb_n = p_msb_n;
            a_done_n = 4'd0; a_res_n = 16'h0;
            p_k = 2'd0;
          end else if (a_k == 2'd2) begin
            rem = a_nm1_n + 4'd1 - a_done_n;
            sh = a_msb_n ? (rem - 4'd1) : a_done_n;
            outb = a_data_n[sh[2:0]];
            if (a_mode_n == 2'd0 || a_mode_n == 2'd2) begin
              pin0_out <= outb;
              pin0_oe <= 1'b1;
            end
            if (a_mode_n == 2'd1 || a_mode_n == 2'd2) begin
              if (a_msb_n) a_res_n = {a_res_n[14:0], pin0_in};
              else a_res_n[a_done_n] = pin0_in;
            end
            if (a_done_n == a_nm1_n) begin
              xfer_done = 1'b1;
              if (a_mode_n == 2'd0) result <= {8'h0, a_data_n};
              else result <= a_res_n;
              res_valid <= 1'b1;
              a_k = p_k;
              a_oe_n = p_oe_n; a_mask_n = p_mask_n; a_val_n = p_val_n;
              a_mode_n = p_mode_n; a_nm1_n = p_nm1_n; a_data_n = p_data_n; a_msb_n = p_msb_n;
              a_done_n = 4'd0; a_res_n = 16'h0;
              p_k = 2'd0;
            end else begin
              a_done_n = a_done_n + 4'd1;
            end
          end else if (a_k == 2'd3) begin
            // Timed WAIT consumes this tick (EVF.TICK); apply tc.
            waiting_n = 1'b0;
            if (wait_tc == 2'b01) begin
              timer_run <= 1'b1; accum <= 20'h0; time_cnt <= 16'h0; phase_left <= phase_cfg;
            end else if (wait_tc == 2'b10 || wait_tc == 2'b11) begin
              timer_run <= 1'b0; accum <= 20'h0; phase_left <= 16'h0;
            end
            a_k = p_k;
            a_oe_n = p_oe_n; a_mask_n = p_mask_n; a_val_n = p_val_n;
            a_mode_n = p_mode_n; a_nm1_n = p_nm1_n; a_data_n = p_data_n; a_msb_n = p_msb_n;
            a_done_n = 4'd0; a_res_n = 16'h0;
            p_k = 2'd0;
          end
        end

        slots_full_n = (a_k != 2'd0) && (p_k != 2'd0);

        if (waiting_n) begin
          if (pull_block && !tx_empty) begin
            tmp = txfifo[tx_r][7:0];
            rf[pull_rd] <= tmp;
            last_f <= txfifo[tx_r][8];
            cmd_f <= txfifo[tx_r][9];
            z <= (tmp == 8'h0);
            tx_r <= tx_r + 3'd1;
            pull_block <= 1'b0;
            waiting_n = 1'b0;
          end else if (mfs_block && res_valid) begin
            rf[mfs_rd] <= result[7:0];
            c <= result[8];
            z <= (result[7:0] == 8'h0);
            res_valid <= 1'b0;
            mfs_block <= 1'b0;
            waiting_n = 1'b0;
          end else begin
            // Soft WAIT (events only; tick-bearing WAIT is kind=3 timed op).
            take = 1'b0;
            if (wait_mask[0] && host_data) take = 1'b1;
            if (wait_mask != 5'h0 && take && a_k != 2'd3 && p_k != 2'd3) begin
              waiting_n = 1'b0;
              if (wait_tc == 2'b01) begin
                timer_run <= 1'b1; accum <= 20'h0; time_cnt <= 16'h0; phase_left <= phase_cfg;
              end else if (wait_tc == 2'b10 || wait_tc == 2'b11) begin
                timer_run <= 1'b0; accum <= 20'h0; phase_left <= 16'h0;
              end
            end
          end
        end

        issued = 1'b0;
        stalled = 1'b0;
        next_pc = pc + 6'd1;
        do_post = 1'b0;
        post_kind = 2'd0;
        post_oe = 1'b0;
        post_mask = 4'h0;
        post_val = 4'h0;
        post_mode = 2'd0;
        post_nm1 = 4'd0;
        post_data = 8'h0;
        post_msb = msb_cfg;

        if (!waiting_n) begin
          case (op)
            4'b0000: begin // SET
              if (instr[11]) begin
                if (slots_full_n) stalled = 1'b1;
                else begin
                  if (!timer_run) begin
                    timer_run <= 1'b1; accum <= 20'h0; time_cnt <= 16'h0; phase_left <= phase_cfg;
                  end
                  do_post = 1'b1;
                  post_kind = 2'd1;
                  post_oe = instr[10];
                  post_mask = instr[9:6];
                  post_val = instr[5:2];
                  issued = 1'b1;
                end
              end else begin
                if (instr[6]) begin
                  if (instr[10]) pin0_oe <= instr[2];
                  else begin pin0_out <= instr[2]; pin0_oe <= 1'b1; end
                end
                issued = 1'b1;
              end
            end
            4'b0010: begin // WAIT
              wait_mask <= instr[9:5];
              wait_tc <= instr[11:10];
              if (instr[11:10] == 2'b01 || instr[11:10] == 2'b11) begin
                timer_run <= 1'b0; accum <= 20'h0; phase_left <= 16'h0;
              end
              if (instr[9]) begin
                // Tick bit set → post timed WAIT (kind=3)
                if (slots_full_n) stalled = 1'b1;
                else begin
                  // Ensure timer for timed WAIT (may restart after rearm/idle stop).
                  timer_run <= 1'b1; accum <= 20'h0; time_cnt <= 16'h0; phase_left <= phase_cfg;
                  do_post = 1'b1;
                  post_kind = 2'd3;
                  waiting_n = 1'b1;
                  issued = 1'b1;
                end
              end else begin
                waiting_n = 1'b1;
                issued = 1'b1;
              end
            end
            4'b0011: begin // JMP
              take = 1'b0;
              case (instr[11:8])
                4'd0: take = 1'b1;
                4'd1: take = z;
                4'd2: take = ~z;
                4'd3: take = c;
                4'd4: take = ~c;
                4'd13: take = tx_empty;
                default: take = 1'b0;
              endcase
              if (take) next_pc = instr[7:2];
              issued = 1'b1;
            end
            4'b0100: begin
              rf[instr[11:10]] <= instr[7:0];
              z <= (instr[7:0] == 8'h0);
              issued = 1'b1;
            end
            4'b0101: begin
              case (instr[11:9])
                3'd0: begin
                  rf[instr[8:7]] <= rf[instr[6:5]];
                  z <= (rf[instr[6:5]] == 8'h0);
                end
                3'd1: begin
                  sum = {1'b0, rf[instr[8:7]]} + {1'b0, rf[instr[6:5]]};
                  rf[instr[8:7]] <= sum[7:0];
                  z <= (sum[7:0] == 8'h0);
                  c <= sum[8];
                end
                3'd7: begin
                  c <= rf[instr[8:7]][0];
                  tmp = {1'b0, rf[instr[8:7]][7:1]};
                  rf[instr[8:7]] <= tmp;
                  z <= (tmp == 8'h0);
                end
                default: ;
              endcase
              issued = 1'b1;
            end
            4'b0110: begin // XFER
              if (slots_full_n) stalled = 1'b1;
              else begin
                if (!timer_run) begin
                  timer_run <= 1'b1; accum <= 20'h0; time_cnt <= 16'h0; phase_left <= phase_cfg;
                end
                do_post = 1'b1;
                post_kind = 2'd2;
                post_mode = instr[5:4];
                post_nm1 = instr[9:6];
                post_data = rf[instr[11:10]];
                post_msb = msb_cfg;
                issued = 1'b1;
              end
            end
            4'b0111: begin // PULL
              if (tx_empty) begin
                if (instr[9]) begin
                  rf[instr[11:10]] <= 8'hFF;
                  last_f <= 1'b0; cmd_f <= 1'b0;
                  issued = 1'b1;
                end else begin
                  waiting_n = 1'b1;
                  pull_block <= 1'b1;
                  pull_rd <= instr[11:10];
                  wait_mask <= 5'h0;
                  issued = 1'b1;
                end
              end else begin
                tmp = txfifo[tx_r][7:0];
                rf[instr[11:10]] <= tmp;
                last_f <= txfifo[tx_r][8];
                cmd_f <= txfifo[tx_r][9];
                z <= (tmp == 8'h0);
                tx_r <= tx_r + 3'd1;
                issued = 1'b1;
              end
            end
            4'b1000: begin
              if (!rx_full) begin
                rxfifo[rx_w] <= {instr[9:8], rf[instr[11:10]]};
                rx_w <= rx_w + 3'd1;
                issued = 1'b1;
              end else stalled = 1'b1;
            end
            4'b1001: begin
              if (instr[9:6] == 4'd0) begin
                if (!res_valid) begin
                  waiting_n = 1'b1; mfs_block <= 1'b1; mfs_rd <= instr[11:10];
                  issued = 1'b1;
                end else begin
                  rf[instr[11:10]] <= result[7:0];
                  c <= result[8];
                  res_valid <= 1'b0;
                  issued = 1'b1;
                end
              end else issued = 1'b1;
            end
            // MTS: PER / PHASE / ECFG / ERR / PC (W12)
            4'b1010: begin
              case (instr[9:6])
                4'd5: begin // ERR clear-by-1
                  if (rf[instr[11:10]][0]) miss <= 1'b0;
                end
                4'd6: per_fp[7:0] <= rf[instr[11:10]]; // PER_L
                4'd7: per_fp[15:8] <= rf[instr[11:10]]; // PER_M
                4'd8: per_fp[19:16] <= rf[instr[11:10]][3:0]; // PER_H
                4'd9: phase_cfg[7:0] <= rf[instr[11:10]]; // PHASE_L
                4'd10: phase_cfg[15:8] <= rf[instr[11:10]]; // PHASE_H
                4'd11: msb_cfg <= rf[instr[11:10]][0]; // ECFG
                4'd12: next_pc = rf[instr[11:10]][5:0]; // PC
                default: ;
              endcase
              issued = 1'b1;
            end
            default: issued = 1'b1;
          endcase

          if (do_post && !stalled) begin
            if (a_k == 2'd0) begin
              a_k = post_kind;
              if (post_kind == 2'd1) begin
                a_oe_n = post_oe; a_mask_n = post_mask; a_val_n = post_val;
              end else begin
                a_mode_n = post_mode; a_nm1_n = post_nm1; a_data_n = post_data;
                a_msb_n = post_msb; a_done_n = 4'd0; a_res_n = 16'h0;
              end
            end else begin
              p_k = post_kind;
              if (post_kind == 2'd1) begin
                p_oe_n = post_oe; p_mask_n = post_mask; p_val_n = post_val;
              end else begin
                p_mode_n = post_mode; p_nm1_n = post_nm1; p_data_n = post_data;
                p_msb_n = post_msb;
              end
            end
          end

          if (issued && !stalled) pc <= next_pc;
        end

        // Commit queue next-state
        waiting <= waiting_n;
        a_kind <= a_k;
        p_kind <= p_k;
        a_oe <= a_oe_n; p_oe <= p_oe_n;
        a_mask <= a_mask_n; p_mask <= p_mask_n;
        a_val <= a_val_n; p_val <= p_val_n;
        a_mode <= a_mode_n; p_mode <= p_mode_n;
        a_nm1 <= a_nm1_n; p_nm1 <= p_nm1_n;
        a_data <= a_data_n; p_data <= p_data_n;
        a_msb <= a_msb_n; p_msb <= p_msb_n;
        a_done <= a_done_n; a_res <= a_res_n;
      end
    end
  end
endmodule

`default_nettype wire
