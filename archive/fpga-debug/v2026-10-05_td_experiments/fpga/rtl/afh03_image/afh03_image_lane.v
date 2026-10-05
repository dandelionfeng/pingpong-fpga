// Hardware-independent, single-clock GRAY8 image processing lane.
// Protocol/packing/register map: fpga/afh03_image/INTERFACE.md.
// s_user={timestamp_ticks[63:0],frame_id[31:0],eol,sof}.
// output user={config_tag[15:0],timestamp[63:0],frame_id[31:0],y[15:0],x[15:0],eof,eol,sof}.
module afh03_image_lane #(
    parameter MAX_WIDTH=2048, parameter MAX_HEIGHT=2048,
    parameter DEFAULT_WIDTH=640, parameter DEFAULT_HEIGHT=480
) (
    input wire clk, input wire rst_n,
    input wire cfg_valid, output wire cfg_ready,
    input wire [5:0] cfg_addr, input wire [31:0] cfg_wdata,
    output reg cfg_error, output reg cfg_pending,
    output reg stream_fault,
    input wire s_valid, output wire s_ready,
    input wire [7:0] s_data, input wire [97:0] s_user,
    output reg full_valid, input wire full_ready,
    output reg [15:0] full_data, output reg [146:0] full_user,
    output reg roi_valid, input wire roi_ready,
    output reg [7:0] roi_data, output reg [146:0] roi_user
);
    localparam [15:0] DW=DEFAULT_WIDTH, DH=DEFAULT_HEIGHT;
    // tag,H,W,roi_x,roi_y,roi_w,roi_h,flags,gain_q6,bias_signed9.
    localparam [132:0] DEFAULT_CFG = {16'd0,DH,DW,16'd0,16'd0,DW,DH,4'd0,8'd64,9'd0};
    reg [132:0] shadow_cfg, pending_cfg, active_cfg;
    reg in_frame;
    reg [15:0] x, y;
    reg [31:0] frame_id;
    reg [63:0] frame_time;
    wire sof = s_user[0];
    wire use_pending = !in_frame && sof && cfg_pending;
    wire [132:0] effective_cfg = use_pending ? pending_cfg : active_cfg;
    wire [15:0] width = effective_cfg[100:85];
    wire [15:0] height = effective_cfg[116:101];
    wire [15:0] input_x = in_frame ? x : 16'd0;
    wire [15:0] input_y = in_frame ? y : 16'd0;
    wire input_bad = (sof == in_frame) || (s_user[1] != (input_x == width-1'b1));
    wire filter_ready;
    assign s_ready = rst_n && !stream_fault && filter_ready;
    wire input_fire = s_valid && s_ready;
    assign cfg_ready = rst_n && (cfg_addr != 6'h18 || !cfg_pending);
    wire config_size_ok = shadow_cfg[100:85] != 0 && shadow_cfg[100:85] <= MAX_WIDTH
                       && shadow_cfg[116:101] != 0 && shadow_cfg[116:101] <= MAX_HEIGHT;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            shadow_cfg <= DEFAULT_CFG; pending_cfg <= DEFAULT_CFG; active_cfg <= DEFAULT_CFG;
            cfg_pending <= 0; cfg_error <= 0;
            in_frame <= 0; x <= 0; y <= 0; frame_id <= 0; frame_time <= 0;
            stream_fault <= 0;
        end else begin
            cfg_error <= 0;
            if (cfg_valid && cfg_ready) begin
                case (cfg_addr)
                    6'h00: begin shadow_cfg[100:85] <= cfg_wdata[15:0]; shadow_cfg[116:101] <= cfg_wdata[31:16]; end
                    6'h04: begin shadow_cfg[84:69] <= cfg_wdata[15:0]; shadow_cfg[68:53] <= cfg_wdata[31:16]; end
                    6'h08: begin shadow_cfg[52:37] <= cfg_wdata[15:0]; shadow_cfg[36:21] <= cfg_wdata[31:16]; end
                    6'h0c: shadow_cfg[20:17] <= {1'b0,cfg_wdata[2:0]};
                    6'h10: begin shadow_cfg[16:9] <= cfg_wdata[7:0]; shadow_cfg[8:0] <= cfg_wdata[24:16]; end
                    6'h14: shadow_cfg[132:117] <= cfg_wdata[15:0];
                    6'h18: begin
                        if (config_size_ok) begin pending_cfg <= shadow_cfg; cfg_pending <= 1; end
                        else cfg_error <= 1;
                    end
                    default: cfg_error <= 1;
                endcase
            end
            if (input_fire) begin
                if (input_bad) stream_fault <= 1;
                else begin
                    if (!in_frame) begin
                        frame_id <= s_user[33:2]; frame_time <= s_user[97:34];
                        if (cfg_pending) begin active_cfg <= pending_cfg; cfg_pending <= 0; end
                    end
                    if (input_x == width-1'b1) begin
                        x <= 0;
                        if (input_y == height-1'b1) begin y <= 0; in_frame <= 0; end
                        else begin y <= input_y+1'b1; in_frame <= 1; end
                    end else begin x <= input_x+1'b1; y <= input_y; in_frame <= 1; end
                end
            end
        end
    end

    wire [31:0] time_frame_id = !in_frame ? s_user[33:2] : frame_id;
    wire [63:0] time_frame_time = !in_frame ? s_user[97:34] : frame_time;
    wire [228:0] filter_input_user = {effective_cfg[132:117],time_frame_time,time_frame_id,effective_cfg[116:0]};
    wire f_valid, f_ready, f_sof, f_eol, f_eof;
    wire [7:0] f_raw, f_filtered;
    wire [15:0] f_x, f_y;
    wire [228:0] f_user;
    img_filter3x3 #(.MAX_WIDTH(MAX_WIDTH),.USER_WIDTH(229)) filter (
        .clk(clk),.rst_n(rst_n),.s_valid(s_valid && !stream_fault && !input_bad),
        .s_ready(filter_ready),.s_data(s_data),.s_x(input_x),.s_y(input_y),
        .s_width(width),.s_height(height),.s_user(filter_input_user),
        .m_valid(f_valid),.m_ready(f_ready),.m_raw(f_raw),.m_filtered(f_filtered),
        .m_x(f_x),.m_y(f_y),.m_sof(f_sof),.m_eol(f_eol),.m_eof(f_eof),.m_user(f_user)
    );
    wire [7:0] adjusted;
    img_luma_adjust luma (.pixel(f_user[17] ? f_filtered : f_raw),
        .gain_q6(f_user[16:9]),.offset(f_user[8:0]),.adjusted(adjusted));
    wire [16:0] roi_end_x_unclipped = {1'b0,f_user[84:69]} + {1'b0,f_user[52:37]};
    wire [16:0] roi_end_y_unclipped = {1'b0,f_user[68:53]} + {1'b0,f_user[36:21]};
    wire [16:0] roi_end_x = roi_end_x_unclipped > {1'b0,f_user[100:85]} ? {1'b0,f_user[100:85]} : roi_end_x_unclipped;
    wire [16:0] roi_end_y = roi_end_y_unclipped > {1'b0,f_user[116:101]} ? {1'b0,f_user[116:101]} : roi_end_y_unclipped;
    wire inside_roi = f_user[18] && f_x >= f_user[84:69] && {1'b0,f_x} < roi_end_x
                                    && f_y >= f_user[68:53] && {1'b0,f_y} < roi_end_y;
    wire r_sof = f_x == f_user[84:69] && f_y == f_user[68:53];
    wire r_eol = {1'b0,f_x}+17'd1 == roi_end_x;
    wire r_eof = r_eol && {1'b0,f_y}+17'd1 == roi_end_y;
    wire [143:0] coordinate_meta = {f_user[228:213],f_user[212:149],f_user[148:117],f_y,f_x};
    // Independent pending bits prevent duplicate full-frame transfers when the
    // ROI consumer stalls (and vice versa). Input advances only when both slots
    // are empty or being consumed in this cycle.
    assign f_ready = (!full_valid || full_ready) && (!roi_valid || roi_ready);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            full_valid <= 0; roi_valid <= 0; full_data <= 0; roi_data <= 0;
            full_user <= 0; roi_user <= 0;
        end else begin
            if (full_ready) full_valid <= 0;
            if (roi_ready) roi_valid <= 0;
            if (f_valid && f_ready) begin
                full_valid <= 1; roi_valid <= inside_roi;
                full_data <= {adjusted,f_raw};
                full_user <= {coordinate_meta,f_eof,f_eol,f_sof};
                roi_data <= f_user[19] ? adjusted : f_raw;
                roi_user <= {coordinate_meta,r_eof,r_eol,r_sof};
            end
        end
    end
endmodule
