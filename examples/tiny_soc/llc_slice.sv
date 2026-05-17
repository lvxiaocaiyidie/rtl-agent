module llc_slice #(
  parameter DATA_WIDTH = 64
) (
  input  logic                  clk,
  input  logic                  rst_n,
  input  logic                  req_valid,
  output logic [DATA_WIDTH-1:0] rdata
);

  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      rdata <= '0;
    end else if (req_valid) begin
      rdata <= {DATA_WIDTH{1'b1}};
    end
  end

endmodule
