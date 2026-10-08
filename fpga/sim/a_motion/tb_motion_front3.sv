`timescale 1ns/1ps
module tb_motion_front3;
 parameter W=16,H=12,N=W*H,AW=$clog2(4*N),XW=$clog2(W),YW=$clog2(H+1);
 reg clk=0;always #5 clk=~clk;
 reg rst_n=0,start_valid=0,start_eye=0,commit=0,abort_frame=0;
 reg [63:0] start_pair_id=0,start_timestamp_ns=0;reg [31:0] start_config=1;reg [7:0] start_threshold=12;
 reg in_valid=0;wire in_ready;reg [7:0] in_data=0;
 wire rd_valid,wr_valid,rsp_ready;reg rd_ready=0,wr_ready=0,rsp_valid=0;wire [AW-1:0] rd_addr,wr_addr;wire [7:0] wr_data;wire [15:0] rd_epoch;reg [7:0] rsp_data=0;reg [15:0] rsp_epoch=0;
 wire ov;reg ready=0;wire [7:0] og,od;wire mask,last,eye,ref_valid,done,start_ready;wire [XW-1:0] ox;wire [YW-1:0] oy;wire [63:0] pid,ts,ref_id;wire [31:0] cfg;
 motion_front3 #(.W(W),.H(H)) dut(.clk(clk),.rst_n(rst_n),.start_valid(start_valid),.start_ready(start_ready),.start_eye(start_eye),.start_pair_id(start_pair_id),.start_timestamp_ns(start_timestamp_ns),.start_config(start_config),.start_threshold(start_threshold),.commit(commit),.abort_frame(abort_frame),.in_valid(in_valid),.in_ready(in_ready),.in_data(in_data),.mem_rd_valid(rd_valid),.mem_rd_ready(rd_ready),.mem_rd_addr(rd_addr),.mem_rd_epoch(rd_epoch),.mem_rsp_valid(rsp_valid),.mem_rsp_ready(rsp_ready),.mem_rsp_data(rsp_data),.mem_rsp_epoch(rsp_epoch),.mem_wr_valid(wr_valid),.mem_wr_ready(wr_ready),.mem_wr_addr(wr_addr),.mem_wr_data(wr_data),.out_valid(ov),.out_ready(ready),.out_gaussian(og),.out_difference(od),.out_mask(mask),.out_x(ox),.out_y(oy),.out_last(last),.out_eye(eye),.out_pair_id(pid),.out_timestamp_ns(ts),.out_config(cfg),.reference_valid(ref_valid),.reference_id(ref_id),.done(done));
 reg [7:0] memory[0:4*N-1],vectors[0:4*N-1];
 reg [7:0] response_data[0:63];reg [15:0] response_epoch[0:63];integer rh=0,rt=0,rc=0;
 integer input_count=0,output_count=0,input_limit=N,expected_ref=0,expected_refid=0;
 integer active_case=0,random_stalls=1,total_checked=0,cycle_count=0;
 reg checking=0,held=0,input_accepted=0,response_accepted=0;reg [127:0] held_value;
 reg write_held=0,read_held=0;reg [AW+7:0] held_write;reg [AW+15:0] held_read;
 wire [127:0] visible={32'd0,og,od,mask,last,ox,oy,pid[31:0],cfg};
 integer seed=81237;reg [31:0] random_value;
 always @(negedge clk)begin
   random_value=$random(seed);
   ready=!random_stalls || random_value[0] || random_value[1];
   rd_ready=rc<60 && (!random_stalls || random_value[2] || random_value[3]);
   wr_ready=!random_stalls || random_value[4] || random_value[5];
   if(checking && (!in_valid || input_accepted))begin
     if(input_count<input_limit && (!random_stalls || random_value[6] || random_value[7]))begin in_valid=1;in_data=vectors[4*input_count];end
     else in_valid=0;
   end
   if(!rsp_valid || response_accepted)begin
     if(rc && (!random_stalls || random_value[8] || random_value[9]))begin rsp_valid=1;rsp_data=response_data[rh];rsp_epoch=response_epoch[rh];end
     else rsp_valid=0;
   end
 end
 always @(posedge clk)begin
   if(!rst_n)begin rh=0;rt=0;rc=0;held=0;input_accepted=0;response_accepted=0;write_held=0;read_held=0;end
   else begin
     input_accepted=in_valid && in_ready;
     response_accepted=rsp_valid && rsp_ready;
     cycle_count=cycle_count+1;
     if(cycle_count>4000000)begin $display("FAIL timeout case=%0d input=%0d output=%0d",active_case,input_count,output_count);$fatal(1);end
     if(wr_valid && wr_ready)memory[wr_addr]=wr_data;
     if(rd_valid && rd_ready)begin response_data[rt]=memory[rd_addr];response_epoch[rt]=rd_epoch;rt=(rt+1)%64;rc=rc+1;end
     if(rsp_valid && rsp_ready)begin rh=(rh+1)%64;rc=rc-1;end
     if(checking)begin
       if(!abort_frame)begin
         if(write_held && (!wr_valid || {wr_addr,wr_data}!==held_write))$fatal(1,"write changed during stall");
         if(read_held && (!rd_valid || {rd_addr,rd_epoch}!==held_read))$fatal(1,"read changed during stall");
       end
       write_held=wr_valid && !wr_ready;read_held=rd_valid && !rd_ready;
       held_write={wr_addr,wr_data};held_read={rd_addr,rd_epoch};
       if(in_valid && in_ready)input_count=input_count+1;
       if(held && (!ov || visible!==held_value))begin $display("FAIL output changed during stall case=%0d",active_case);$fatal(1);end
       held=ov && !ready;held_value=visible;
       if(ov && ready)begin
         if(og!==vectors[4*output_count+1] || od!==vectors[4*output_count+2] || mask!==(vectors[4*output_count+3]!=0) || ox!==output_count%W || oy!==output_count/W || last!==(output_count==N-1))begin
           $display("FAIL case=%0d pixel=%0d xy=(%0d,%0d) got=%0d/%0d/%0d expected=%0d/%0d/%0d last=%0d",active_case,output_count,ox,oy,og,od,mask,vectors[4*output_count+1],vectors[4*output_count+2],vectors[4*output_count+3],last);$fatal(1);
         end
         if(pid!==start_pair_id || eye!==start_eye || cfg!==start_config || ts!==start_timestamp_ns || ref_valid!==expected_ref[0] || ref_id!==expected_refid)begin $display("FAIL metadata case=%0d",active_case);$fatal(1);end
         output_count=output_count+1;total_checked=total_checked+1;
       end
     end
   end
 end
 integer cases,vector_file,bytes,status,selected_eye,selected_id,selected_ref,selected_refid,selected_commit,selected_limit,selected_config,selected_reset;
 string case_path,root,vector_name,wave;
 initial begin
   if(!$value$plusargs("ROOT=%s",root))root=".";
   case_path={root,"/cases.txt"};cases=$fopen(case_path,"r");if(!cases)$fatal(1,"cannot open cases");
   if($value$plusargs("WAVE=%s",wave))begin $dumpfile(wave);$dumpvars(0,tb_motion_front3.dut);end
   repeat(4)@(negedge clk);rst_n=1;
   while(!$feof(cases))begin
     status=$fscanf(cases,"%d %d %d %d %d %d %d %d %s\n",selected_eye,selected_id,selected_ref,selected_refid,selected_commit,selected_limit,selected_config,selected_reset,vector_name);
     if(status==9)begin
       if(selected_reset)begin checking=0;in_valid=0;rst_n=0;repeat(3)@(negedge clk);rst_n=1;end
       active_case=active_case+1;cycle_count=0;held=0;write_held=0;read_held=0;input_count=0;output_count=0;input_limit=selected_limit;expected_ref=selected_ref;expected_refid=selected_refid;
       random_stalls=(W<640)||(active_case%20==0);
       vector_file=$fopen({root,"/",vector_name},"rb");bytes=$fread(vectors,vector_file);$fclose(vector_file);if(bytes!=4*N)$fatal(1,"vector length mismatch");
       wait(start_ready);@(negedge clk);start_eye=selected_eye;start_pair_id=selected_id;start_timestamp_ns=selected_id*16000000;start_config=selected_config;start_valid=1;
       @(negedge clk);start_valid=0;checking=1;
       if(input_limit==N)begin
         wait(done);@(negedge clk);checking=0;in_valid=0;
         if(output_count!=N)$fatal(1,"output count mismatch");
         if(selected_commit)commit=1;else abort_frame=1;
         @(negedge clk);commit=0;abort_frame=0;
       end else begin
         wait(input_count==input_limit);@(negedge clk);in_valid=0;checking=0;abort_frame=1;
         @(negedge clk);abort_frame=0;
       end
       if(active_case%20==0)begin $display("PROGRESS cases=%0d pixels=%0d",active_case,total_checked);$fflush();end
     end
   end
   $fclose(cases);$display("PASS cases=%0d checked_pixels=%0d W=%0d H=%0d",active_case,total_checked,W,H);$finish;
 end
endmodule
