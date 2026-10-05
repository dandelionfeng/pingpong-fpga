# Run from a fresh output directory containing copied input files.
set stage init
if {[catch {
    set stage device
    import_device ph1_180.db -package PH1A180SFG676
    set stage read_hdl
    read_hdl -file {smoke_top.v} -top smoke_top
    read_sdc smoke.sdc
    set stage synthesis
    optimize_rtl
    optimize_gate
    legalize_phy_inst
    report_area -file gate.area
    export_db gate.db
    set stage place
    place
    set stage route
    route
    report_area -file route.area
    export_db route.db
    set stage timing
    update_timing -mode final
    report_timing_summary -file route_timing.rpt
    # Stop at routed reports. Actual board pin constraints are not available.
    # Do not bypass TD's unconstrained-IO bitstream protection.
    set f [open SUCCESS.txt w]
    puts $f "TD_SMOKE_PASS PH1A180SFG676 route-only"
    close $f
    puts "TD_SMOKE_PASS"
} message]} {
    puts stderr "TD_SMOKE_FAIL stage=$stage: $message"
    set f [open FAILURE.txt w]
    puts $f "stage=$stage: $message"
    close $f
    exit 1
}
exit 0
