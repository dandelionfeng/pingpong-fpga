`timescale 1ns/1ps
module tb_morphology_mask_chain;
    localparam W=8,H=6,N=W*H,B=N/8;
    reg clk=0,rst=1,frame_start=0,in_valid=0,in_pixel=0,in_last=0,out_ready=1;
    wire in_ready,out_valid,out_first,out_last,busy,done; wire [7:0] out_data;
    reg pixels[0:N-1]; reg [7:0] expected[0:B-1]; integer i,got=0,errors=0,cycles=0;
    always #5 clk=~clk;
    morphology_mask_chain #(.WIDTH(W),.HEIGHT(H)) dut(clk,rst,frame_start,in_valid,in_ready,in_pixel,in_last,out_valid,out_ready,out_data,out_first,out_last,busy,done);
    initial begin
        $dumpfile("morphology_mask_chain.vcd");
        // Keep only interface/control waveforms; frame memories are not dumped.
        $dumpvars(0,clk,rst,frame_start,in_valid,in_pixel,in_last,out_ready,
                  in_ready,out_valid,out_first,out_last,out_data,busy,done);
        for(i=0;i<N;i=i+1)pixels[i]=0;
        // A 4x4 block survives the open/close chain; one isolated point is removed.
        for(i=1;i<5;i=i+1) begin pixels[i*W+1]=1; pixels[i*W+2]=1; pixels[i*W+3]=1; pixels[i*W+4]=1; end
        pixels[0*W+7]=1;
        expected[0]=8'h1f; expected[1]=8'h1f; expected[2]=8'h1f; expected[3]=8'h1f; expected[4]=8'h1f; expected[5]=8'h1f;
        repeat(2)@(posedge clk); rst=0; @(negedge clk);frame_start=1;@(negedge clk);frame_start=0;
        for(i=0;i<N;i=i+1)begin @(negedge clk);in_valid=1;in_pixel=pixels[i];in_last=(i==N-1);@(posedge clk); end
        @(negedge clk);in_valid=0;in_last=0; wait(out_valid);
        while(got<B)begin
            @(negedge clk); cycles=cycles+1; out_ready=(cycles%3!=0); // periodic one-cycle backpressure
            @(posedge clk); if(out_valid&&out_ready)begin
            $display("MASK_BYTE %0d %02x first=%0d last=%0d",got,out_data,out_first,out_last);
            if(out_data!==expected[got])begin $display("MISMATCH byte=%0d got=%02x expected=%02x",got,out_data,expected[got]);errors=errors+1;end got=got+1;
        end end
        @(negedge clk); out_ready=1; @(posedge clk); if(errors==0)$display("MORPHOLOGY_MASK_PASS bytes=%0d with backpressure",got);else $display("MORPHOLOGY_MASK_FAIL errors=%0d",errors);$finish;
    end
endmodule
