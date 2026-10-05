// Two independent lanes, after camera-domain CDC/adaptation. Shared core clk.
// Packed ports: lane 0 occupies the least significant slice. No exposure pairing.
module afh03_stereo_preproc #(
    parameter MAX_WIDTH=2048, parameter MAX_HEIGHT=2048,
    parameter DEFAULT_WIDTH=640, parameter DEFAULT_HEIGHT=480
) (
    input wire clk, input wire rst_n,
    input wire cfg_valid, input wire cfg_camera, output wire cfg_ready,
    input wire [5:0] cfg_addr, input wire [31:0] cfg_wdata,
    output wire [1:0] cfg_error, cfg_pending, stream_fault,
    input wire [1:0] s_valid, output wire [1:0] s_ready,
    input wire [15:0] s_data, input wire [195:0] s_user,
    output wire [1:0] full_valid, input wire [1:0] full_ready,
    output wire [31:0] full_data, output wire [293:0] full_user,
    output wire [1:0] roi_valid, input wire [1:0] roi_ready,
    output wire [15:0] roi_data, output wire [293:0] roi_user
);
    wire [1:0] lane_cfg_ready;
    assign cfg_ready = lane_cfg_ready[cfg_camera];
    genvar i;
    generate for (i=0;i<2;i=i+1) begin: camera
        afh03_image_lane #(.MAX_WIDTH(MAX_WIDTH),.MAX_HEIGHT(MAX_HEIGHT),
            .DEFAULT_WIDTH(DEFAULT_WIDTH),.DEFAULT_HEIGHT(DEFAULT_HEIGHT)) lane (
            .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid && cfg_camera == i),
            .cfg_ready(lane_cfg_ready[i]),.cfg_addr(cfg_addr),.cfg_wdata(cfg_wdata),
            .cfg_error(cfg_error[i]),.cfg_pending(cfg_pending[i]),.stream_fault(stream_fault[i]),
            .s_valid(s_valid[i]),.s_ready(s_ready[i]),.s_data(s_data[8*i+:8]),.s_user(s_user[98*i+:98]),
            .full_valid(full_valid[i]),.full_ready(full_ready[i]),.full_data(full_data[16*i+:16]),.full_user(full_user[147*i+:147]),
            .roi_valid(roi_valid[i]),.roi_ready(roi_ready[i]),.roi_data(roi_data[8*i+:8]),.roi_user(roi_user[147*i+:147])
        );
    end endgenerate
endmodule
