// Internal streaming/memory contract, independent of vendor PCIe/DDR pins.
// Read responses must be ordered within an epoch. Stale epochs are drained.
module motion_front3 #(parameter W=640,H=360,DEPTH=32,N=W*H,AW=$clog2(4*N),XW=$clog2(W),YW=$clog2(H+1),PW=$clog2(DEPTH)) (
 input wire clk,rst_n,
 input wire start_valid,output wire start_ready,input wire start_eye,
 input wire [63:0] start_pair_id,start_timestamp_ns,input wire [31:0] start_config,
 input wire [7:0] start_threshold,input wire commit,abort_frame,
 input wire in_valid,output wire in_ready,input wire [7:0] in_data,
 output wire mem_rd_valid,input wire mem_rd_ready,output wire [AW-1:0] mem_rd_addr,output wire [15:0] mem_rd_epoch,
 input wire mem_rsp_valid,output wire mem_rsp_ready,input wire [7:0] mem_rsp_data,input wire [15:0] mem_rsp_epoch,
 output wire mem_wr_valid,input wire mem_wr_ready,output wire [AW-1:0] mem_wr_addr,output wire [7:0] mem_wr_data,
 output reg out_valid,input wire out_ready,output reg [7:0] out_gaussian,out_difference,output reg out_mask,
 output reg [XW-1:0] out_x,output reg [YW-1:0] out_y,output reg out_last,
 output wire out_eye,output wire [63:0] out_pair_id,out_timestamp_ns,output wire [31:0] out_config,
 output wire reference_valid,output wire [63:0] reference_id,output reg done
);
 reg active,eye,bank,ref_latched,gstart;
 reg read_sent,write_sent;
 reg [1:0] reference_bits,bank_bits;
 reg [63:0] ids[0:1];reg [63:0] pair_id,timestamp_ns,ref_id;
 reg [31:0] config_tag,last_config;
 reg [7:0] threshold;reg [15:0] epoch;
 wire gv,gr,gl;wire [7:0] gd;wire [XW-1:0] gx;wire [YW-1:0] gy;
 gaussian_stream #(.W(W),.H(H)) gaussian(.clk(clk),.rst_n(rst_n),.start(gstart),.abort_frame(abort_frame),.in_valid(in_valid && active),.in_ready(in_ready),.in_data(in_data),.out_valid(gv),.out_ready(gr),.out_data(gd),.out_x(gx),.out_y(gy),.out_last(gl));
 reg [7:0] pixels[0:DEPTH-1];reg [XW-1:0] xs[0:DEPTH-1];reg [YW-1:0] ys[0:DEPTH-1];reg lasts[0:DEPTH-1];
 reg [PW-1:0] head,tail;reg [PW:0] count;
 wire room=(count<DEPTH);
 wire [AW-1:0] index=gy*W+gx;
 wire [AW-1:0] eye_base=eye ? 2*N:0;
 assign mem_rd_addr=eye_base+(bank ? N:0)+index;
 assign mem_wr_addr=eye_base+(bank ? 0:N)+index;
 assign mem_rd_epoch=epoch;assign mem_wr_data=gd;
 // Independent valid/ready channels. The Gaussian pixel is released only
 // after each required transfer has completed, with no repeated submission.
 assign mem_wr_valid=active && gv && room && !write_sent;
 assign mem_rd_valid=active && gv && room && ref_latched && !read_sent;
 wire write_done=write_sent || (mem_wr_valid && mem_wr_ready);
 wire read_done=!ref_latched || read_sent || (mem_rd_valid && mem_rd_ready);
 assign gr=active && room && write_done && read_done;
 wire push=gv && gr;
 wire response_current=mem_rsp_epoch==epoch;
 wire pop=active && count!=0 && (!out_valid || out_ready) && (!ref_latched || (mem_rsp_valid && response_current));
 assign mem_rsp_ready=!response_current || (active && ref_latched && count!=0 && (!out_valid || out_ready));
 wire [7:0] difference=ref_latched ? (pixels[head]>=mem_rsp_data ? pixels[head]-mem_rsp_data:mem_rsp_data-pixels[head]):0;
 assign start_ready=!active;assign reference_valid=ref_latched;assign reference_id=ref_id;
 assign out_eye=eye;assign out_pair_id=pair_id;assign out_timestamp_ns=timestamp_ns;assign out_config=config_tag;
 always @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
     active<=0;eye<=0;bank<=0;ref_latched<=0;gstart<=0;reference_bits<=0;bank_bits<=0;read_sent<=0;write_sent<=0;
     ids[0]<=0;ids[1]<=0;pair_id<=0;timestamp_ns<=0;ref_id<=0;config_tag<=0;last_config<=0;threshold<=12;epoch<=0;
     head<=0;tail<=0;count<=0;out_valid<=0;out_gaussian<=0;out_difference<=0;out_mask<=0;out_x<=0;out_y<=0;out_last<=0;done<=0;
   end else begin
     gstart<=0;
     if(abort_frame) begin active<=0;count<=0;head<=0;tail<=0;out_valid<=0;done<=0;epoch<=epoch+1;read_sent<=0;write_sent<=0;end
     else if(start_valid && start_ready) begin
       active<=1;eye<=start_eye;pair_id<=start_pair_id;timestamp_ns<=start_timestamp_ns;config_tag<=start_config;threshold<=start_threshold;
       bank<=start_config==last_config ? bank_bits[start_eye]:0;
       ref_latched<=start_config==last_config && reference_bits[start_eye];
       ref_id<=start_config==last_config && reference_bits[start_eye] ? ids[start_eye]:0;
       if(start_config!=last_config)begin reference_bits<=0;bank_bits<=0;ids[0]<=0;ids[1]<=0;end
       last_config<=start_config;gstart<=1;count<=0;head<=0;tail<=0;done<=0;out_valid<=0;epoch<=epoch+1;read_sent<=0;write_sent<=0;
     end else if(active) begin
       if(out_valid && out_ready)begin out_valid<=0;if(out_last)done<=1;end
       if(push)begin pixels[tail]<=gd;xs[tail]<=gx;ys[tail]<=gy;lasts[tail]<=gl;tail<=tail+1;read_sent<=0;write_sent<=0;end
       else begin
         if(mem_wr_valid && mem_wr_ready)write_sent<=1;
         if(mem_rd_valid && mem_rd_ready)read_sent<=1;
       end
       if(pop)begin out_valid<=1;out_gaussian<=pixels[head];out_difference<=difference;out_mask<=difference>threshold;out_x<=xs[head];out_y<=ys[head];out_last<=lasts[head];head<=head+1;end
       case({push,pop})2'b10:count<=count+1;2'b01:count<=count-1;default:count<=count;endcase
       if(commit && done)begin bank_bits[eye]<=!bank;reference_bits[eye]<=1;ids[eye]<=pair_id;active<=0;done<=0;end
     end
   end
 end
endmodule
