`timescale 1ns/1ps
module tb_protocol_review;
  localparam W=8,H=6,N=W*H,B=N/8;
  reg clk=0,rst=1,frame_start=0,in_valid=0,in_pixel=0,in_last=0,out_ready=1;
  wire in_ready,out_valid,out_first,out_last,busy,done;
  wire [7:0] out_data;
  integer got,failures=0,i;
  reg [7:0] bytes [0:B-1];
  always #5 clk=~clk;
  morphology_mask_chain #(.WIDTH(W),.HEIGHT(H)) dut(
    clk,rst,frame_start,in_valid,in_ready,in_pixel,in_last,
    out_valid,out_ready,out_data,out_first,out_last,busy,done);
  task collect;
    begin
      got=0;
      while(got<B) begin
        @(posedge clk);
        if(out_valid && out_ready) begin bytes[got]=out_data;got=got+1;end
      end
      wait(done);@(negedge clk);@(negedge clk);
    end
  endtask
  task constant_frame(input integer count,input reg pixel);
    begin
      @(negedge clk);frame_start=1;
      @(negedge clk);frame_start=0;
      for(i=0;i<count;i=i+1)begin
        in_valid=1;in_pixel=pixel;in_last=(i==count-1);
        @(negedge clk);
      end
      in_valid=0;in_last=0;collect;
    end
  endtask
  initial begin
    #20000;$fatal(1,"review timeout");
  end
  initial begin
    repeat(2)@(negedge clk);rst=0;
    // Warm up the frame store, making the missing tail deterministic.
    constant_frame(N,0);
    // A producer uses the advertised ready signal on the start edge.
    @(negedge clk);frame_start=1;in_valid=1;in_pixel=1;in_last=0;
    @(posedge clk);
    if(!in_ready)$fatal(1,"setup: ready was not advertised");
    @(negedge clk);frame_start=0;
    for(i=1;i<N;i=i+1)begin
      in_valid=1;in_pixel=(i%W<4);in_last=(i==N-1);
      @(negedge clk);
    end
    in_valid=0;in_last=0;collect;
    for(i=0;i<B;i=i+1)if(bytes[i]!==8'h0f)begin
      $display("FIRST_PIXEL_LOST row=%0d got=%02x expected=0f",i,bytes[i]);
      failures=failures+1;
    end
    constant_frame(N,1);
    // A truncated all-zero row must not complete as a full stale frame.
    constant_frame(W,0);
    for(i=0;i<B;i=i+1)begin
      $display("SHORT_FRAME_OUTPUT row=%0d byte=%02x",i,bytes[i]);
      if(bytes[i]!==8'h00)failures=failures+1;
    end
    $display("REVIEW_PROTOCOL_FAILURES=%0d",failures);
    if(failures)$fatal(1,"input handshake / short frame contract violated");
    $finish;
  end
endmodule
