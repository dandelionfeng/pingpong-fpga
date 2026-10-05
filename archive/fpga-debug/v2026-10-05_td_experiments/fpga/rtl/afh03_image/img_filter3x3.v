// Centered separable [1 2 1] x [1 2 1] / 16 filter, rounded to nearest.
// Replicate borders; outputs exactly width*height pixels, with unshifted x/y.
// Three inferred synchronous row RAMs; no DDR or vendor-specific primitive.
// One global pipeline enable freezes RAM reads, window and metadata on a stall.
module img_filter3x3 #(
    parameter MAX_WIDTH = 2048, parameter USER_WIDTH = 229
) (
    input wire clk, input wire rst_n,
    input wire s_valid, output wire s_ready, input wire [7:0] s_data,
    input wire [15:0] s_x, s_y, s_width, s_height,
    input wire [USER_WIDTH-1:0] s_user,
    output reg m_valid, input wire m_ready,
    output reg [7:0] m_raw, m_filtered,
    output reg [15:0] m_x, m_y,
    output reg m_sof, m_eol, m_eof,
    output reg [USER_WIDTH-1:0] m_user
);
    localparam NORMAL=2'd0, RIGHT=2'd1, BOTTOM=2'd2, BOTTOM_RIGHT=2'd3;
    function integer address_bits;
        input integer depth;
        integer n;
        begin
            address_bits=0;
            for (n=depth-1;n>0;n=n>>1) address_bits=address_bits+1;
            if (address_bits==0) address_bits=1;
        end
    endfunction
    localparam RAM_ADDR_WIDTH=address_bits(MAX_WIDTH);
    reg [1:0] state, bank, last_bank;
    reg [15:0] width_r, height_r, right_y, bottom_x;
    reg last_row;
    reg [USER_WIDTH-1:0] frame_user;
    // TD SWUG106: infer embedded block RAM rather than distributed LUT RAM.
    // Other Verilog tools may ignore the synthesis attribute.
    (* ram_style = "bram" *) reg [7:0] row0 [0:MAX_WIDTH-1];
    (* ram_style = "bram" *) reg [7:0] row1 [0:MAX_WIDTH-1];
    (* ram_style = "bram" *) reg [7:0] row2 [0:MAX_WIDTH-1];
    reg [7:0] q0, q1, q2;
    wire advance = !m_valid || m_ready;
    wire token_valid = state != NORMAL || s_valid;
    wire token_right = state == RIGHT || state == BOTTOM_RIGHT;
    wire token_bottom = state == BOTTOM || state == BOTTOM_RIGHT;
    wire [15:0] token_x = state == NORMAL ? s_x :
                         token_right ? width_r : bottom_x;
    wire [15:0] token_y = state == NORMAL ? s_y :
                         token_bottom ? height_r : right_y;
    // Coordinates were bounded at frame configuration. Keep the RAM address
    // at its physical width; a 16-bit index otherwise introduces out-of-range
    // read logic that prevents TD from packing the synchronous read register.
    wire [RAM_ADDR_WIDTH-1:0] ram_addr = token_x[RAM_ADDR_WIDTH-1:0];
    assign s_ready = rst_n && advance && state == NORMAL;

    // Synchronous read-before-write RAM ports. Contents need not be reset:
    // no previous-frame row can contribute to an emitted first-row pixel.
    always @(posedge clk) begin
        if (rst_n && advance && token_valid && !token_right) begin
            q0 <= row0[ram_addr]; q1 <= row1[ram_addr]; q2 <= row2[ram_addr];
            if (state == NORMAL) begin
                case (bank)
                    0: row0[ram_addr] <= s_data;
                    1: row1[ram_addr] <= s_data;
                    2: row2[ram_addr] <= s_data;
                endcase
            end
        end
    end

    reg p_valid, p_right, p_bottom;
    reg [1:0] p_bank;
    reg [7:0] p_pixel;
    reg [15:0] p_x, p_y, p_width, p_height;
    reg [USER_WIDTH-1:0] p_user;
    wire [7:0] previous = p_bank == 0 ? q2 : p_bank == 1 ? q0 : q1;
    wire [7:0] older = p_bank == 0 ? q1 : p_bank == 1 ? q2 : q0;
    wire [7:0] latest = p_bank == 0 ? q0 : p_bank == 1 ? q1 : q2;
    wire [7:0] mid = p_bottom ? latest : previous;
    wire [7:0] top = p_y == 1 ? mid : p_bottom ? previous : older;
    wire [7:0] bot = p_bottom ? mid : p_pixel;
    reg [7:0] tl, tc, ml, mc, bl, bc;
    wire [7:0] tr = p_right ? tc : top;
    wire [7:0] mr = p_right ? mc : mid;
    wire [7:0] br = p_right ? bc : bot;
    wire [11:0] sum = {4'd0,tl} + {3'd0,tc,1'b0} + {4'd0,tr}
                   + {3'd0,ml,1'b0} + {2'd0,mc,2'b0} + {3'd0,mr,1'b0}
                   + {4'd0,bl} + {3'd0,bc,1'b0} + {4'd0,br} + 12'd8;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            state <= NORMAL; bank <= 0; last_bank <= 0;
            width_r <= 1; height_r <= 1; right_y <= 0; bottom_x <= 0;
            last_row <= 0; frame_user <= 0;
            p_valid <= 0; p_right <= 0; p_bottom <= 0; p_bank <= 0;
            p_pixel <= 0; p_x <= 0; p_y <= 0; p_width <= 1; p_height <= 1;
            p_user <= 0; tl <= 0; tc <= 0; ml <= 0; mc <= 0; bl <= 0; bc <= 0;
            m_valid <= 0; m_raw <= 0; m_filtered <= 0; m_x <= 0; m_y <= 0;
            m_sof <= 0; m_eol <= 0; m_eof <= 0; m_user <= 0;
        end else if (advance) begin
            m_valid <= p_valid && (p_right || (p_y != 0 && p_x != 0));
            if (p_valid && (p_right || (p_y != 0 && p_x != 0))) begin
                m_raw <= mc; m_filtered <= sum[11:4];
                m_x <= p_x - 1'b1; m_y <= p_y - 1'b1;
                m_sof <= p_x == 1 && p_y == 1;
                m_eol <= p_right;
                m_eof <= p_right && p_y == p_height;
                m_user <= p_user;
            end
            if (p_valid && !p_right) begin
                tl <= p_x == 0 ? top : tc; tc <= top;
                ml <= p_x == 0 ? mid : mc; mc <= mid;
                bl <= p_x == 0 ? bot : bc; bc <= bot;
            end
            p_valid <= token_valid;
            if (token_valid) begin
                p_right <= token_right; p_bottom <= token_bottom;
                p_x <= token_x; p_y <= token_y; p_pixel <= s_data;
                p_bank <= token_bottom ? last_bank : bank;
                p_width <= state == NORMAL ? s_width : width_r;
                p_height <= state == NORMAL ? s_height : height_r;
                p_user <= state == NORMAL ? s_user : frame_user;
                case (state)
                    NORMAL: begin
                        if (s_x == 0 && s_y == 0) begin
                            width_r <= s_width; height_r <= s_height;
                            frame_user <= s_user;
                        end
                        if (s_x == s_width - 1'b1) begin
                            bank <= bank == 2 ? 0 : bank + 1'b1;
                            right_y <= s_y; last_row <= s_y == s_height-1'b1;
                            if (s_y == s_height-1'b1) last_bank <= bank;
                            if (s_y != 0) state <= RIGHT;
                            else if (s_height == 1) begin state <= BOTTOM; bottom_x <= 0; end
                        end
                    end
                    RIGHT: begin
                        state <= last_row ? BOTTOM : NORMAL; bottom_x <= 0;
                    end
                    BOTTOM: begin
                        if (bottom_x == width_r-1'b1) state <= BOTTOM_RIGHT;
                        else bottom_x <= bottom_x+1'b1;
                    end
                    BOTTOM_RIGHT: begin state <= NORMAL; bank <= 0; end
                endcase
            end
        end
    end
endmodule
