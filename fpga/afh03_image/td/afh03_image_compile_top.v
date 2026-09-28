// Synthesis harness ONLY: narrows internal buses to fit package I/O limits.
// Not a camera/PCIe bridge and not a board top. Integrate afh03_stereo_preproc
// directly in the future board design. All core inputs remain controllable and
// all outputs observable so synthesis retains both complete processing lanes.
module afh03_image_compile_top (
    input wire clk, input wire rst_n,
    input wire [31:0] host_data,
    input wire [1:0] load_select, input wire load_enable,
    input wire cfg_valid, input wire cfg_camera,
    input wire [5:0] cfg_addr, output wire cfg_ready,
    input wire [1:0] s_valid, output wire [1:0] s_ready,
    input wire [1:0] full_ready, roi_ready,
    output wire [1:0] full_valid, roi_valid,
    output wire [1:0] cfg_error, cfg_pending, stream_fault,
    output reg [31:0] observation
);
    reg [15:0] pixels;
    reg [195:0] source_user;
    wire [31:0] full_data;
    wire [15:0] roi_data;
    wire [293:0] full_user, roi_user;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin pixels <= 0; source_user <= 0; end
        else if (load_enable) begin
            if (load_select == 0) pixels <= host_data[15:0];
            if (load_select == 1) source_user <= {source_user[163:0],host_data};
        end
    end
    afh03_stereo_preproc core (
        .clk(clk),.rst_n(rst_n),.cfg_valid(cfg_valid),.cfg_camera(cfg_camera),
        .cfg_addr(cfg_addr),.cfg_wdata(host_data),.cfg_ready(cfg_ready),
        .cfg_error(cfg_error),.cfg_pending(cfg_pending),.stream_fault(stream_fault),
        .s_valid(s_valid),.s_ready(s_ready),.s_data(pixels),.s_user(source_user),
        .full_valid(full_valid),.full_ready(full_ready),.full_data(full_data),.full_user(full_user),
        .roi_valid(roi_valid),.roi_ready(roi_ready),.roi_data(roi_data),.roi_user(roi_user)
    );
    wire [671:0] observed_bus = {28'd0,full_user,roi_user,full_data,roi_data,
                               full_valid,roi_valid,stream_fault,cfg_pending};
    reg [31:0] folded;
    integer i;
    always @* begin
        folded=0;
        for (i=0;i<21;i=i+1) folded=folded ^ observed_bus[32*i+:32];
    end
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) observation <= 0;
        else observation <= folded;
    end
endmodule
