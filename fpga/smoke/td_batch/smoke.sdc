# Synthetic 50 MHz clock; this does not describe the actual board clock or IO timing.
create_clock -name smoke_clk -period 20 [get_ports {clk}]
