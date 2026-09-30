`default_nettype none

// SVA properties for tick_core — bind or include in a formal wrapper.
module tick_props (
    input wire clk,
    input wire rst_n,
    input wire timer_run,
    input wire tick,
    input wire [1:0] a_kind,
    input wire miss,
    input wire [19:0] per_fp
);
  // Integer period: PER_fp must be multiple of 16 for this property.
  wire [15:0] per_cycles = per_fp[19:4];

  // miss only on empty timed stream while running
  property miss_iff;
    @(posedge clk) disable iff (!rst_n)
      tick && timer_run && (a_kind == 2'b00) |=> miss;
  endproperty
  a_miss: assert property (miss_iff);

  // No miss when a timed op is present on a tick
  property no_miss_when_busy;
    @(posedge clk) disable iff (!rst_n)
      tick && (a_kind != 2'b00) |=> !miss;
  endproperty
  a_no_miss_busy: assert property (no_miss_when_busy);

  // Tick spacing for integer PER: successive ticks PER cycles apart while running
  // (bounded observation via $past)
  reg [15:0] since_tick;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) since_tick <= 16'h0;
    else if (!timer_run) since_tick <= 16'h0;
    else if (tick) since_tick <= 16'h1;
    else if (timer_run) since_tick <= since_tick + 16'd1;
  end

  property tick_period;
    @(posedge clk) disable iff (!rst_n || !timer_run)
      tick && (since_tick != 16'h0) |-> (since_tick == per_cycles);
  endproperty
  a_tick_period: assert property (tick_period);
endmodule

`default_nettype wire
