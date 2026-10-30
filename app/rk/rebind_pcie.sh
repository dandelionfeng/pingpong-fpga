#!/bin/sh
# Reprobe the already enabled PCIe1 after FPGA SRAM programming; no boot edits.
set -eu
module=${1:?Provide the private anlogic_pci.ko path}
poll=${2:-0}
controller=2a210000.pcie
driver=/sys/bus/platform/drivers/rk-pcie
if [ -d /sys/module/anlogic_pci ]; then rmmod anlogic_pci; fi
if [ -e "$driver/$controller" ]; then printf '%s' "$controller" > "$driver/unbind"; fi
printf '%s' "$controller" > "$driver/bind"
n=0
while [ ! -e /sys/bus/pci/devices/0000:21:00.0/vendor ]; do
  n=$((n+1)); [ "$n" -lt 80 ] || { echo 'PCIe endpoint readiness timed out' >&2; exit 3; }
  sleep .1
done
[ "$(cat /sys/bus/pci/devices/0000:21:00.0/vendor)" = 0x1edb ]
[ "$(cat /sys/bus/pci/devices/0000:21:00.0/device)" = 0xabcd ]
insmod "$module" poll_mode="$poll" interrupt_mode=1 enable_st_c2h_credit=1 \
  desc_blen_max=1048576 h2c_timeout=3 c2h_timeout=3
n=0
while [ ! -e /dev/ANLOGIC-PCI0_c2h_0 ] || [ ! -e /dev/ANLOGIC-PCI0_h2c_0 ]; do
  n=$((n+1)); [ "$n" -lt 30 ] || { echo 'DMA device readiness timed out' >&2; exit 4; }
  sleep .1
done
echo 'PCIE_REBIND_AND_DRIVER_READY'
lspci -nn
