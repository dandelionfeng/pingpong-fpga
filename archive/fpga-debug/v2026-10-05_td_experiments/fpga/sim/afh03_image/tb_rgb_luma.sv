`timescale 1ns/1ps
module tb_rgb_luma;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,s_valid=0,m_ready=1;
    wire s_ready,m_valid;
    reg [23:0] s_data=0;reg [15:0] s_user=0;
    wire [7:0] m_data;wire [15:0] m_user;
    img_rgb888_to_gray #(.USER_WIDTH(16)) dut(.*);
    reg [7:0] pixel,gain_q6;reg signed [8:0] offset;
    wire [7:0] adjusted;
    img_luma_adjust luma(.*);
    integer n,j,k,value,expected,received=0,seed=1457;
    integer queue_data[0:9999];integer queue_user[0:9999];
    reg [7:0] old_data;reg [15:0] old_user;reg was_stalled=0;
    integer ready_cycle=0;
    always @(negedge clk) begin
        ready_cycle=ready_cycle+1;
        m_ready <= (ready_cycle%11 >= 4);
    end
    always @(posedge clk) if(rst_n) begin
        if(was_stalled && (!m_valid || m_data!==old_data || m_user!==old_user)) $fatal(1,"RGB output unstable");
        if(m_valid && m_ready) begin
            if(m_data !== queue_data[received] || m_user !== queue_user[received]) $fatal(1,"RGB mismatch %0d",received);
            received=received+1;
        end
        was_stalled<=m_valid&&!m_ready;old_data<=m_data;old_user<=m_user;
    end
    initial begin
        // Exhaust every pixel/gain pair with signed-offset boundary cases.
        for(n=0;n<256;n=n+1) for(j=0;j<256;j=j+1) for(k=0;k<5;k=k+1) begin
            pixel=n;gain_q6=j;
            case(k) 0:offset=-256;1:offset=-1;2:offset=0;3:offset=1;4:offset=255;endcase
            #1;value=((n*j+32)/64)+offset;
            expected=value<0?0:value>255?255:value;
            if(adjusted!==expected) $fatal(1,"luma mismatch");
        end
        repeat(3) @(negedge clk);rst_n=1;
        for(n=0;n<4096;n=n+1) begin
            @(negedge clk);s_data=$random(seed);s_user=n;s_valid=1;
            queue_data[n]=(77*s_data[23:16]+150*s_data[15:8]+29*s_data[7:0]+128)/256;
            queue_user[n]=n;
            @(posedge clk);while(!s_ready) @(posedge clk);
            @(negedge clk);s_valid=0;
        end
        repeat(20) @(negedge clk);
        if(received!=4096) $fatal(1,"RGB count mismatch");
        $display("TB_RGB_LUMA_PASS rgb=4096 luma=327680");$finish;
    end
endmodule
