// Toolchain smoke test only. No board pin assignments; never program this bitstream.
module smoke_top(input wire clk, input wire reset_n, output wire led);
    reg [23:0] counter;
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) counter <= 24'd0;
        else counter <= counter + 1'b1;
    end
    assign led = counter[23];
endmodule
