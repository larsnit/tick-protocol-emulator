`default_nettype none

// host_spi — 4-pin SPI host link (docs/isa.md Host link v0.2).
// Mode 0, MSB first. SCLK/MOSI/CS_n: 2-flop sync + edge detect.
module host_spi #(
    parameter [7:0] ID_VALUE = 8'hA1
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        sclk_i,
    input  wire        mosi_i,
    input  wire        cs_n_i,
    output reg         miso_o,
    output wire        irq_o,
    output wire        run_o,
    output reg         soft_rst_o,
    output reg         cfg_we,
    output reg         cfg_re,
    output reg  [7:0]  cfg_addr,
    output reg  [7:0]  cfg_wdata,
    input  wire [7:0]  cfg_rdata,
    output reg         imem_we,
    output reg  [5:0]  imem_waddr,
    output reg  [15:0] imem_wdata,
    output reg  [5:0]  imem_hraddr,
    input  wire [15:0] imem_hrdata,
    output reg         host_wr,
    output reg  [9:0]  host_wdata,
    input  wire        host_full,
    output reg         host_rd,
    input  wire [9:0]  host_rdata,
    input  wire        host_empty,
    input  wire [3:0]  host_tx_count,
    input  wire [3:0]  host_rx_count,
    input  wire        enable0,
    input  wire        err_any
);
  // -------- sync + edges --------
  reg [1:0] sclk_s, mosi_s, cs_s;
  reg       sclk_d, cs_d;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      sclk_s <= 2'b00;
      mosi_s <= 2'b00;
      cs_s   <= 2'b11;
      sclk_d <= 1'b0;
      cs_d   <= 1'b1;
    end else begin
      sclk_s <= {sclk_s[0], sclk_i};
      mosi_s <= {mosi_s[0], mosi_i};
      cs_s   <= {cs_s[0], cs_n_i};
      sclk_d <= sclk_s[1];
      cs_d   <= cs_s[1];
    end
  end
  wire sclk = sclk_s[1];
  wire mosi = mosi_s[1];
  wire cs_n = cs_s[1];
  wire sclk_rise =  sclk & ~sclk_d;
  wire sclk_fall = ~sclk &  sclk_d;
  wire cs_fall   = ~cs_n &  cs_d;
  wire cs_rise   =  cs_n & ~cs_d;

  // -------- CTRL / LINKERR / IRQ --------
  reg       run_q, irq_en_rx, irq_en_err;
  reg [3:0] linkerr_q; // BADCMD, OVERFLOW, IMEM_REJECTED, ABORTED
  wire      rx_avail    = ~host_empty;
  wire      linkerr_any = |linkerr_q;
  wire      irq         = (irq_en_rx & rx_avail) | (irq_en_err & (err_any | linkerr_any));
  assign irq_o = irq;
  assign run_o = run_q;

  wire [3:0] tx_free = 4'd8 - host_tx_count;
  wire [7:0] status_now = {run_q, irq, rx_avail, host_full, err_any, linkerr_any, 1'b0, 1'b1};

  // -------- FSM --------
  localparam S_IDLE   = 3'd0;
  localparam S_CMD    = 3'd1;
  localparam S_ARG    = 3'd2;
  localparam S_DUMMY  = 3'd3;
  localparam S_DATA   = 3'd4;
  localparam S_IGNORE = 3'd5;

  reg [2:0]  state;
  reg [2:0]  bit_cnt;
  reg [7:0]  rx_sr, tx_sr, status_snap;
  reg [7:0]  cmd_q, addr_q;
  reg        push_cmd, push_last_en, hold_valid;
  reg [7:0]  hold_data;
  reg        imem_hi_phase;
  reg [7:0]  imem_hi_byte;
  reg        pull_want_data; // after tag byte, next is data
  reg        pull_armed;     // tag/data pair latched
  reg        pull_valid_l;
  reg [1:0]  pull_tag_l;
  reg [7:0]  pull_data_l;
  reg        unit_open;
  reg        shared_rd;
  reg [7:0]  shared_buf;
  reg        cfg_re_pend;
  reg        cfg_re_pend2;   // extra cycle so cfg_rdata NBA is visible
  reg [7:0]  cfg_cap;
  reg        load_tx_next;   // after byte, load tx_sr from prepared source
  reg [7:0]  tx_next;
  reg        imem_hi_reload; // 1-cycle delayed HI fetch after address bump
  reg        ctrl_pend;      // defer CTRL apply until CS rise (clean RUN start)
  reg [7:0]  ctrl_pend_val;
  reg        skip_next_fall; // after arming a new TX byte, first fall must not wipe bit7

  wire cmd_push = (cmd_q[7:2] == 6'b000100); // 0x10–0x13
  // Combinational current byte (valid on the 8th rising edge before rx_sr NBA)
  wire [7:0] byte_in = {rx_sr[6:0], mosi};

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      miso_o        <= 1'b0;
      soft_rst_o    <= 1'b0;
      cfg_we        <= 1'b0;
      cfg_re        <= 1'b0;
      cfg_addr      <= 8'h00;
      cfg_wdata     <= 8'h00;
      imem_we       <= 1'b0;
      imem_waddr    <= 6'h0;
      imem_wdata    <= 16'h0;
      imem_hraddr   <= 6'h0;
      host_wr       <= 1'b0;
      host_wdata    <= 10'h0;
      host_rd       <= 1'b0;
      run_q         <= 1'b0;
      irq_en_rx     <= 1'b0;
      irq_en_err    <= 1'b0;
      linkerr_q     <= 4'h0;
      state         <= S_IDLE;
      bit_cnt       <= 3'd0;
      rx_sr         <= 8'h00;
      tx_sr         <= 8'h00;
      status_snap   <= 8'h01;
      cmd_q         <= 8'h00;
      addr_q        <= 8'h00;
      push_cmd      <= 1'b0;
      push_last_en  <= 1'b0;
      hold_valid    <= 1'b0;
      hold_data     <= 8'h00;
      imem_hi_phase <= 1'b0;
      imem_hi_byte  <= 8'h00;
      pull_want_data<= 1'b0;
      pull_armed    <= 1'b0;
      pull_valid_l  <= 1'b0;
      pull_tag_l    <= 2'b00;
      pull_data_l   <= 8'h00;
      unit_open     <= 1'b0;
      shared_rd     <= 1'b0;
      shared_buf    <= 8'h00;
      cfg_re_pend   <= 1'b0;
      cfg_re_pend2  <= 1'b0;
      cfg_cap       <= 8'h00;
      load_tx_next  <= 1'b0;
      tx_next       <= 8'h00;
      imem_hi_reload<= 1'b0;
      ctrl_pend     <= 1'b0;
      ctrl_pend_val <= 8'h00;
      skip_next_fall<= 1'b0;
    end else begin
      // default: clear one-shot strobes (load_tx_next held until sclk_fall)
      soft_rst_o   <= 1'b0;
      cfg_we       <= 1'b0;
      cfg_re       <= 1'b0;
      imem_we      <= 1'b0;
      host_wr      <= 1'b0;
      host_rd      <= 1'b0;

      if (cfg_re_pend) begin
        cfg_re_pend  <= 1'b0;
        cfg_re_pend2 <= 1'b1;
      end else if (cfg_re_pend2) begin
        cfg_cap      <= cfg_rdata;
        cfg_re_pend2 <= 1'b0;
        if (state == S_DATA && cmd_q == 8'h02) begin
          load_tx_next <= 1'b1;
          tx_next      <= cfg_rdata;
        end
      end

      if (imem_hi_reload) begin
        load_tx_next   <= 1'b1;
        tx_next        <= imem_hrdata[15:8];
        imem_hi_reload <= 1'b0;
      end

      // ===== CS fall: snapshot STATUS, start CMD =====
      if (cs_fall) begin
        status_snap    <= status_now;
        state          <= S_CMD;
        bit_cnt        <= 3'd0;
        rx_sr          <= 8'h00;
        tx_sr          <= status_now;
        miso_o         <= status_now[7];
        unit_open      <= 1'b0;
        hold_valid     <= 1'b0;
        pull_want_data <= 1'b0;
        pull_armed     <= 1'b0;
        imem_hi_phase  <= 1'b0;
      end

      // ===== CS rise: end transaction =====
      if (cs_rise) begin
        if (hold_valid) begin
          if (host_full)
            linkerr_q[1] <= 1'b1;
          else begin
            host_wr    <= 1'b1;
            host_wdata <= {push_cmd, push_last_en, hold_data};
          end
          hold_valid <= 1'b0;
        end
        if (unit_open)
          linkerr_q[3] <= 1'b1;
        unit_open      <= 1'b0;
        state          <= S_IDLE;
        bit_cnt        <= 3'd0;
        pull_armed     <= 1'b0;
        pull_want_data <= 1'b0;
        // Apply deferred CTRL (RUN takes effect on CS rise, not mid-frame)
        if (ctrl_pend) begin
          run_q      <= ctrl_pend_val[0];
          irq_en_rx  <= ctrl_pend_val[2];
          irq_en_err <= ctrl_pend_val[3];
          if (ctrl_pend_val[1])
            soft_rst_o <= 1'b1;
          ctrl_pend  <= 1'b0;
        end
      end

      // ===== Active transaction =====
      if (!cs_n && !cs_fall && !cs_rise) begin
        // --- Rising SCLK: sample MOSI ---
        if (sclk_rise) begin
          rx_sr <= byte_in;
          if (bit_cnt != 3'd7)
            bit_cnt <= bit_cnt + 3'd1;
          else begin
            bit_cnt <= 3'd0;
            // byte complete
            case (state)
              // ---------------- CMD ----------------
              S_CMD: begin
                cmd_q <= byte_in;
                if (byte_in == 8'h00) begin
                  state <= S_IDLE;
                end else if (byte_in == 8'h01 || byte_in == 8'h02 ||
                             byte_in == 8'h03 || byte_in == 8'h04) begin
                  state <= S_ARG;
                  load_tx_next <= 1'b1;
                  tx_next <= 8'h00;
                end else if (byte_in[7:2] == 6'b000100) begin
                  push_cmd     <= byte_in[1];
                  push_last_en <= byte_in[0];
                  state        <= S_DATA;
                  load_tx_next <= 1'b1;
                  tx_next      <= 8'h00;
                end else if (byte_in == 8'h20) begin
                  state        <= S_DUMMY;
                  load_tx_next <= 1'b1;
                  tx_next      <= 8'h00;
                end else begin
                  linkerr_q[0] <= 1'b1;
                  state        <= S_IGNORE;
                  load_tx_next <= 1'b1;
                  tx_next      <= 8'h00;
                end
              end

              // ---------------- ARG ----------------
              S_ARG: begin
                addr_q <= byte_in;
                if (cmd_q == 8'h01) begin
                  state <= S_DATA;
                end else if (cmd_q == 8'h02) begin
                  if ((byte_in >= 8'h01) && (byte_in <= 8'h05)) begin
                    shared_rd  <= 1'b1;
                    shared_buf <= (byte_in == 8'h01) ? {4'h0, irq_en_err, irq_en_rx, 1'b0, run_q} :
                                  (byte_in == 8'h02) ? {4'h0, tx_free} :
                                  (byte_in == 8'h03) ? {4'h0, host_rx_count} :
                                  (byte_in == 8'h04) ? {4'h0, linkerr_q} :
                                                                  ID_VALUE;
                  end else begin
                    shared_rd   <= 1'b0;
                    cfg_addr    <= byte_in;
                    cfg_re      <= 1'b1;
                    cfg_re_pend <= 1'b1;
                  end
                  state <= S_DUMMY;
                end else if (cmd_q == 8'h03) begin
                  imem_hi_phase <= 1'b0;
                  state         <= S_DATA;
                end else if (cmd_q == 8'h04) begin
                  imem_hraddr   <= byte_in[5:0];
                  imem_hi_phase <= 1'b0;
                  state         <= S_DUMMY;
                end else
                  state <= S_IGNORE;
                load_tx_next <= 1'b1;
                tx_next      <= 8'h00;
              end

              // ---------------- DUMMY ----------------
              S_DUMMY: begin
                // Arm MISO bit7 on this rising edge; skip the fall that starts
                // the first data bit so bit7 is not replaced by bit6 early.
                // tx_sr holds the full byte; falls after the skip drive [6].
                if (cmd_q == 8'h02) begin
                  if (shared_rd) begin
                    miso_o <= shared_buf[7];
                    tx_sr  <= shared_buf;
                  end else begin
                    miso_o <= cfg_cap[7];
                    tx_sr  <= cfg_cap;
                  end
                end else if (cmd_q == 8'h04) begin
                  miso_o <= imem_hrdata[15];
                  tx_sr  <= imem_hrdata[15:8];
                end else if (cmd_q == 8'h20) begin
                  if (!host_empty) begin
                    pull_valid_l <= 1'b1;
                    pull_tag_l   <= host_rdata[9:8];
                    pull_data_l  <= host_rdata[7:0];
                    pull_armed   <= 1'b1;
                    miso_o       <= 1'b1;
                    tx_sr        <= {1'b1, 5'b0, host_rdata[9:8]};
                  end else begin
                    pull_valid_l <= 1'b0;
                    pull_armed   <= 1'b0;
                    miso_o       <= 1'b0;
                    tx_sr        <= 8'h00;
                  end
                  pull_want_data <= 1'b0;
                  unit_open      <= 1'b1;
                end
                load_tx_next   <= 1'b0;
                skip_next_fall <= 1'b1;
                state          <= S_DATA;
              end

              // ---------------- DATA ----------------
              S_DATA: begin
                if (cmd_q == 8'h01) begin
                  // CFG_WRITE
                  if ((addr_q >= 8'h01) && (addr_q <= 8'h05)) begin
                    if (addr_q == 8'h01) begin
                      ctrl_pend     <= 1'b1;
                      ctrl_pend_val <= byte_in;
                    end else if (addr_q == 8'h04) begin
                      linkerr_q <= linkerr_q & ~byte_in[3:0];
                    end
                  end else begin
                    cfg_addr  <= addr_q;
                    cfg_wdata <= byte_in;
                    cfg_we    <= 1'b1;
                  end
                  addr_q <= addr_q + 8'd1;
                end else if (cmd_q == 8'h02) begin
                  // CFG_READ auto-inc: prepare next
                  addr_q <= addr_q + 8'd1;
                  if (((addr_q + 8'd1) >= 8'h01) && ((addr_q + 8'd1) <= 8'h05)) begin
                    shared_rd <= 1'b1;
                    load_tx_next <= 1'b1;
                    tx_next <= ((addr_q + 8'd1) == 8'h01) ? {4'h0, irq_en_err, irq_en_rx, 1'b0, run_q} :
                               ((addr_q + 8'd1) == 8'h02) ? {4'h0, tx_free} :
                               ((addr_q + 8'd1) == 8'h03) ? {4'h0, host_rx_count} :
                               ((addr_q + 8'd1) == 8'h04) ? {4'h0, linkerr_q} :
                                                            ID_VALUE;
                  end else begin
                    shared_rd   <= 1'b0;
                    cfg_addr    <= addr_q + 8'd1;
                    cfg_re      <= 1'b1;
                    cfg_re_pend <= 1'b1;
                    // tx_next loaded after cfg_cap settles (next byte's start via
                    // load at end of this DATA byte — host samples next byte)
                    load_tx_next <= 1'b1;
                    tx_next      <= cfg_rdata; // may be stale; corrected below
                  end
                end else if (cmd_q == 8'h03) begin
                  // IMEM_WRITE HI then LO
                  if (!imem_hi_phase) begin
                    imem_hi_byte  <= byte_in;
                    imem_hi_phase <= 1'b1;
                    unit_open     <= 1'b1;
                  end else begin
                    if (enable0)
                      linkerr_q[2] <= 1'b1;
                    else begin
                      imem_we    <= 1'b1;
                      imem_waddr <= addr_q[5:0];
                      imem_wdata <= {imem_hi_byte, byte_in};
                    end
                    addr_q        <= addr_q + 8'd1;
                    imem_hi_phase <= 1'b0;
                    unit_open     <= 1'b0;
                  end
                end else if (cmd_q == 8'h04) begin
                  // IMEM_READ: after HI out, send LO; after LO, next HI
                  if (!imem_hi_phase) begin
                    load_tx_next  <= 1'b1;
                    tx_next       <= imem_hrdata[7:0];
                    imem_hi_phase <= 1'b1;
                    unit_open     <= 1'b1;
                  end else begin
                    imem_hraddr    <= addr_q[5:0] + 6'd1;
                    addr_q         <= addr_q + 8'd1;
                    imem_hi_reload <= 1'b1; // fetch next HI next cycle
                    imem_hi_phase  <= 1'b0;
                    unit_open      <= 1'b0;
                  end
                end else if (cmd_push) begin
                  if (hold_valid) begin
                    if (host_full)
                      linkerr_q[1] <= 1'b1;
                    else begin
                      host_wr    <= 1'b1;
                      host_wdata <= {push_cmd, 1'b0, hold_data};
                    end
                  end
                  hold_data  <= byte_in;
                  hold_valid <= 1'b1;
                end else if (cmd_q == 8'h20) begin
                  if (!pull_want_data) begin
                    // finished TAGBYTE → emit DATA next
                    load_tx_next   <= 1'b1;
                    tx_next        <= pull_valid_l ? pull_data_l : 8'h00;
                    pull_want_data <= 1'b1;
                    unit_open      <= 1'b1;
                  end else begin
                    // finished DATA → consume if valid
                    if (pull_armed && pull_valid_l)
                      host_rd <= 1'b1;
                    pull_want_data <= 1'b0;
                    unit_open      <= 1'b0;
                    pull_armed     <= 1'b0;
                    // Next TAGBYTE: peek after consume (rptr updates next cy).
                    // Load zeros for now; refresh on first fall of next byte.
                    load_tx_next <= 1'b1;
                    tx_next      <= 8'h00;
                  end
                end
              end

              S_IGNORE: begin
              end

              default: ;
            endcase
          end
        end

        // --- Falling SCLK: present next MISO bit (mode 0) ---
        // load_tx_next: new byte starts on this fall → drive bit7 immediately
        //   (no skip). skip_next_fall: bit7 was armed on a rising edge → keep
        //   it through this fall. Otherwise advance to tx_sr[6].
        if (sclk_fall) begin
          if (skip_next_fall) begin
            skip_next_fall <= 1'b0;
          end else if (load_tx_next) begin
            miso_o       <= tx_next[7];
            tx_sr        <= tx_next;
            load_tx_next <= 1'b0;
          end else begin
            miso_o <= tx_sr[6];
            tx_sr  <= {tx_sr[6:0], 1'b0};
          end
        end

        // PULL: at start of TAGBYTE bit-time, refresh peek (after prior consume)
        if (cmd_q == 8'h20 && state == S_DATA && !pull_want_data &&
            bit_cnt == 3'd0 && sclk_fall && !pull_armed) begin
          if (!host_empty) begin
            pull_valid_l <= 1'b1;
            pull_tag_l   <= host_rdata[9:8];
            pull_data_l  <= host_rdata[7:0];
            pull_armed   <= 1'b1;
            tx_sr        <= {1'b1, 5'b0, host_rdata[9:8]};
            miso_o       <= 1'b1;
            unit_open    <= 1'b1;
          end else begin
            pull_valid_l <= 1'b0;
            pull_armed   <= 1'b0;
            tx_sr        <= 8'h00;
            miso_o       <= 1'b0;
          end
        end
      end
    end
  end
endmodule

`default_nettype wire
