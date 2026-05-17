module axi_fabric #(
  parameter ADDR_WIDTH = 32,
  parameter DATA_WIDTH = 64
) (
  input  logic                  clk,
  input  logic                  rst_n,
  input  logic [ADDR_WIDTH-1:0] m_awaddr,
  input  logic                  m_awvalid,
  output logic                  m_awready,
  output logic [ADDR_WIDTH-1:0] s_awaddr,
  output logic                  s_awvalid,
  input  logic                  s_awready
);

  assign s_awaddr = m_awaddr;
  assign s_awvalid = m_awvalid;
  assign m_awready = s_awready;

endmodule
