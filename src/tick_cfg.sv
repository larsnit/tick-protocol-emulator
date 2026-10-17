`default_nettype none

// tick_cfg — configuration register map (docs/isa.md §2.1).
// Flat addr: shared 0x00–0x0F, ctx0 0x10–0x2F, ctx1 0x30–0x4F (stored; unused in 2a).
// Writes to an enabled context are ignored and set ERR.CFG.
// PER/PHASE live here and are shared with MTS (timer reads these registers).
// ECFG (MTS SPR11) aliases ENGINE[7:6] and CLKCFG[1:0].
module tick_cfg (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        cfg_we,
    input  wire        cfg_re,
    input  wire [7:0]  cfg_addr,
    input  wire [7:0]  cfg_wdata,
    output reg  [7:0]  cfg_rdata,
    // MTS PER/PHASE (same registers)
    input  wire        per_we,
    input  wire [1:0]  per_sel,
    input  wire [7:0]  per_wdata,
    input  wire        phase_we,
    input  wire        phase_hi,
    input  wire [7:0]  phase_wdata,
    // MTS ECFG → ENGINE[6]/MSB, [7]/CLK_EN, CLKCFG[1]/CPHA, [0]/CPOL
    input  wire        ecfg_we,
    input  wire [7:0]  ecfg_wdata,
    // Sticky errors
    input  wire        err_map_set,
    input  wire        err_under_set,
    input  wire        err_overrun_set,
    input  wire        err_arb_set,
    input  wire        err_clear,       // MTS ERR write-1-to-clear
    input  wire [7:0]  err_clear_mask,
    output wire [7:0]  err_bits,
    // Decoded ctx0
    output wire        enable0,
    output wire [2:0]  pinmap0,
    output wire [2:0]  pinmap1,
    output wire [2:0]  pinmap2,
    output wire [2:0]  pinmap3,
    output wire [1:0]  pinmode0,
    output wire [1:0]  pinmode1,
    output wire [1:0]  pinmode2,
    output wire [1:0]  pinmode3,
    output wire [3:0]  pinidle,
    output wire [1:0]  dout_lp,
    output wire [1:0]  din_lp,
    output wire [1:0]  clk_lp,
    output wire        msb_first,
    output wire        clk_en,
    output wire        cpol,
    output wire        cpha,
    output wire        tick_src,
    output wire        tick_rise,
    output wire [1:0]  tick_pin,
    output wire [1:0]  miss_pol,
    output wire [5:0]  miss_vec,
    output wire [7:0]  default_byte,
    output wire [19:0] per_fp,
    output wire [15:0] phase,
    output wire [5:0]  base,
    output wire [5:0]  bound,
    output wire [3:0]  glitch,
    // Event selectors (store only; behaviour in 2c). Latched = TRAP[7].
    output wire [7:0]  ev0_cfg,
    output wire [7:0]  ev0_trap,
    output wire [7:0]  ev1_cfg,
    output wire [7:0]  ev1_trap,
    output wire [7:0]  ev2_cfg,
    output wire [7:0]  ev2_trap,
    output wire [7:0]  ev3_cfg,
    output wire [7:0]  ev3_trap
);
  // Shared
  reg [1:0]  enable_q;
  reg        err_map_q, err_cfg_q, err_under_q, err_overrun_q, err_arb_q;

  // Ctx0 block (offsets as in docs)
  reg [7:0]  c0_pinmap_lo, c0_pinmap_hi, c0_pinmode, c0_pinidle;
  reg [7:0]  c0_engine, c0_clkcfg, c0_tick, c0_miss, c0_default;
  reg [7:0]  c0_per_l, c0_per_m, c0_per_h;
  reg [7:0]  c0_phase_l, c0_phase_h;
  reg [7:0]  c0_base, c0_bound, c0_glitch;
  reg [7:0]  c0_ev0_cfg, c0_ev0_trap, c0_ev1_cfg, c0_ev1_trap;
  reg [7:0]  c0_ev2_cfg, c0_ev2_trap, c0_ev3_cfg, c0_ev3_trap;

  // Ctx1 storage (written/readable; unused by single-context engine in 2a/2b)
  reg [7:0]  c1_mem [0:31];

  assign enable0     = enable_q[0];
  assign pinmap0     = c0_pinmap_lo[2:0];
  assign pinmap1     = c0_pinmap_lo[6:4];
  assign pinmap2     = c0_pinmap_hi[2:0];
  assign pinmap3     = c0_pinmap_hi[6:4];
  assign pinmode0    = c0_pinmode[1:0];
  assign pinmode1    = c0_pinmode[3:2];
  assign pinmode2    = c0_pinmode[5:4];
  assign pinmode3    = c0_pinmode[7:6];
  assign pinidle     = c0_pinidle[3:0];
  assign dout_lp     = c0_engine[1:0];
  assign din_lp      = c0_engine[3:2];
  assign clk_lp      = c0_engine[5:4];
  assign msb_first   = c0_engine[6];
  assign clk_en      = c0_engine[7];
  assign cpol        = c0_clkcfg[0];
  assign cpha        = c0_clkcfg[1];
  assign tick_src    = c0_tick[0];
  assign tick_rise   = c0_tick[1];
  assign tick_pin    = c0_tick[3:2];
  assign miss_pol    = c0_miss[1:0];
  assign miss_vec    = c0_miss[7:2];
  assign default_byte = c0_default;
  assign per_fp      = {c0_per_h[3:0], c0_per_m, c0_per_l};
  assign phase       = {c0_phase_h, c0_phase_l};
  assign base        = c0_base[5:0];
  assign bound       = c0_bound[5:0];
  assign glitch      = c0_glitch[3:0];
  assign ev0_cfg     = c0_ev0_cfg;
  assign ev0_trap    = c0_ev0_trap;
  assign ev1_cfg     = c0_ev1_cfg;
  assign ev1_trap    = c0_ev1_trap;
  assign ev2_cfg     = c0_ev2_cfg;
  assign ev2_trap    = c0_ev2_trap;
  assign ev3_cfg     = c0_ev3_cfg;
  assign ev3_trap    = c0_ev3_trap;
  // bit0 MISS is OR'd in core from queue; cfg holds UNDER/OVERRUN/ARB/MAP/CFG
  assign err_bits    = {2'b0, err_cfg_q, err_map_q, err_arb_q, err_overrun_q, err_under_q, 1'b0};
  wire _unused_cfg = &{err_clear_mask[7:6], err_clear_mask[0],
                       c0_pinidle[7:4], c0_clkcfg[7:2], c0_tick[7:4],
                       c0_per_h[7:4], c0_base[7:6], c0_bound[7:6],
                       c0_glitch[7:4], ecfg_wdata[7:4], 1'b0};

  function automatic [7:0] read_c0(input [7:0] off);
    begin
      case (off)
        8'h00: read_c0 = c0_pinmap_lo;
        8'h01: read_c0 = c0_pinmap_hi;
        8'h02: read_c0 = c0_pinmode;
        8'h03: read_c0 = {4'h0, c0_pinidle[3:0]};
        8'h04: read_c0 = c0_engine;
        8'h05: read_c0 = {6'h0, c0_clkcfg[1:0]};
        8'h06: read_c0 = {4'h0, c0_tick[3:0]};
        8'h07: read_c0 = c0_miss;
        8'h08: read_c0 = c0_default;
        8'h09: read_c0 = c0_per_l;
        8'h0A: read_c0 = c0_per_m;
        8'h0B: read_c0 = {4'h0, c0_per_h[3:0]};
        8'h0C: read_c0 = c0_phase_l;
        8'h0D: read_c0 = c0_phase_h;
        8'h0E: read_c0 = {2'b0, c0_base[5:0]};
        8'h0F: read_c0 = {2'b0, c0_bound[5:0]};
        8'h10: read_c0 = c0_ev0_cfg;
        8'h11: read_c0 = c0_ev0_trap;
        8'h12: read_c0 = c0_ev1_cfg;
        8'h13: read_c0 = c0_ev1_trap;
        8'h14: read_c0 = c0_ev2_cfg;
        8'h15: read_c0 = c0_ev2_trap;
        8'h16: read_c0 = c0_ev3_cfg;
        8'h17: read_c0 = c0_ev3_trap;
        8'h18: read_c0 = {4'h0, c0_glitch[3:0]};
        default: read_c0 = 8'h00;
      endcase
    end
  endfunction

  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      enable_q   <= 2'b00;
      err_map_q  <= 1'b0;
      err_cfg_q  <= 1'b0;
      err_under_q <= 1'b0;
      err_overrun_q <= 1'b0;
      err_arb_q  <= 1'b0;
      cfg_rdata  <= 8'h00;
      c0_pinmap_lo <= 8'h10; // LP0=0, LP1=1
      c0_pinmap_hi <= 8'h32; // LP2=2, LP3=3
      c0_pinmode   <= 8'h00; // all INPUT
      c0_pinidle   <= 8'h0F;
      c0_engine    <= 8'h04; // dout=0 din=1 clk=0
      c0_clkcfg    <= 8'h00;
      c0_tick      <= 8'h00;
      c0_miss      <= 8'h00;
      c0_default   <= 8'hFF;
      c0_per_l     <= 8'h80; // PER=8.0 → 128 = 0x080
      c0_per_m     <= 8'h00;
      c0_per_h     <= 8'h00;
      c0_phase_l   <= 8'h00;
      c0_phase_h   <= 8'h00;
      c0_base      <= 8'h00;
      c0_bound     <= 8'h00; // 0 → 64
      c0_glitch    <= 8'h00;
      c0_ev0_cfg   <= 8'h00;
      c0_ev0_trap  <= 8'h00;
      c0_ev1_cfg   <= 8'h00;
      c0_ev1_trap  <= 8'h00;
      c0_ev2_cfg   <= 8'h00;
      c0_ev2_trap  <= 8'h00;
      c0_ev3_cfg   <= 8'h00;
      c0_ev3_trap  <= 8'h00;
      for (int i = 0; i < 32; i = i + 1)
        c1_mem[i] <= 8'h00;
    end else begin
      if (err_map_set)
        err_map_q <= 1'b1;
      if (err_under_set)
        err_under_q <= 1'b1;
      if (err_overrun_set)
        err_overrun_q <= 1'b1;
      if (err_arb_set)
        err_arb_q <= 1'b1;
      if (err_clear) begin
        if (err_clear_mask[1]) err_under_q <= 1'b0;
        if (err_clear_mask[2]) err_overrun_q <= 1'b0;
        if (err_clear_mask[3]) err_arb_q <= 1'b0;
        if (err_clear_mask[4]) err_map_q <= 1'b0;
        if (err_clear_mask[5]) err_cfg_q <= 1'b0;
      end

      // MTS PER/PHASE — same registers as config map
      if (per_we) begin
        case (per_sel)
          2'd0: c0_per_l <= per_wdata;
          2'd1: c0_per_m <= per_wdata;
          2'd2: c0_per_h <= {4'h0, per_wdata[3:0]};
          default: ;
        endcase
      end
      if (phase_we) begin
        if (phase_hi) c0_phase_h <= phase_wdata;
        else          c0_phase_l <= phase_wdata;
      end
      if (ecfg_we) begin
        c0_engine[6] <= ecfg_wdata[0]; // MSB_FIRST
        c0_engine[7] <= ecfg_wdata[1]; // CLK_EN
        c0_clkcfg[1] <= ecfg_wdata[2]; // CPHA
        c0_clkcfg[0] <= ecfg_wdata[3]; // CPOL
      end

      if (cfg_re) begin
        if (cfg_addr == 8'h00)
          cfg_rdata <= {6'h0, enable_q};
        else if (cfg_addr < 8'h10)
          cfg_rdata <= 8'h00;
        else if (cfg_addr < 8'h30)
          cfg_rdata <= read_c0(cfg_addr - 8'h10);
        else if (cfg_addr < 8'h50)
          cfg_rdata <= c1_mem[cfg_addr[4:0]];
        else
          cfg_rdata <= 8'h00;
      end

      if (cfg_we) begin
        if (cfg_addr == 8'h00) begin
          enable_q <= cfg_wdata[1:0];
        end else if (cfg_addr >= 8'h10 && cfg_addr < 8'h30) begin
          if (enable_q[0])
            err_cfg_q <= 1'b1;
          else begin
            case (cfg_addr - 8'h10)
              8'h00: c0_pinmap_lo <= cfg_wdata;
              8'h01: c0_pinmap_hi <= cfg_wdata;
              8'h02: c0_pinmode   <= cfg_wdata;
              8'h03: c0_pinidle   <= cfg_wdata;
              8'h04: c0_engine    <= cfg_wdata;
              8'h05: c0_clkcfg    <= cfg_wdata;
              8'h06: c0_tick      <= cfg_wdata;
              8'h07: c0_miss      <= cfg_wdata;
              8'h08: c0_default   <= cfg_wdata;
              8'h09: c0_per_l     <= cfg_wdata;
              8'h0A: c0_per_m     <= cfg_wdata;
              8'h0B: c0_per_h     <= cfg_wdata;
              8'h0C: c0_phase_l   <= cfg_wdata;
              8'h0D: c0_phase_h   <= cfg_wdata;
              8'h0E: c0_base      <= cfg_wdata;
              8'h0F: c0_bound     <= cfg_wdata;
              8'h10: c0_ev0_cfg   <= cfg_wdata;
              8'h11: c0_ev0_trap  <= cfg_wdata;
              8'h12: c0_ev1_cfg   <= cfg_wdata;
              8'h13: c0_ev1_trap  <= cfg_wdata;
              8'h14: c0_ev2_cfg   <= cfg_wdata;
              8'h15: c0_ev2_trap  <= cfg_wdata;
              8'h16: c0_ev3_cfg   <= cfg_wdata;
              8'h17: c0_ev3_trap  <= cfg_wdata;
              8'h18: c0_glitch    <= cfg_wdata;
              default: ;
            endcase
          end
        end else if (cfg_addr >= 8'h30 && cfg_addr < 8'h50) begin
          if (enable_q[1])
            err_cfg_q <= 1'b1;
          else
            c1_mem[cfg_addr[4:0]] <= cfg_wdata;
        end
      end
    end
  end
endmodule

`default_nettype wire
