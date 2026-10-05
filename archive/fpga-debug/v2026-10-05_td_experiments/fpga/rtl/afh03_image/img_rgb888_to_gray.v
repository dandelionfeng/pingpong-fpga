// RGB888 (R in [23:16]) to full-range GRAY8. Not a Bayer/RAW unpacker.
module img_rgb888_to_gray #(parameter USER_WIDTH = 98) (
    input wire clk, input wire rst_n,
    input wire s_valid, output wire s_ready,
    input wire [23:0] s_data, input wire [USER_WIDTH-1:0] s_user,
    output reg m_valid, input wire m_ready,
    output reg [7:0] m_data, output reg [USER_WIDTH-1:0] m_user
);
    wire [15:0] weighted = 16'd77 * s_data[23:16]
                        + 16'd150 * s_data[15:8]
                        + 16'd29 * s_data[7:0] + 16'd128;
    assign s_ready = !m_valid || m_ready;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin m_valid <= 0; m_data <= 0; m_user <= 0; end
        else if (s_ready) begin
            m_valid <= s_valid;
            if (s_valid) begin m_data <= weighted[15:8]; m_user <= s_user; end
        end
    end
endmodule
