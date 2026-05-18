module irq_cpu(input [31:0] irq);
endmodule

module irq_top(input spi_irq, input gpio_irq);
  reg [31:0] irq;
  wire [31:0] irq_status_rdata;

  always @* begin
    irq = 0;
    irq[6] = spi_irq;
    irq[7] = gpio_irq;
    irq_status_rdata = irq;
  end

  irq_cpu u_cpu(.irq(irq));
endmodule
