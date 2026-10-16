`default_nettype none

// tick_issue — PC, decode, r0–r3, flags, ALU, WAIT/stall, MTS/MFS, posts.
// Issues only when run && ctx_enable. IN / IN.T / full-mask SET for Stage 2a.
module tick_issue (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        run,
    input  wire        ctx_enable,
    input  wire [15:0] instr,
    input  wire [1:0]  at_a_kind,
    input  wire [1:0]  at_p_kind,
    input  wire        at_slots_full,
    input  wire        event_wait_done,
    input  wire        tick_wait_done,
    input  wire        timer_run,
    input  wire        cfg_msb_first,
    input  wire [3:0]  lp_in,
    input  wire        in_t_done,
    input  wire        in_t_bit,
    input  wire [7:0]  err_bits,
    input  wire        tx_empty,
    input  wire [9:0]  tx_rdata,
    output reg         tx_rd,
    input  wire        rx_full,
    output reg         rx_wr,
    output reg  [9:0]  rx_wdata,
    input  wire        res_valid,
    input  wire [15:0] result,
    output reg         res_take,
    output reg         miss_clear,
    output reg         err_clear,
    output reg  [7:0]  err_clear_mask,
    output reg         post_en,
    output reg  [1:0]  post_kind,
    output reg         post_oe,
    output reg  [3:0]  post_mask,
    output reg  [3:0]  post_val,
    output reg  [1:0]  post_mode,
    output reg  [3:0]  post_nm1,
    output reg  [7:0]  post_data,
    output reg         post_msb,
    output reg         post_in_t,
    output reg  [1:0]  post_lp,
    output reg         pin_we,
    output reg         pin_oe_mode,
    output reg  [3:0]  pin_mask,
    output reg  [3:0]  pin_val4,
    output reg         tcmd_start,
    output reg         tcmd_stop,
    output reg         tcmd_rearm,
    output reg         per_we,
    output reg  [1:0]  per_sel,
    output reg  [7:0]  per_wdata,
    output reg         phase_we,
    output reg         phase_hi,
    output reg  [7:0]  phase_wdata,
    output reg         msb_we,
    output reg         msb_wdata,
    output wire [5:0]  pc,
    output wire        waiting,
    output wire [4:0]  wait_mask_obs,
    output wire [1:0]  wait_tc_obs,
    output wire        pull_block_obs,
    output wire        mfs_block_obs
);
  reg [7:0] rf_q [0:3];
  reg       z_q, c_q, last_f_q, cmd_f_q;
  reg       waiting_q;
  reg [4:0] wait_mask_q;
  reg [1:0] wait_tc_q;
  reg       pull_block_q;
  reg [1:0] pull_rd_q;
  reg       mfs_block_q;
  reg [1:0] mfs_rd_q;
  reg [5:0] pc_q;

  reg [7:0] rf_d [0:3];
  reg       z_d, c_d, last_f_d, cmd_f_d;
  reg       waiting_d;
  reg [4:0] wait_mask_d;
  reg [1:0] wait_tc_d;
  reg       pull_block_d;
  reg [1:0] pull_rd_d;
  reg       mfs_block_d;
  reg [1:0] mfs_rd_d;
  reg [5:0] pc_d;
  reg [5:0] next_pc;
  reg       issued, stalled, take;
  reg [7:0] tmp;
  reg [8:0] sum;
  reg [3:0] op;
  reg [1:0] in_lp;

  assign pc             = pc_q;
  assign waiting        = waiting_q;
  assign wait_mask_obs  = wait_mask_q;
  assign wait_tc_obs    = wait_tc_q;
  assign pull_block_obs = pull_block_q;
  assign mfs_block_obs  = mfs_block_q;
  wire _unused_i = &{result[15:9], 1'b0};

  always @(*) begin : comb_issue
    for (int i = 0; i < 4; i = i + 1)
      rf_d[i] = rf_q[i];
    z_d = z_q; c_d = c_q; last_f_d = last_f_q; cmd_f_d = cmd_f_q;
    waiting_d = waiting_q;
    wait_mask_d = wait_mask_q;
    wait_tc_d = wait_tc_q;
    pull_block_d = pull_block_q;
    pull_rd_d = pull_rd_q;
    mfs_block_d = mfs_block_q;
    mfs_rd_d = mfs_rd_q;
    pc_d = pc_q;
    next_pc = pc_q + 6'd1;
    issued = 1'b0;
    stalled = 1'b0;
    take = 1'b0;
    tmp = 8'h0;
    sum = 9'h0;
    op = instr[15:12];
    in_lp = instr[10:9];

    tx_rd = 1'b0;
    rx_wr = 1'b0;
    rx_wdata = 10'h0;
    res_take = 1'b0;
    miss_clear = 1'b0;
    err_clear = 1'b0;
    err_clear_mask = 8'h0;
    post_en = 1'b0;
    post_kind = 2'd0;
    post_oe = 1'b0;
    post_mask = 4'h0;
    post_val = 4'h0;
    post_mode = 2'd0;
    post_nm1 = 4'd0;
    post_data = 8'h0;
    post_msb = cfg_msb_first;
    post_in_t = 1'b0;
    post_lp = 2'd0;
    pin_we = 1'b0;
    pin_oe_mode = 1'b0;
    pin_mask = 4'h0;
    pin_val4 = 4'h0;
    tcmd_start = 1'b0;
    tcmd_stop = 1'b0;
    tcmd_rearm = 1'b0;
    per_we = 1'b0;
    per_sel = 2'd0;
    per_wdata = 8'h0;
    phase_we = 1'b0;
    phase_hi = 1'b0;
    phase_wdata = 8'h0;
    msb_we = 1'b0;
    msb_wdata = 1'b0;

    if (run && ctx_enable) begin
      if (event_wait_done || tick_wait_done)
        waiting_d = 1'b0;

      if (in_t_done) begin
        c_d = in_t_bit;
        z_d = ~in_t_bit;
        waiting_d = 1'b0;
      end

      if (waiting_d) begin
        if (pull_block_q && !tx_empty) begin
          tmp = tx_rdata[7:0];
          rf_d[pull_rd_q] = tmp;
          last_f_d = tx_rdata[8];
          cmd_f_d = tx_rdata[9];
          z_d = (tmp == 8'h0);
          tx_rd = 1'b1;
          pull_block_d = 1'b0;
          waiting_d = 1'b0;
        end else if (mfs_block_q && res_valid) begin
          rf_d[mfs_rd_q] = result[7:0];
          c_d = result[8];
          z_d = (result[7:0] == 8'h0);
          res_take = 1'b1;
          mfs_block_d = 1'b0;
          waiting_d = 1'b0;
        end else begin
          take = 1'b0;
          if (wait_mask_q[0] && !tx_empty) take = 1'b1;
          if (wait_mask_q != 5'h0 && take && at_a_kind != 2'd3 && at_p_kind != 2'd3) begin
            waiting_d = 1'b0;
            if (wait_tc_q == 2'b01)
              tcmd_rearm = 1'b1;
            else if (wait_tc_q == 2'b10 || wait_tc_q == 2'b11)
              tcmd_stop = 1'b1;
          end
        end
      end

      if (!waiting_d) begin
        case (op)
          4'b0000: begin // SET
            if (instr[11]) begin
              if (at_slots_full) stalled = 1'b1;
              else begin
                if (!timer_run)
                  tcmd_start = 1'b1;
                post_en = 1'b1;
                post_kind = 2'd1;
                post_oe = instr[10];
                post_mask = instr[9:6];
                post_val = instr[5:2];
                issued = 1'b1;
              end
            end else begin
              pin_we = 1'b1;
              pin_oe_mode = instr[10];
              pin_mask = instr[9:6];
              pin_val4 = instr[5:2];
              issued = 1'b1;
            end
          end
          4'b0001: begin // IN / IN.T
            if (instr[11]) begin
              if (at_slots_full) stalled = 1'b1;
              else begin
                if (!timer_run)
                  tcmd_start = 1'b1;
                post_en = 1'b1;
                post_kind = 2'd2;
                post_in_t = 1'b1;
                post_lp = in_lp;
                waiting_d = 1'b1;
                wait_mask_d = 5'h10;
                issued = 1'b1;
              end
            end else begin
              c_d = lp_in[in_lp];
              z_d = ~lp_in[in_lp];
              issued = 1'b1;
            end
          end
          4'b0010: begin // WAIT
            wait_mask_d = instr[9:5];
            wait_tc_d = instr[11:10];
            if (instr[11:10] == 2'b01 || instr[11:10] == 2'b11)
              tcmd_stop = 1'b1;
            if (instr[9]) begin
              if (at_slots_full) stalled = 1'b1;
              else begin
                if (!timer_run)
                  tcmd_start = 1'b1;
                post_en = 1'b1;
                post_kind = 2'd3;
                waiting_d = 1'b1;
                issued = 1'b1;
              end
            end else begin
              waiting_d = 1'b1;
              issued = 1'b1;
            end
          end
          4'b0011: begin // JMP
            take = 1'b0;
            case (instr[11:8])
              4'd0: take = 1'b1;
              4'd1: take = z_q;
              4'd2: take = ~z_q;
              4'd3: take = c_q;
              4'd4: take = ~c_q;
              4'd13: take = tx_empty;
              // JMP ERR iff ERR register non-zero (all sticky bits).
              4'd14: take = |err_bits;
              default: take = 1'b0;
            endcase
            if (take) next_pc = instr[7:2];
            issued = 1'b1;
          end
          4'b0100: begin
            rf_d[instr[11:10]] = instr[7:0];
            z_d = (instr[7:0] == 8'h0);
            issued = 1'b1;
          end
          4'b0101: begin
            case (instr[11:9])
              3'd0: begin
                rf_d[instr[8:7]] = rf_q[instr[6:5]];
                z_d = (rf_q[instr[6:5]] == 8'h0);
              end
              3'd1: begin
                sum = {1'b0, rf_q[instr[8:7]]} + {1'b0, rf_q[instr[6:5]]};
                rf_d[instr[8:7]] = sum[7:0];
                z_d = (sum[7:0] == 8'h0);
                c_d = sum[8];
              end
              3'd7: begin
                c_d = rf_q[instr[8:7]][0];
                tmp = {1'b0, rf_q[instr[8:7]][7:1]};
                rf_d[instr[8:7]] = tmp;
                z_d = (tmp == 8'h0);
              end
              default: ;
            endcase
            issued = 1'b1;
          end
          4'b0110: begin // XFER
            if (at_slots_full) stalled = 1'b1;
            else begin
              if (!timer_run)
                tcmd_start = 1'b1;
              post_en = 1'b1;
              post_kind = 2'd2;
              post_in_t = 1'b0;
              post_mode = instr[5:4];
              post_nm1 = instr[9:6];
              post_data = rf_q[instr[11:10]];
              post_msb = cfg_msb_first;
              issued = 1'b1;
            end
          end
          4'b0111: begin // PULL
            if (tx_empty) begin
              if (instr[9]) begin
                rf_d[instr[11:10]] = 8'hFF;
                last_f_d = 1'b0; cmd_f_d = 1'b0;
                issued = 1'b1;
              end else begin
                waiting_d = 1'b1;
                pull_block_d = 1'b1;
                pull_rd_d = instr[11:10];
                wait_mask_d = 5'h0;
                issued = 1'b1;
              end
            end else begin
              tmp = tx_rdata[7:0];
              rf_d[instr[11:10]] = tmp;
              last_f_d = tx_rdata[8];
              cmd_f_d = tx_rdata[9];
              z_d = (tmp == 8'h0);
              tx_rd = 1'b1;
              issued = 1'b1;
            end
          end
          4'b1000: begin
            if (!rx_full) begin
              rx_wdata = {instr[9:8], rf_q[instr[11:10]]};
              rx_wr = 1'b1;
              issued = 1'b1;
            end else stalled = 1'b1;
          end
          4'b1001: begin // MFS
            if (instr[9:6] == 4'd0) begin
              if (!res_valid) begin
                waiting_d = 1'b1;
                mfs_block_d = 1'b1;
                mfs_rd_d = instr[11:10];
                issued = 1'b1;
              end else begin
                rf_d[instr[11:10]] = result[7:0];
                c_d = result[8];
                res_take = 1'b1;
                issued = 1'b1;
              end
            end else if (instr[9:6] == 4'd5) begin
              // ERR: map/cfg (+ miss via sticky in queue — bit0 not in err_bits)
              rf_d[instr[11:10]] = err_bits;
              z_d = (err_bits == 8'h0);
              issued = 1'b1;
            end else issued = 1'b1;
          end
          4'b1010: begin
            case (instr[9:6])
              4'd5: begin
                err_clear = 1'b1;
                err_clear_mask = rf_q[instr[11:10]];
                if (rf_q[instr[11:10]][0]) miss_clear = 1'b1;
              end
              4'd6: begin per_we = 1'b1; per_sel = 2'd0; per_wdata = rf_q[instr[11:10]]; end
              4'd7: begin per_we = 1'b1; per_sel = 2'd1; per_wdata = rf_q[instr[11:10]]; end
              4'd8: begin per_we = 1'b1; per_sel = 2'd2; per_wdata = rf_q[instr[11:10]]; end
              4'd9: begin phase_we = 1'b1; phase_hi = 1'b0; phase_wdata = rf_q[instr[11:10]]; end
              4'd10: begin phase_we = 1'b1; phase_hi = 1'b1; phase_wdata = rf_q[instr[11:10]]; end
              4'd11: begin msb_we = 1'b1; msb_wdata = rf_q[instr[11:10]][0]; end
              4'd12: next_pc = rf_q[instr[11:10]][5:0];
              default: ;
            endcase
            issued = 1'b1;
          end
          default: issued = 1'b1;
        endcase

        if (issued && !stalled)
          pc_d = next_pc;
      end
    end
  end

  always @(posedge clk or negedge rst_n) begin : seq_issue
    if (!rst_n) begin
      for (int i = 0; i < 4; i = i + 1)
        rf_q[i] <= 8'h0;
      pc_q <= 6'd0;
      z_q <= 1'b0; c_q <= 1'b0; last_f_q <= 1'b0; cmd_f_q <= 1'b0;
      waiting_q <= 1'b0; wait_mask_q <= 5'h0; wait_tc_q <= 2'b0;
      pull_block_q <= 1'b0; mfs_block_q <= 1'b0;
      pull_rd_q <= 2'd0; mfs_rd_q <= 2'd0;
    end else begin
      for (int i = 0; i < 4; i = i + 1)
        rf_q[i] <= rf_d[i];
      pc_q <= pc_d;
      z_q <= z_d; c_q <= c_d; last_f_q <= last_f_d; cmd_f_q <= cmd_f_d;
      waiting_q <= waiting_d;
      wait_mask_q <= wait_mask_d;
      wait_tc_q <= wait_tc_d;
      pull_block_q <= pull_block_d;
      pull_rd_q <= pull_rd_d;
      mfs_block_q <= mfs_block_d;
      mfs_rd_q <= mfs_rd_d;
    end
  end
endmodule

`default_nettype wire
