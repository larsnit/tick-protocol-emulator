`ifndef VERILATOR
module testbench;
  reg [4095:0] vcdfile;
  reg clock;
`else
module testbench(input clock, output reg genclock);
  initial genclock = 1;
`endif
  reg genclock = 1;
  reg [31:0] cycle = 0;
  reg [9:0] PI_host_wdata;
  reg [0:0] PI_pin0_in;
  reg [5:0] PI_imem_waddr;
  reg [0:0] PI_run;
  reg [0:0] PI_imem_we;
  reg [0:0] PI_rst_n;
  reg [15:0] PI_imem_wdata;
  wire [0:0] PI_clk = clock;
  reg [0:0] PI_host_rd;
  reg [0:0] PI_host_wr;
  tick_formal_top UUT (
    .host_wdata(PI_host_wdata),
    .pin0_in(PI_pin0_in),
    .imem_waddr(PI_imem_waddr),
    .run(PI_run),
    .imem_we(PI_imem_we),
    .rst_n(PI_rst_n),
    .imem_wdata(PI_imem_wdata),
    .clk(PI_clk),
    .host_rd(PI_host_rd),
    .host_wr(PI_host_wr)
  );
`ifndef VERILATOR
  initial begin
    if ($value$plusargs("vcd=%s", vcdfile)) begin
      $dumpfile(vcdfile);
      $dumpvars(0, testbench);
    end
    #5 clock = 0;
    while (genclock) begin
      #5 clock = 0;
      #5 clock = 1;
    end
  end
`endif
  initial begin
`ifndef VERILATOR
    #1;
`endif
    // UUT.$auto$async2sync.\cc:107:execute$9124  = 1'b0;
    // UUT.$auto$async2sync.\cc:107:execute$9142  = 1'b0;
    // UUT.$auto$async2sync.\cc:116:execute$9128  = 1'b1;
    // UUT.$auto$async2sync.\cc:116:execute$9134  = 1'b1;
    // UUT.$auto$async2sync.\cc:116:execute$9140  = 1'b1;
    // UUT.$auto$async2sync.\cc:116:execute$9146  = 1'b1;
    UUT._witness_.anyinit_procdff_8926 = 1'b0;
    UUT.saw_reset = 1'b0;
    UUT.uut._witness_.anyinit_procdff_7828 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_7833 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_7838 = 10'b0000000010;
    UUT.uut._witness_.anyinit_procdff_7843 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_7848 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_7858 = 3'b100;
    UUT.uut._witness_.anyinit_procdff_7863 = 3'b000;
    UUT.uut._witness_.anyinit_procdff_7868 = 3'b011;
    UUT.uut._witness_.anyinit_procdff_7873 = 3'b010;
    UUT.uut._witness_.anyinit_procdff_7878 = 6'b000000;
    UUT.uut._witness_.anyinit_procdff_7893 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_7898 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_7903 = 5'b00001;
    UUT.uut._witness_.anyinit_procdff_7908 = 2'b00;
    UUT.uut._witness_.anyinit_procdff_7913 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_7925 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_7937 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_7942 = 20'b00000000010001000000;
    UUT.uut._witness_.anyinit_procdff_7947 = 16'b0000000000000000;
    UUT.uut._witness_.anyinit_procdff_7957 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_7962 = 2'b00;
    UUT.uut._witness_.anyinit_procdff_7967 = 2'b00;
    UUT.uut._witness_.anyinit_procdff_8084 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_8089 = 16'b0000000100000000;
    UUT.uut._witness_.anyinit_procdff_8188 = 16'b0000010000000000;
    UUT.uut._witness_.anyinit_procdff_8193 = 16'b0001001000000000;
    UUT.uut._witness_.anyinit_procdff_8198 = 16'b0000010100000000;
    UUT.uut._witness_.anyinit_procdff_8203 = 16'b0001010100000000;
    UUT.uut._witness_.anyinit_procdff_8208 = 16'b0001010100000000;
    UUT.uut._witness_.anyinit_procdff_8213 = 16'b0001001000000000;
    UUT.uut._witness_.anyinit_procdff_8218 = 16'b0001000000000000;
    UUT.uut._witness_.anyinit_procdff_8223 = 16'b0100010100000000;
    UUT.uut._witness_.anyinit_procdff_8228 = 16'b0001011000000000;
    UUT.uut._witness_.anyinit_procdff_8233 = 16'b0000011000000000;
    UUT.uut._witness_.anyinit_procdff_8238 = 16'b0100000100000000;
    UUT.uut._witness_.anyinit_procdff_8243 = 16'b1000000100000000;
    UUT.uut._witness_.anyinit_procdff_8248 = 16'b0000010100000000;
    UUT.uut._witness_.anyinit_procdff_8253 = 16'b0001010100000000;
    UUT.uut._witness_.anyinit_procdff_8258 = 16'b0000010000000000;
    UUT.uut._witness_.anyinit_procdff_8263 = 16'b1000000000000000;
    UUT.uut._witness_.anyinit_procdff_8268 = 16'b0100010100000000;
    UUT.uut._witness_.anyinit_procdff_8273 = 16'b1000000100000000;
    UUT.uut._witness_.anyinit_procdff_8278 = 16'b0000000100000000;
    UUT.uut._witness_.anyinit_procdff_8283 = 16'b0000000100000000;
    UUT.uut._witness_.anyinit_procdff_8288 = 16'b0000000001000000;
    UUT.uut._witness_.anyinit_procdff_8293 = 16'b0001000000000000;
    UUT.uut._witness_.anyinit_procdff_8298 = 16'b1000001000000000;
    UUT.uut._witness_.anyinit_procdff_8303 = 16'b0100000000000000;
    UUT.uut._witness_.anyinit_procdff_8308 = 16'b0001000100000000;
    UUT.uut._witness_.anyinit_procdff_8313 = 16'b0001011000000000;
    UUT.uut._witness_.anyinit_procdff_8318 = 16'b0001011000000000;
    UUT.uut._witness_.anyinit_procdff_8323 = 16'b0001001000000000;
    UUT.uut._witness_.anyinit_procdff_8328 = 16'b0010000100000000;
    UUT.uut._witness_.anyinit_procdff_8333 = 16'b0001000000000000;
    UUT.uut._witness_.anyinit_procdff_8338 = 16'b0001001000000000;
    UUT.uut._witness_.anyinit_procdff_8343 = 16'b0001010000000000;
    UUT.uut._witness_.anyinit_procdff_8348 = 16'b0001010100000000;
    UUT.uut._witness_.anyinit_procdff_8353 = 16'b0000011000000000;
    UUT.uut._witness_.anyinit_procdff_8358 = 16'b0010000000000000;
    UUT.uut._witness_.anyinit_procdff_8363 = 16'b0010000100000000;
    UUT.uut._witness_.anyinit_procdff_8368 = 16'b0010000100000000;
    UUT.uut._witness_.anyinit_procdff_8373 = 16'b0001000100000000;
    UUT.uut._witness_.anyinit_procdff_8378 = 16'b0010000100000000;
    UUT.uut._witness_.anyinit_procdff_8383 = 16'b0001000100000000;
    UUT.uut._witness_.anyinit_procdff_8388 = 16'b1000000100000000;
    UUT.uut._witness_.anyinit_procdff_8393 = 16'b0100001000000000;
    UUT.uut._witness_.anyinit_procdff_8398 = 16'b1000000100000000;
    UUT.uut._witness_.anyinit_procdff_8403 = 16'b0000010000000000;
    UUT.uut._witness_.anyinit_procdff_8408 = 16'b0010001000000000;
    UUT.uut._witness_.anyinit_procdff_8413 = 16'b0010010100000000;
    UUT.uut._witness_.anyinit_procdff_8418 = 16'b0100000100000000;
    UUT.uut._witness_.anyinit_procdff_8423 = 16'b0100000000000000;
    UUT.uut._witness_.anyinit_procdff_8428 = 16'b0001000100000000;
    UUT.uut._witness_.anyinit_procdff_8433 = 16'b0100010100000000;
    UUT.uut._witness_.anyinit_procdff_8438 = 16'b0001010000000000;
    UUT.uut._witness_.anyinit_procdff_8443 = 16'b0001001000000000;
    UUT.uut._witness_.anyinit_procdff_8448 = 16'b1000000000000000;
    UUT.uut._witness_.anyinit_procdff_8453 = 16'b1000000000000000;
    UUT.uut._witness_.anyinit_procdff_8458 = 16'b0000011000000000;
    UUT.uut._witness_.anyinit_procdff_8463 = 16'b0000000100000000;
    UUT.uut._witness_.anyinit_procdff_8468 = 16'b0001001000000000;
    UUT.uut._witness_.anyinit_procdff_8473 = 16'b0001001000000000;
    UUT.uut._witness_.anyinit_procdff_8478 = 16'b0100010000000000;
    UUT.uut._witness_.anyinit_procdff_8483 = 16'b0100010100000000;
    UUT.uut._witness_.anyinit_procdff_8488 = 16'b0010001000000000;
    UUT.uut._witness_.anyinit_procdff_8493 = 16'b0001000100000000;
    UUT.uut._witness_.anyinit_procdff_8498 = 16'b0000000001000000;
    UUT.uut._witness_.anyinit_procdff_8503 = 16'b0001000000000000;
    UUT.uut._witness_.anyinit_procdff_8508 = 8'b00010000;
    UUT.uut._witness_.anyinit_procdff_8513 = 8'b00010000;
    UUT.uut._witness_.anyinit_procdff_8518 = 8'b10000000;
    UUT.uut._witness_.anyinit_procdff_8523 = 8'b10000000;
    UUT.uut.a_data = 8'b10000000;
    UUT.uut.a_done = 4'b1111;
    UUT.uut.a_mask = 4'b0010;
    UUT.uut.a_mode = 2'b00;
    UUT.uut.a_msb = 1'b1;
    UUT.uut.a_nm1 = 4'b0010;
    UUT.uut.a_oe = 1'b0;
    UUT.uut.a_res = 16'b1000000000000000;
    UUT.uut.a_val = 4'b0100;
    UUT.uut.mfs_rd = 2'b00;
    UUT.uut.p_data = 8'b00000100;
    UUT.uut.p_mask = 4'b0100;
    UUT.uut.p_mode = 2'b11;
    UUT.uut.p_msb = 1'b0;
    UUT.uut.p_nm1 = 4'b0000;
    UUT.uut.p_oe = 1'b0;
    UUT.uut.p_val = 4'b0001;
    UUT.uut.pull_rd = 2'b00;
    UUT.uut.\rxfifo[0]  = 10'b1000000000;
    UUT.uut.\rxfifo[1]  = 10'b0000000010;
    UUT.uut.\rxfifo[2]  = 10'b0000000100;
    UUT.uut.\rxfifo[3]  = 10'b1000000000;
    UUT.uut.\rxfifo[4]  = 10'b0010000000;
    UUT.uut.\rxfifo[5]  = 10'b0010000000;
    UUT.uut.\rxfifo[6]  = 10'b0000010000;
    UUT.uut.\rxfifo[7]  = 10'b0100000000;
    UUT.uut.\txfifo[0]  = 10'b0000010010;
    UUT.uut.\txfifo[1]  = 10'b1000001000;
    UUT.uut.\txfifo[2]  = 10'b0100100010;
    UUT.uut.\txfifo[3]  = 10'b1000000001;
    UUT.uut.\txfifo[4]  = 10'b0000000000;
    UUT.uut.\txfifo[5]  = 10'b0000010010;
    UUT.uut.\txfifo[6]  = 10'b0010000000;
    UUT.uut.\txfifo[7]  = 10'b1000000010;

    // state 0
    PI_host_wdata = 10'b0000000011;
    PI_pin0_in = 1'b0;
    PI_imem_waddr = 6'b000100;
    PI_run = 1'b0;
    PI_imem_we = 1'b1;
    PI_rst_n = 1'b0;
    PI_imem_wdata = 16'b1000000000000000;
    PI_host_rd = 1'b0;
    PI_host_wr = 1'b0;
  end
  always @(posedge clock) begin
    // state 1
    if (cycle == 0) begin
      PI_host_wdata <= 10'b0000000010;
      PI_pin0_in <= 1'b1;
      PI_imem_waddr <= 6'b000000;
      PI_run <= 1'b0;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0000100000000000;
      PI_host_rd <= 1'b0;
      PI_host_wr <= 1'b0;
    end

    // state 2
    if (cycle == 1) begin
      PI_host_wdata <= 10'b0000010000;
      PI_pin0_in <= 1'b0;
      PI_imem_waddr <= 6'b000001;
      PI_run <= 1'b1;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0111100000010000;
      PI_host_rd <= 1'b0;
      PI_host_wr <= 1'b0;
    end

    // state 3
    if (cycle == 2) begin
      PI_host_wdata <= 10'b0000010000;
      PI_pin0_in <= 1'b1;
      PI_imem_waddr <= 6'b000010;
      PI_run <= 1'b1;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0000100100011100;
      PI_host_rd <= 1'b0;
      PI_host_wr <= 1'b0;
    end

    // state 4
    if (cycle == 3) begin
      PI_host_wdata <= 10'b0000010010;
      PI_pin0_in <= 1'b1;
      PI_imem_waddr <= 6'b000000;
      PI_run <= 1'b1;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0110110000000000;
      PI_host_rd <= 1'b0;
      PI_host_wr <= 1'b0;
    end

    // state 5
    if (cycle == 4) begin
      PI_host_wdata <= 10'b0100000010;
      PI_pin0_in <= 1'b1;
      PI_imem_waddr <= 6'b000010;
      PI_run <= 1'b1;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b1010000000010000;
      PI_host_rd <= 1'b1;
      PI_host_wr <= 1'b0;
    end

    // state 6
    if (cycle == 5) begin
      PI_host_wdata <= 10'b0000000010;
      PI_pin0_in <= 1'b0;
      PI_imem_waddr <= 6'b000010;
      PI_run <= 1'b1;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0110110000000000;
      PI_host_rd <= 1'b0;
      PI_host_wr <= 1'b0;
    end

    // state 7
    if (cycle == 6) begin
      PI_host_wdata <= 10'b0000000001;
      PI_pin0_in <= 1'b0;
      PI_imem_waddr <= 6'b000001;
      PI_run <= 1'b1;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0110110000000000;
      PI_host_rd <= 1'b0;
      PI_host_wr <= 1'b1;
    end

    // state 8
    if (cycle == 7) begin
      PI_host_wdata <= 10'b0000001000;
      PI_pin0_in <= 1'b0;
      PI_imem_waddr <= 6'b000010;
      PI_run <= 1'b1;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0011000000000010;
      PI_host_rd <= 1'b1;
      PI_host_wr <= 1'b1;
    end

    // state 9
    if (cycle == 8) begin
      PI_host_wdata <= 10'b0000000001;
      PI_pin0_in <= 1'b1;
      PI_imem_waddr <= 6'b000000;
      PI_run <= 1'b1;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0000100000000100;
      PI_host_rd <= 1'b0;
      PI_host_wr <= 1'b0;
    end

    // state 10
    if (cycle == 9) begin
      PI_host_wdata <= 10'b0000000000;
      PI_pin0_in <= 1'b0;
      PI_imem_waddr <= 6'b000111;
      PI_run <= 1'b1;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0000010010000000;
      PI_host_rd <= 1'b0;
      PI_host_wr <= 1'b0;
    end

    // state 11
    if (cycle == 10) begin
      PI_host_wdata <= 10'b0000010010;
      PI_pin0_in <= 1'b0;
      PI_imem_waddr <= 6'b000001;
      PI_run <= 1'b0;
      PI_imem_we <= 1'b1;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0000000000100000;
      PI_host_rd <= 1'b0;
      PI_host_wr <= 1'b0;
    end

    // state 12
    if (cycle == 11) begin
      PI_host_wdata <= 10'b0000000000;
      PI_pin0_in <= 1'b0;
      PI_imem_waddr <= 6'b000000;
      PI_run <= 1'b0;
      PI_imem_we <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_imem_wdata <= 16'b0000000000000000;
      PI_host_rd <= 1'b0;
      PI_host_wr <= 1'b0;
    end

    genclock <= cycle < 12;
    cycle <= cycle + 1;
  end
endmodule
