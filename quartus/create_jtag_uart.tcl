# Run from quartus/: qsys-script --script=create_jtag_uart.tcl
# Run from the quartus directory; Qsys Tcl does not support file normalize.
package require qsys
create_system jtag_uart_system
set_project_property DEVICE_FAMILY "Cyclone IV E"
set_project_property DEVICE EP4CE115F29C7
add_instance uart altera_avalon_jtag_uart
add_interface clk clock sink
set_interface_property clk EXPORT_OF uart.clk
add_interface reset reset sink
set_interface_property reset EXPORT_OF uart.reset
add_interface uart avalon slave
set_interface_property uart EXPORT_OF uart.avalon_jtag_slave
add_interface irq interrupt sender
set_interface_property irq EXPORT_OF uart.irq
save_system jtag_uart_system.qsys
