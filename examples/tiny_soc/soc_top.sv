module soc_top #(
  parameter ADDR_WIDTH = 32,
  parameter DATA_WIDTH = 64
) (
  input  logic                  clk,
  input  logic                  rst_n,
  input  logic [ADDR_WIDTH-1:0] cpu_awaddr,
  input  logic                  cpu_awvalid,
  output logic                  cpu_awready,
  output logic [DATA_WIDTH-1:0] llc_rdata
);

  logic                 fabric_awready;
  logic [DATA_WIDTH-1:0] llc_data;

  axi_fabric #(
    .ADDR_WIDTH(ADDR_WIDTH),
    .DATA_WIDTH(DATA_WIDTH)
  ) u_fabric (
    .clk(clk),
    .rst_n(rst_n),
    .m_awaddr(cpu_awaddr),
    .m_awvalid(cpu_awvalid),
    .m_awready(fabric_awready),
    .s_awaddr(),
    .s_awvalid(),
    .s_awready(1'b1)
  );

  llc_slice #(
    .DATA_WIDTH(DATA_WIDTH)
  ) u_llc (
    .clk(clk),
    .rst_n(rst_n),
    .req_valid(cpu_awvalid),
    .rdata(llc_data)
  );

  assign cpu_awready = fabric_awready;
  assign llc_rdata = llc_data;

endmodule
