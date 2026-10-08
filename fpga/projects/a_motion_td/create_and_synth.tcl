# Synthesis envelope only; ports are the internal A/B and DDR contracts.
set stage create_project
if {[catch {
    create_project a_motion ./ -family ph1 -device PH1A90SEG324
    set stage add_sources
    add_files {./src/gaussian_stream.v ./src/motion_front3.v ./src/a_motion_compile_top.v}
    add_files ./core.sdc
    top_module a_motion_compile_top
    set stage synthesis
    launch_runs -step gate syn_1
    wait_run syn_1 -quiet
    set stage reports
    open_run syn_1
    report_area -file ./core_gate.area
    export_db ./core_gate.db
    close_project
    set f [open SUCCESS.txt w]
    puts $f "A_MOTION_SYNTH_PASS PH1A90SEG324 synthesis-only"
    close $f
    puts "A_MOTION_SYNTH_PASS"
} message]} {
    puts stderr "A_MOTION_SYNTH_FAIL stage=$stage: $message"
    set f [open FAILURE.txt w]
    puts $f "stage=$stage: $message"
    close $f
    exit 1
}
exit 0
