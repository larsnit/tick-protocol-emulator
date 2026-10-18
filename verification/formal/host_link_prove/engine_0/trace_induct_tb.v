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
  reg [0:0] PI_err_any;
  reg [0:0] PI_rst_n;
  reg [3:0] PI_host_rx_count;
  reg [7:0] PI_cfg_rdata;
  reg [3:0] PI_host_tx_count;
  reg [15:0] PI_imem_hrdata;
  reg [0:0] PI_cs_n_i;
  reg [0:0] PI_enable0;
  wire [0:0] PI_clk = clock;
  reg [0:0] PI_sclk_i;
  reg [0:0] PI_host_full;
  reg [0:0] PI_host_empty;
  reg [9:0] PI_host_rdata;
  reg [0:0] PI_mosi_i;
  host_link_formal_top UUT (
    .err_any(PI_err_any),
    .rst_n(PI_rst_n),
    .host_rx_count(PI_host_rx_count),
    .cfg_rdata(PI_cfg_rdata),
    .host_tx_count(PI_host_tx_count),
    .imem_hrdata(PI_imem_hrdata),
    .cs_n_i(PI_cs_n_i),
    .enable0(PI_enable0),
    .clk(PI_clk),
    .sclk_i(PI_sclk_i),
    .host_full(PI_host_full),
    .host_empty(PI_host_empty),
    .host_rdata(PI_host_rdata),
    .mosi_i(PI_mosi_i)
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
    // UUT.$auto$async2sync.\cc:107:execute$1729  = 1'b0;
    // UUT.$auto$async2sync.\cc:107:execute$1735  = 1'b0;
    // UUT.$auto$async2sync.\cc:107:execute$1741  = 1'b0;
    // UUT.$auto$async2sync.\cc:116:execute$1727  = 1'b1;
    // UUT.$auto$async2sync.\cc:116:execute$1733  = 1'b0;
    // UUT.$auto$async2sync.\cc:116:execute$1739  = 1'b0;
    // UUT.$auto$async2sync.\cc:116:execute$1745  = 1'b0;
    // UUT.$auto$async2sync.\cc:116:execute$1751  = 1'b0;
    UUT._witness_.anyinit_procdff_1719 = 1'b0;
    UUT._witness_.anyinit_procdff_1720 = 8'b00100000;
    UUT._witness_.anyinit_procdff_1721 = 1'b0;
    UUT.saw_reset = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1463 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1468 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1473 = 8'b00000010;
    UUT.uut._witness_.anyinit_procdff_1478 = 8'b00000001;
    UUT.uut._witness_.anyinit_procdff_1483 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1488 = 6'b000001;
    UUT.uut._witness_.anyinit_procdff_1493 = 6'b000001;
    UUT.uut._witness_.anyinit_procdff_1498 = 16'b0000000000000001;
    UUT.uut._witness_.anyinit_procdff_1503 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1508 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1513 = 10'b0000000001;
    UUT.uut._witness_.anyinit_procdff_1518 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1523 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1528 = 8'b00100000;
    UUT.uut._witness_.anyinit_procdff_1533 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1538 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1543 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1548 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1553 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1558 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1563 = 4'b1101;
    UUT.uut._witness_.anyinit_procdff_1568 = 3'b100;
    UUT.uut._witness_.anyinit_procdff_1573 = 3'b101;
    UUT.uut._witness_.anyinit_procdff_1578 = 8'b00010011;
    UUT.uut._witness_.anyinit_procdff_1583 = 8'b00010001;
    UUT.uut._witness_.anyinit_procdff_1593 = 8'b11111101;
    UUT.uut._witness_.anyinit_procdff_1598 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1603 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1608 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1613 = 8'b00000000;
    UUT.uut._witness_.anyinit_procdff_1618 = 8'b00000000;
    UUT.uut._witness_.anyinit_procdff_1623 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1628 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1638 = 8'b00000100;
    UUT.uut._witness_.anyinit_procdff_1643 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1648 = 8'b00001001;
    UUT.uut._witness_.anyinit_procdff_1653 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1658 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1663 = 8'b10000000;
    UUT.uut._witness_.anyinit_procdff_1668 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1673 = 8'b00000001;
    UUT.uut._witness_.anyinit_procdff_1678 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1683 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1688 = 8'b00000001;
    UUT.uut._witness_.anyinit_procdff_1693 = 1'b1;
    UUT.uut._witness_.anyinit_procdff_1698 = 2'b00;
    UUT.uut._witness_.anyinit_procdff_1703 = 2'b00;
    UUT.uut._witness_.anyinit_procdff_1708 = 2'b00;
    UUT.uut._witness_.anyinit_procdff_1713 = 1'b0;
    UUT.uut._witness_.anyinit_procdff_1718 = 1'b0;

    // state 0
    PI_err_any = 1'b0;
    PI_rst_n = 1'b1;
    PI_host_rx_count = 4'b0000;
    PI_cfg_rdata = 8'b00000000;
    PI_host_tx_count = 4'b0000;
    PI_imem_hrdata = 16'b0000000000000000;
    PI_cs_n_i = 1'b0;
    PI_enable0 = 1'b1;
    PI_sclk_i = 1'b0;
    PI_host_full = 1'b1;
    PI_host_empty = 1'b1;
    PI_host_rdata = 10'b0000000000;
    PI_mosi_i = 1'b1;
  end
  always @(posedge clock) begin
    // state 1
    if (cycle == 0) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00010001;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 2
    if (cycle == 1) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00000000;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000100000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 3
    if (cycle == 2) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00010001;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 4
    if (cycle == 3) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00110001;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 5
    if (cycle == 4) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00010001;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 6
    if (cycle == 5) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00001001;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 7
    if (cycle == 6) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00001000;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 8
    if (cycle == 7) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00000001;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 9
    if (cycle == 8) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00001001;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 10
    if (cycle == 9) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00001001;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000010;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 11
    if (cycle == 10) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00001001;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000100000000010;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 12
    if (cycle == 11) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00001001;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000101;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b1;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b0;
    end

    // state 13
    if (cycle == 12) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00000010;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b0000000000000010;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b1;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b0;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 14
    if (cycle == 13) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00000001;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b0000001000000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b0;
    end

    // state 15
    if (cycle == 14) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00001001;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b1000011100000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b1;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 16
    if (cycle == 15) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00000100;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b0010000100000010;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b1;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b0;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b0;
    end

    // state 17
    if (cycle == 16) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00100000;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b0000001100010000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b1;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 18
    if (cycle == 17) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b01000000;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b0000001000000100;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b1;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b0;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 19
    if (cycle == 18) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00000000;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b1000000100001000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b1;
      PI_host_full <= 1'b0;
      PI_host_empty <= 1'b0;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 20
    if (cycle == 19) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00010000;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b1000011100000010;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b0;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 21
    if (cycle == 20) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b10000000;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b0000001001000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b1;
      PI_host_full <= 1'b1;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b0;
    end

    // state 22
    if (cycle == 21) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00000000;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b1000001000000010;
      PI_cs_n_i <= 1'b1;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b1;
      PI_host_full <= 1'b0;
      PI_host_empty <= 1'b0;
      PI_host_rdata <= 10'b1000000000;
      PI_mosi_i <= 1'b0;
    end

    // state 23
    if (cycle == 22) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00100000;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b0000101100000100;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b1;
      PI_sclk_i <= 1'b1;
      PI_host_full <= 1'b0;
      PI_host_empty <= 1'b0;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b1;
    end

    // state 24
    if (cycle == 23) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b1;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00000010;
      PI_host_tx_count <= 4'b1101;
      PI_imem_hrdata <= 16'b0000100000001000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b0;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b0;
      PI_host_empty <= 1'b1;
      PI_host_rdata <= 10'b0000000010;
      PI_mosi_i <= 1'b0;
    end

    // state 25
    if (cycle == 24) begin
      PI_err_any <= 1'b0;
      PI_rst_n <= 1'b0;
      PI_host_rx_count <= 4'b0000;
      PI_cfg_rdata <= 8'b00000000;
      PI_host_tx_count <= 4'b0000;
      PI_imem_hrdata <= 16'b0000000000000000;
      PI_cs_n_i <= 1'b0;
      PI_enable0 <= 1'b0;
      PI_sclk_i <= 1'b0;
      PI_host_full <= 1'b0;
      PI_host_empty <= 1'b0;
      PI_host_rdata <= 10'b0000000000;
      PI_mosi_i <= 1'b0;
    end

    genclock <= cycle < 25;
    cycle <= cycle + 1;
  end
endmodule
