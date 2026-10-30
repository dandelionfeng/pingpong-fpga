// Private ABM7/AMR7 SRAM board-test adapter, not the draft AM01 wire protocol.
// 640x360 GRAY8 -> integer Gaussian -> same-eye diff -> >threshold -> E,D,D,E.
// Previous Gaussian samples are packed nine bytes per 72-bit RAM word. This
// uses the full ERAM payload width and keeps two eyes resident without DDR IP.
module motion7_axis #(parameter W=640,H=360,N=W*H,GROUPS=N/9,
 parameter AW=$clog2(2*GROUPS)) (
 input wire clk,rst_n,
 input wire [127:0] s_data,input wire s_valid,output wire s_ready,
 output wire [127:0] m_data,output wire m_valid,input wire m_ready,
 output wire m_last,output reg fault
);
 localparam HEADER0=0,HEADER1=1,FEED=2,DRAIN=3,FAULT=4;
 localparam [31:0] PAYLOAD_BYTES=N/8;
 localparam [15:0] IMAGE_W=W,IMAGE_H=H;
 reg [2:0] state;
 reg start,eye,ref_valid;
 reg [1:0] references;
 reg [31:0] config_tag,last_config;
 reg [63:0] pair_id,timestamp_ns,ref_id,ids[0:1];
 reg [7:0] threshold;
 reg [127:0] input_word;
 reg have_word;
 reg [3:0] input_lane;
 reg [31:0] input_count;
 wire input_valid=state==FEED && have_word;
 wire input_ready;
 assign s_ready=(state==HEADER0 || state==HEADER1 ||
                  (state==FEED && !have_word && input_count<N));
 wire gv,gr,gl;wire [7:0] gd;
 gaussian_stream #(.W(W),.H(H)) gaussian(
  .clk(clk),.rst_n(rst_n),.start(start),.abort_frame(1'b0),
  .in_valid(input_valid),.in_ready(input_ready),
  .in_data(input_word[8*input_lane+:8]),.out_valid(gv),.out_ready(gr),
  .out_data(gd),.out_x(),.out_y(),.out_last(gl));
 (* ram_style="bram" *) reg [71:0] history[0:2*GROUPS-1];
 reg [71:0] previous_word,current_word;
 reg [AW-1:0] group_addr;
 reg [3:0] group_lane;
 wire history_first=s_valid && s_ready && state==HEADER1;
 wire history_next=gv && gr && group_lane==8 && !gl;
 wire [AW-1:0] history_read_addr=history_first ? (s_data[64] ? GROUPS:0):group_addr+1'b1;
 // Keep RAM ports in a reset-free clocked block so TD can infer ERAM rather
 // than turn the frame store into distributed LUT RAM. Valid bits hide stale
 // contents after reset; RAM data itself never needs clearing.
 always @(posedge clk) begin
  if(history_first || history_next) previous_word<=history[history_read_addr];
  if(gv && gr && group_lane==8) history[group_addr]<={gd,current_word[63:0]};
 end
 wire [7:0] previous_pixel=previous_word[8*group_lane+:8];
 // Separate the wide frame-RAM selection from subtraction/threshold. Without
 // this elastic register TD routes RAM -> byte mux -> absdiff -> threshold ->
 // morphology RAM as one path, exceeding the PCIe user clock's 8ns period.
 reg sample_valid,sample_last;
 reg [7:0] current_sample,previous_sample;
 wire [7:0] difference=current_sample>=previous_sample ? current_sample-previous_sample:previous_sample-current_sample;
 wire threshold_bit=ref_valid && difference>threshold;
 wire [4:0] v,r,last;
 wire [4:0] pixel;
 assign v[0]=sample_valid;assign gr=!sample_valid || r[0];
 assign pixel[0]=threshold_bit;assign last[0]=sample_last;
 genvar stage;
 generate for(stage=0;stage<4;stage=stage+1) begin: morphology
  binary_morph_stream #(.W(W),.H(H),.DILATE(stage==1 || stage==2)) core(
   .clk(clk),.rst_n(rst_n),.start(start),.in_valid(v[stage]),
   .in_ready(r[stage]),.in_data(pixel[stage]),.out_valid(v[stage+1]),
   .out_ready(r[stage+1]),.out_data(pixel[stage+1]),.out_last(last[stage+1]));
 end endgenerate
 reg [6:0] mask_lane;
 reg [127:0] mask_word,payload;
 reg payload_valid,payload_last,responding;
 reg [1:0] response_header;
 assign m_valid=responding && (response_header!=3 || payload_valid);
 assign m_last=responding && response_header==3 && payload_valid && payload_last;
 assign m_data=response_header==0 ? {pair_id,config_tag,32'h37524d41}:
               response_header==1 ? {ref_id,timestamp_ns}:
               response_header==2 ? {32'd1,PAYLOAD_BYTES,IMAGE_H,IMAGE_W,threshold,8'd0,7'd0,ref_valid,7'd0,eye}:payload;
 wire payload_take=m_valid && m_ready && response_header==3;
 assign r[4]=!payload_valid || payload_take;
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n) begin
   state<=HEADER0;start<=0;eye<=0;ref_valid<=0;references<=0;
   config_tag<=0;last_config<=0;pair_id<=0;timestamp_ns<=0;ref_id<=0;
   ids[0]<=0;ids[1]<=0;threshold<=12;input_word<=0;have_word<=0;
   input_lane<=0;input_count<=0;group_addr<=0;group_lane<=0;
   current_word<=0;mask_lane<=0;mask_word<=0;
   payload<=0;payload_valid<=0;payload_last<=0;responding<=0;
   response_header<=0;fault<=0;
   sample_valid<=0;sample_last<=0;current_sample<=0;previous_sample<=0;
  end else begin
   start<=0;
   if(gr) begin
    sample_valid<=gv;
    if(gv) begin current_sample<=gd;previous_sample<=ref_valid ? previous_pixel:0;sample_last<=gl;end
   end
   if(s_valid && s_ready) begin
    case(state)
     HEADER0: begin
      if(s_data[31:0]!=32'h374d4241) begin state<=FAULT;fault<=1;references<=0;end
      else begin pair_id<=s_data[127:64];config_tag<=s_data[63:32];state<=HEADER1;end
     end
     HEADER1: begin
      timestamp_ns<=s_data[63:0];eye<=s_data[64];threshold<=s_data[79:72];
      ref_valid<=config_tag==last_config && !s_data[80] && references[s_data[64]];
      ref_id<=config_tag==last_config && !s_data[80] && references[s_data[64]] ? ids[s_data[64]]:0;
      if(config_tag!=last_config || s_data[80]) references<=0;
      last_config<=config_tag;
      group_addr<=s_data[64] ? GROUPS:0;
      // A synchronous read precedes the first Gaussian output by at least a line.
      group_lane<=0;current_word<=0;start<=1;state<=FEED;
      input_count<=0;input_lane<=0;have_word<=0;
      mask_lane<=0;mask_word<=0;payload_valid<=0;
      responding<=1;response_header<=0;
     end
     FEED: begin input_word<=s_data;input_lane<=0;have_word<=1;end
    endcase
   end
   if(input_valid && input_ready) begin
    input_count<=input_count+1;
    if(input_lane==15) have_word<=0;else input_lane<=input_lane+1;
    if(input_count==N-1) begin state<=DRAIN;have_word<=0;end
   end
   if(gv && gr) begin
    current_word[8*group_lane+:8]<=gd;
    if(group_lane==8) begin
     group_addr<=group_addr+1'b1;group_lane<=0;
    end else group_lane<=group_lane+1'b1;
   end
   if(payload_take) payload_valid<=0;
   if(v[4] && r[4]) begin
    mask_word[mask_lane]<=pixel[4];
    if(mask_lane==127) begin
     payload<={pixel[4],mask_word[126:0]};payload_last<=last[4];
     payload_valid<=1;mask_lane<=0;
    end else mask_lane<=mask_lane+1'b1;
   end
   if(m_valid && m_ready) begin
    if(response_header!=3) response_header<=response_header+1'b1;
    else if(payload_last) begin
     responding<=0;state<=HEADER0;references[eye]<=1;ids[eye]<=pair_id;
    end
   end
  end
 end
endmodule
