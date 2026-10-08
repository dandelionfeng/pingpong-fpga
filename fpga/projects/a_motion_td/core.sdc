# Requested core clock constraint, not a measured board frequency.
create_clock -name core_clk -period 10.000 [get_ports clk]
