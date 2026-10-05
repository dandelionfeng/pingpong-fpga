// B-module functional reference for the FPGA back four stages.
// Operation: erode -> dilate -> dilate -> erode, 3x3 replicate boundary.
// Simulation-first frame store; line-buffer replacement preserves frame semantics.
module morphology_mask_chain #(
    parameter integer WIDTH=8, HEIGHT=6
) (
    input wire clk, input wire rst, input wire frame_start,
    input wire in_valid, output wire in_ready, input wire in_pixel, input wire in_last,
    output reg out_valid, input wire out_ready, output reg [7:0] out_data,
    output reg out_first, output reg out_last, output reg busy, output reg done
);
    localparam integer PIXELS=WIDTH*HEIGHT, BYTES=WIDTH*HEIGHT/8;
    localparam [2:0] IDLE=0,CAPTURE=1,PROCESS=2,PACK=3,DONE=4;
    reg [2:0] state; reg source_mem[0:PIXELS-1]; reg s1_mem[0:PIXELS-1];
    reg s2_mem[0:PIXELS-1]; reg s3_mem[0:PIXELS-1]; reg s4_mem[0:PIXELS-1];
    integer write_idx, pack_idx, x, y, dx, dy, nx, ny; reg v;
    assign in_ready=(state==IDLE)||(state==CAPTURE);
    always @(posedge clk) begin
        if (rst) begin state<=IDLE; write_idx<=0; pack_idx<=0; out_valid<=0; out_data<=0; out_first<=0; out_last<=0; busy<=0; done<=0; end
        else begin
            done<=0;
            case(state)
            IDLE: begin busy<=0; out_valid<=0; out_first<=0; out_last<=0; if(frame_start) begin write_idx<=0; busy<=1; state<=CAPTURE; end end
            CAPTURE: begin
                busy<=1; out_valid<=0; out_first<=0; out_last<=0;
                if(in_valid && in_ready) begin
                    if(write_idx<PIXELS) source_mem[write_idx]<=in_pixel;
                    if(in_last || write_idx==PIXELS-1) begin state<=PROCESS; write_idx<=0; end
                    else write_idx<=write_idx+1;
                end
            end
            PROCESS: begin
                // Deterministic reference calculation; each stage reads the previous stage.
                for(y=0;y<HEIGHT;y=y+1) for(x=0;x<WIDTH;x=x+1) begin
                    v=1; for(dy=-1;dy<=1;dy=dy+1) for(dx=-1;dx<=1;dx=dx+1) begin
                        nx=x+dx; ny=y+dy; if(nx<0)nx=0; else if(nx>=WIDTH)nx=WIDTH-1; if(ny<0)ny=0; else if(ny>=HEIGHT)ny=HEIGHT-1;
                        if(!source_mem[ny*WIDTH+nx])v=0;
                    end s1_mem[y*WIDTH+x]=v;
                end
                for(y=0;y<HEIGHT;y=y+1) for(x=0;x<WIDTH;x=x+1) begin
                    v=0; for(dy=-1;dy<=1;dy=dy+1) for(dx=-1;dx<=1;dx=dx+1) begin
                        nx=x+dx; ny=y+dy; if(nx<0)nx=0; else if(nx>=WIDTH)nx=WIDTH-1; if(ny<0)ny=0; else if(ny>=HEIGHT)ny=HEIGHT-1;
                        if(s1_mem[ny*WIDTH+nx])v=1;
                    end s2_mem[y*WIDTH+x]=v;
                end
                for(y=0;y<HEIGHT;y=y+1) for(x=0;x<WIDTH;x=x+1) begin
                    v=0; for(dy=-1;dy<=1;dy=dy+1) for(dx=-1;dx<=1;dx=dx+1) begin
                        nx=x+dx; ny=y+dy; if(nx<0)nx=0; else if(nx>=WIDTH)nx=WIDTH-1; if(ny<0)ny=0; else if(ny>=HEIGHT)ny=HEIGHT-1;
                        if(s2_mem[ny*WIDTH+nx])v=1;
                    end s3_mem[y*WIDTH+x]=v;
                end
                for(y=0;y<HEIGHT;y=y+1) for(x=0;x<WIDTH;x=x+1) begin
                    v=1; for(dy=-1;dy<=1;dy=dy+1) for(dx=-1;dx<=1;dx=dx+1) begin
                        nx=x+dx; ny=y+dy; if(nx<0)nx=0; else if(nx>=WIDTH)nx=WIDTH-1; if(ny<0)ny=0; else if(ny>=HEIGHT)ny=HEIGHT-1;
                        if(!s3_mem[ny*WIDTH+nx])v=0;
                    end s4_mem[y*WIDTH+x]=v;
                end
                pack_idx<=0; out_valid<=0; out_first<=0; out_last<=0; state<=PACK;
            end
            PACK: begin
                busy<=1;
                if(!out_valid) begin
                    out_data=0; for(x=0;x<8;x=x+1) out_data[x]=s4_mem[pack_idx*8+x];
                    out_valid<=1; out_first<=(pack_idx==0); out_last<=(pack_idx==BYTES-1);
                end else if(out_ready) begin
                    out_valid<=0;
                    if(pack_idx==BYTES-1) state<=DONE; else pack_idx<=pack_idx+1;
                end
            end
            DONE: begin busy<=0; done<=1; out_valid<=0; out_first<=0; out_last<=0; state<=IDLE; end
            default: state<=IDLE;
            endcase
        end
    end
endmodule
