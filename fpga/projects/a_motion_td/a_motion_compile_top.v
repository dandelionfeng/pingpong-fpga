// Register bridge used only to keep the complete core observable in synthesis.
// The register bus fits the package. This is not the AFH03 PCIe endpoint or pin map.
module a_motion_compile_top (
 input wire clk,rst_n,bus_valid,bus_write,
 input wire [7:0] bus_addr,input wire [31:0] bus_wdata,
 output wire bus_ready,output reg [31:0] bus_rdata
);
 reg [63:0] header_id,header_time;
 reg [31:0] header_config;
 reg [7:0] header_threshold;
 reg header_eye;
 reg [7:0] response_data;
 reg [15:0] response_epoch;
 reg [2:0] ready_bits;
 wire start_ready,in_ready,out_valid,out_last,out_eye,ref_valid,done;
 wire [7:0] gaussian,difference,write_data;
 wire mask,read_valid,write_valid,response_ready;
 wire [9:0] x;wire [8:0] y;
 wire [19:0] read_addr,write_addr;wire [15:0] read_epoch;
 wire [63:0] pair_id,sample_time,reference_id;wire [31:0] config_tag;
 wire command=bus_valid && bus_write && bus_addr==6;
 assign bus_ready=(bus_write && bus_addr==7) ? in_ready :
                  (bus_write && bus_addr==11) ? response_ready : 1'b1;
 motion_front3 core(
   .clk(clk),.rst_n(rst_n),.start_valid(command && bus_wdata[0]),.start_ready(start_ready),
   .start_eye(header_eye),.start_pair_id(header_id),.start_timestamp_ns(header_time),
   .start_config(header_config),.start_threshold(header_threshold),
   .commit(command && bus_wdata[1]),.abort_frame(command && bus_wdata[2]),
   .in_valid(bus_valid && bus_write && bus_addr==7),.in_ready(in_ready),.in_data(bus_wdata[7:0]),
   .mem_rd_valid(read_valid),.mem_rd_ready(ready_bits[0]),.mem_rd_addr(read_addr),.mem_rd_epoch(read_epoch),
   .mem_rsp_valid(bus_valid && bus_write && bus_addr==11),.mem_rsp_ready(response_ready),
   .mem_rsp_data(response_data),.mem_rsp_epoch(response_epoch),
   .mem_wr_valid(write_valid),.mem_wr_ready(ready_bits[1]),.mem_wr_addr(write_addr),.mem_wr_data(write_data),
   .out_valid(out_valid),.out_ready(ready_bits[2]),.out_gaussian(gaussian),.out_difference(difference),.out_mask(mask),
   .out_x(x),.out_y(y),.out_last(out_last),.out_eye(out_eye),.out_pair_id(pair_id),.out_timestamp_ns(sample_time),
   .out_config(config_tag),.reference_valid(ref_valid),.reference_id(reference_id),.done(done));
 always @(posedge clk or negedge rst_n) begin
   if(!rst_n)begin header_id<=0;header_time<=0;header_config<=1;header_threshold<=12;header_eye<=0;
     response_data<=0;response_epoch<=0;ready_bits<=0;end
   else if(bus_valid && bus_write && bus_ready)case(bus_addr)
     0:header_id[31:0]<=bus_wdata;1:header_id[63:32]<=bus_wdata;
     2:header_time[31:0]<=bus_wdata;3:header_time[63:32]<=bus_wdata;
     4:header_config<=bus_wdata;
     5:begin header_threshold<=bus_wdata[7:0];header_eye<=bus_wdata[8];end
     8:ready_bits<=bus_wdata[2:0];
     9:response_data<=bus_wdata[7:0];10:response_epoch<=bus_wdata[15:0];
   endcase
 end
 always @* begin
   bus_rdata=0;
   case(bus_addr)
     0:bus_rdata=pair_id[31:0];1:bus_rdata=pair_id[63:32];
     2:bus_rdata=sample_time[31:0];3:bus_rdata=sample_time[63:32];
     4:bus_rdata=config_tag;
     5:bus_rdata={22'd0,done,ref_valid,out_eye,out_last,mask,out_valid,start_ready,in_ready,read_valid,write_valid};
     6:bus_rdata={16'd0,difference,gaussian};
     7:bus_rdata={13'd0,y,x};
     8:bus_rdata={12'd0,read_addr};9:bus_rdata={4'd0,write_data,write_addr};
     10:bus_rdata={16'd0,read_epoch};
     11:bus_rdata=reference_id[31:0];12:bus_rdata=reference_id[63:32];
   endcase
 end
endmodule
