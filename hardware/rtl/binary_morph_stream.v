// Derived from A gaussian_stream handshake/replicate window. Binary E/D operator.
// Four instances implement the B reference E,D,D,E with bounded line storage.
module binary_morph_stream #(parameter W=640, H=360, DILATE=0, XW=$clog2(W), YW=$clog2(H+1)) (
 input wire clk, rst_n, start,
 input wire in_valid, output wire in_ready, input wire in_data,
 output reg out_valid, input wire out_ready, output reg out_data,
 output reg [XW-1:0] out_x, output reg [YW-1:0] out_y, output reg out_last
);
 reg row1[0:W-1];
 reg row2[0:W-1];
 reg busy, input_done, bottom, bottom_issued, flush;
 reg [XW-1:0] input_x, bottom_x, mem_x;
 reg [YW-1:0] input_y, mem_y, flush_y;
 reg flush_last;
 reg mem_valid, mem_bottom;
 reg prev1,prev2,current;
 reg tl,tm,ml,mm,bl,bm;
 wire advance= !out_valid || out_ready;
 assign in_ready=busy && !input_done && !bottom && !flush && advance;
 wire top_sample=mem_bottom ? prev2 : (mem_y==1 ? prev1:prev2);
 wire middle_sample=prev1;
 wire bottom_sample=mem_bottom ? prev1:current;
 function gaussian;
 input a,b,c,d,e,f,g,h,i;
 
 begin gaussian=DILATE ? (a|b|c|d|e|f|g|h|i):(a&b&c&d&e&f&g&h&i); end
 endfunction
 always @(posedge clk or negedge rst_n) begin
   if(!rst_n) begin
     busy<=0; input_done<=0; bottom<=0; bottom_issued<=0; flush<=0;
     input_x<=0; input_y<=0; bottom_x<=0;mem_x<=0;mem_y<=0;mem_valid<=0;mem_bottom<=0;flush_y<=0;flush_last<=0;
     out_valid<=0;out_data<=0;out_x<=0;out_y<=0;out_last<=0;
     prev1<=0;prev2<=0;current<=0;tl<=0;tm<=0;ml<=0;mm<=0;bl<=0;bm<=0;
   end else if(start && !busy) begin
     busy<=1;input_x<=0;input_y<=0;bottom_x<=0;input_done<=0;bottom<=0;bottom_issued<=0;flush<=0;mem_valid<=0;out_valid<=0;out_last<=0;
   end else if(advance) begin
     out_valid<=0;
     if(out_valid && out_ready && out_last) busy<=0;
     if(flush) begin
       out_valid<=1;out_data<=gaussian(tl,tm,tm,ml,mm,mm,bl,bm,bm);
       out_x<=W-1;out_last<=flush_last;
       out_y<=flush_y;flush<=0;
     end else if(mem_valid) begin
       mem_valid<=0;
       if(!mem_bottom) row2[mem_x]<=prev1;
       if(mem_x==0) begin
         tl<=top_sample;tm<=top_sample;ml<=middle_sample;mm<=middle_sample;bl<=bottom_sample;bm<=bottom_sample;
       end else begin
         if(mem_y!=0) begin
           out_valid<=1;out_data<=gaussian(tl,tm,top_sample,ml,mm,middle_sample,bl,bm,bottom_sample);
           out_x<=mem_x-1;out_y<=mem_y-1;out_last<=0;
         end
         tl<=tm;tm<=top_sample;ml<=mm;mm<=middle_sample;bl<=bm;bm<=bottom_sample;
       end
       if(mem_x==W-1 && mem_y!=0) begin
         flush<=1;flush_y<=mem_y-1;flush_last<=mem_bottom;
       end
       if(mem_x==W-1 && mem_y==H-1 && !mem_bottom) begin bottom<=1;bottom_x<=0;end
     end
     // The read registers and coordinates are held across output stalls and right-edge flush.
     if(!flush) begin
       if(in_valid && in_ready) begin
         prev1<=row1[input_x];prev2<=row2[input_x];row1[input_x]<=in_data;
         current<=in_data;mem_x<=input_x;mem_y<=input_y;mem_bottom<=0;mem_valid<=1;
         if(input_x==W-1) begin input_x<=0;if(input_y==H-1)input_done<=1;else input_y<=input_y+1;end
         else input_x<=input_x+1;
       end else if(bottom && !bottom_issued) begin
         prev1<=row1[bottom_x];prev2<=row2[bottom_x];mem_x<=bottom_x;mem_y<=H;mem_bottom<=1;mem_valid<=1;
         if(bottom_x==W-1)bottom_issued<=1;else bottom_x<=bottom_x+1;
       end
     end
   end
 end
endmodule
