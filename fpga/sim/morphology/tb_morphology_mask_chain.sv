`timescale 1ns/1ps
module tb_morphology_mask_chain;
    localparam W=8,H=6,N=W*H,B=N/8;
    reg clk=0,rst=1,frame_start=0,in_valid=0,in_pixel=0,in_last=0,out_ready=1;
    wire in_ready,out_valid,out_first,out_last,busy,done,frame_error;
    wire [7:0] out_data;
    reg pixels[0:N-1]; integer i,got,errors,cycles;
    always #5 clk=~clk;
    morphology_mask_chain #(.WIDTH(W),.HEIGHT(H)) dut(
        .clk(clk),.rst(rst),.frame_start(frame_start),.in_valid(in_valid),.in_ready(in_ready),
        .in_pixel(in_pixel),.in_last(in_last),.out_valid(out_valid),.out_ready(out_ready),
        .out_data(out_data),.out_first(out_first),.out_last(out_last),.busy(busy),.done(done),.frame_error(frame_error));

    task start_capture;
        begin
            @(negedge clk); frame_start=1; in_valid=1; in_pixel=pixels[0]; in_last=0;
            if(in_ready!==0) begin $display("FAIL startup in_ready asserted in IDLE"); errors=errors+1; end
            @(posedge clk); #1; frame_start=0; in_valid=0; in_last=0;
        end
    endtask

    task send_frame;
        input integer count;
        begin
            for(i=0;i<count;i=i+1) begin
                if((i%5)==2) begin @(negedge clk); in_valid=0; in_last=0; @(posedge clk); #1; end
                @(negedge clk); in_valid=1; in_pixel=pixels[i]; in_last=(i==count-1);
                @(posedge clk); #1;
            end
            @(negedge clk); in_valid=0; in_last=0;
        end
    endtask

    task check_output;
        begin
            got=0; cycles=0;
            while(got<B && cycles<200) begin
                @(negedge clk); cycles=cycles+1; out_ready=(cycles%3!=0);
                // Sample the transfer in the active region before the DUT's
                // nonblocking state update clears out_valid.
                @(posedge clk);
                #0;
                if(out_valid && out_ready) begin
                    if(out_data!==8'h1f) begin $display("FAIL byte=%0d got=%02x expected=1f",got,out_data); errors=errors+1; end
                    if(out_first !== (got==0)) begin $display("FAIL first flag byte=%0d",got); errors=errors+1; end
                    if(out_last !== (got==B-1)) begin $display("FAIL last flag byte=%0d",got); errors=errors+1; end
                    got=got+1;
                end
            end
            if(got!=B) begin $display("FAIL output timeout got=%0d",got); errors=errors+1; end
            out_ready=1; @(posedge clk); #1;
            if(!done) begin $display("FAIL done not asserted"); errors=errors+1; end
        end
    endtask

    initial begin
        $dumpfile("morphology_mask_chain.vcd");
        $dumpvars(0,clk,rst,frame_start,in_valid,in_pixel,in_last,out_ready,in_ready,out_valid,out_first,out_last,out_data,busy,done,frame_error);
        errors=0;
        for(i=0;i<N;i=i+1) pixels[i]=0;
        for(i=1;i<5;i=i+1) begin pixels[i*W+1]=1; pixels[i*W+2]=1; pixels[i*W+3]=1; pixels[i*W+4]=1; end
        pixels[7]=1;
        repeat(2) @(posedge clk); rst=0;
        start_capture(); send_frame(N); check_output();
        if(frame_error) begin $display("FAIL unexpected frame_error on full frame"); errors=errors+1; end

        @(negedge clk); frame_start=1; @(posedge clk); #1; frame_start=0;
        for(i=0;i<W;i=i+1) begin @(negedge clk); in_valid=1; in_pixel=0; in_last=(i==W-1); @(posedge clk); #1; end
        @(negedge clk); in_valid=0; in_last=0;
        if(!frame_error) begin $display("FAIL short frame did not raise frame_error"); errors=errors+1; end
        repeat(2) begin @(posedge clk); #1; if(out_valid||done) begin $display("FAIL short frame produced output"); errors=errors+1; end end

        start_capture(); send_frame(N); check_output();
        if(errors==0) $display("MORPHOLOGY_PROTOCOL_PASS startup_short_frame_recovery");
        else $display("MORPHOLOGY_PROTOCOL_FAIL errors=%0d",errors);
        $finish;
    end
endmodule
