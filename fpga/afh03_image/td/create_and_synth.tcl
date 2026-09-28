# Execute from a fresh build directory containing src/*.v and core.sdc.
# Generates a native TD .al project. Internal streaming ports are NOT board pins.
set stage create_project
if {[catch {
    create_project afh03_image ./ -family ph1 -device PH1A90SEG324
    set stage add_sources
    add_files {./src/afh03_stereo_preproc.v ./src/afh03_image_lane.v ./src/img_filter3x3.v ./src/img_luma_adjust.v ./src/img_rgb888_to_gray.v ./src/afh03_image_compile_top.v}
    add_files ./core.sdc
    top_module afh03_image_compile_top
    set stage synthesis
    launch_runs -step gate syn_1
    wait_run syn_1 -quiet
    set stage reports
    open_run syn_1
    report_area -file ./core_gate.area
    export_db ./core_gate.db
    close_project
    set f [open SUCCESS.txt w]
    puts $f "AFH03_IMAGE_SYNTH_PASS PH1A90SEG324 synthesis-only"
    close $f
    puts "AFH03_IMAGE_SYNTH_PASS"
} message]} {
    puts stderr "AFH03_IMAGE_SYNTH_FAIL stage=$stage: $message"
    set f [open FAILURE.txt w]
    puts $f "stage=$stage: $message"
    close $f
    exit 1
}
exit 0
