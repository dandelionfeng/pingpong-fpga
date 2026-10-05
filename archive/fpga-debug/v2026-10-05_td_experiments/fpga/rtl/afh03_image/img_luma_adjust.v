// Saturating gain/offset: round(pixel * gain_q6 / 64) + signed offset.
// gain=64, offset=0 is the identity. No model normalization or INT8 quantization.
module img_luma_adjust (
    input wire [7:0] pixel, input wire [7:0] gain_q6,
    input wire signed [8:0] offset, output wire [7:0] adjusted
);
    wire [15:0] product = pixel * gain_q6;
    wire [15:0] rounded = product + 16'd32;
    wire signed [12:0] value = $signed({3'b000, rounded[15:6]})
                             + $signed({{4{offset[8]}}, offset});
    assign adjusted = value < 0 ? 8'd0 : value > 255 ? 8'd255 : value[7:0];
endmodule
