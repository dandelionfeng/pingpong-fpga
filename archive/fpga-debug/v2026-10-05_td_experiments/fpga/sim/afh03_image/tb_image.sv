`timescale 1ns/1ps
module tb_image;
    reg clk=0; always #5 clk=~clk;
    reg rst_n=0;
    reg cfg_valid=0,cfg_camera=0;
    reg [5:0] cfg_addr=0; reg [31:0] cfg_wdata=0;
    wire cfg_ready; wire [1:0] cfg_error,cfg_pending,stream_fault;
    reg [1:0] s_valid=0; wire [1:0] s_ready;
    reg [15:0] s_data=0; reg [195:0] s_user=0;
    wire [1:0] full_valid,roi_valid;
    reg [1:0] full_ready=0,roi_ready=0;
    wire [31:0] full_data; wire [15:0] roi_data;
    wire [293:0] full_user,roi_user;
    afh03_stereo_preproc #(.DEFAULT_WIDTH(4),.DEFAULT_HEIGHT(3)) dut(.*);
    reg [1:0] allow_full=3,allow_roi=3;
    reg random_stalls=1;
    reg [31:0] rng=32'h1248abcd;
    integer seed;
    always @(negedge clk) begin
        rng = (rng ^ (rng << 13)); rng = (rng ^ (rng >> 17)); rng = (rng ^ (rng << 5));
        full_ready <= allow_full & (random_stalls ? {rng[7:5]!=0,rng[2:0]!=0} : 2'b11);
        roi_ready <= allow_roi & (random_stalls ? {rng[15:13]!=0,rng[10:8]!=0} : 2'b11);
    end
    integer outfd,fd,scan,op,cam,cycles=0,i,errors=0;
    integer full_count[0:1];
    reg [31:0] a,b,c,d,e;
    reg [1:0] previous_fstall=0,previous_rstall=0;
    reg [31:0] previous_fdata;
    reg [15:0] previous_rdata;
    reg [293:0] previous_fuser,previous_ruser;
    reg [1023:0] stimulus_path,output_path;
    always @(posedge clk) begin
        cycles <= cycles+1;
        if(cycles > 600000) $fatal(1,"watchdog: input/config/output deadlock");
        if(!rst_n) begin previous_fstall<=0;previous_rstall<=0; end
        else begin
            for(i=0;i<2;i=i+1) begin
                if(previous_fstall[i] && (!full_valid[i] || full_data[16*i+:16] !== previous_fdata[16*i+:16]
                    || full_user[147*i+:147] !== previous_fuser[147*i+:147])) $fatal(1,"full unstable while stalled lane %0d",i);
                if(previous_rstall[i] && (!roi_valid[i] || roi_data[8*i+:8] !== previous_rdata[8*i+:8]
                    || roi_user[147*i+:147] !== previous_ruser[147*i+:147])) $fatal(1,"ROI unstable while stalled lane %0d",i);
                if(full_valid[i] && full_ready[i]) begin
                    $fdisplay(outfd,"F %0d %h %h",i,full_data[16*i+:16],full_user[147*i+:147]);
                    full_count[i] = full_count[i]+1;
                end
                if(roi_valid[i] && roi_ready[i]) $fdisplay(outfd,"R %0d %h %h",i,roi_data[8*i+:8],roi_user[147*i+:147]);
            end
            if(cfg_error != 0) errors=errors+1;
            previous_fstall <= full_valid & ~full_ready;
            previous_rstall <= roi_valid & ~roi_ready;
            previous_fdata <= full_data; previous_rdata <= roi_data;
            previous_fuser <= full_user; previous_ruser <= roi_user;
        end
    end
    task reset_dut;
        begin
            @(negedge clk);rst_n=0;s_valid=0;cfg_valid=0;
            repeat(5) @(negedge clk);
            rst_n=1;
        end
    endtask
    initial begin
        full_count[0]=0;full_count[1]=0;
        if($value$plusargs("SEED=%d",seed)) rng=seed;
        if(!$value$plusargs("STIM=%s",stimulus_path)) $fatal(1,"missing STIM");
        if(!$value$plusargs("OUT=%s",output_path)) $fatal(1,"missing OUT");
        fd=$fopen(stimulus_path,"r");outfd=$fopen(output_path,"w");
        if(!fd || !outfd) $fatal(1,"file open failed");
        if($test$plusargs("WAVES")) begin $dumpfile("image_pipeline.vcd");$dumpvars(1,tb_image); end
        reset_dut();
        while(!$feof(fd)) begin
            scan=$fscanf(fd,"%d %d %h %h %h %h %h\n",op,cam,a,b,c,d,e);
            if(scan!=7) $fatal(1,"bad stimulus record");
            case(op)
                1: begin
                    @(negedge clk);cfg_camera=cam;cfg_addr=a;cfg_wdata=b;cfg_valid=1;
                    @(posedge clk);while(!cfg_ready) @(posedge clk);
                    @(negedge clk);cfg_valid=0;
                end
                2: begin
                    if(rng[20]) repeat(rng[22:21]) @(negedge clk);
                    @(negedge clk);s_data[8*cam+:8]=a;s_user[98*cam+:98]={d,e,c,b[1:0]};s_valid[cam]=1;
                    @(posedge clk);while(!s_ready[cam]) @(posedge clk);
                    // Clear after the accepted rising edge; the next record
                    // may drive at the very next falling edge (no forced bubble).
                    s_valid[cam]<=0;
                end
                3: reset_dut();
                4: begin @(negedge clk);allow_full=a;allow_roi=b;random_stalls=c; end
                5: repeat(a) @(negedge clk);
                6: begin
                    @(negedge clk);
                    case(a)
                        0: if(stream_fault !== b[1:0]) $fatal(1,"fault state %h expected %h",stream_fault,b);
                        1: if(cfg_pending !== b[1:0]) $fatal(1,"pending state mismatch");
                        2: if(errors != b) $fatal(1,"config error count %0d expected %0d",errors,b);
                        3: if(s_ready[cam] !== 1'b0) $fatal(1,"faulted source must stop");
                        4: if(full_count[cam] != b) $fatal(1,"other camera blocked: count=%0d expected=%0d",full_count[cam],b);
                    endcase
                end
                default: $fatal(1,"unknown operation");
            endcase
        end
        allow_full=3;allow_roi=3;random_stalls=0;
        repeat(10000) @(negedge clk);
        $fclose(fd);$fclose(outfd);
        $display("TB_IMAGE_PASS cycles=%0d config_errors=%0d",cycles,errors);
        $finish;
    end
endmodule
