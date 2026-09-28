# Integration target only. No camera, DDR, PCIe or board I/O timing is implied.
create_clock -name core_clk -period 10.000 [get_ports {clk}]
