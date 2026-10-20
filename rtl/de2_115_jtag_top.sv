`timescale 1ns/1ps
module de2_115_jtag_top (
    input wire CLOCK_50,
    input wire [3:0] KEY
);
    // Asynchronous assertion, synchronous reset release.
    reg [1:0] reset_sync;
    always @(posedge CLOCK_50 or negedge KEY[0]) begin
        if (!KEY[0]) reset_sync <= 0;
        else reset_sync <= {reset_sync[0], 1'b1};
    end
    wire reset_n = reset_sync[1];
    wire [7:0] rx_data, tx_data;
    wire rx_valid, rx_ready, tx_start, tx_busy, tx_done;
    wire address, chipselect, read_n, write_n, waitrequest;
    wire [31:0] writedata, readdata;
    dense2sparse_protocol protocol (
        .clk(CLOCK_50), .reset_n(reset_n), .rx_data(rx_data),
        .rx_valid(rx_valid), .rx_framing_error(1'b0), .rx_ready(rx_ready),
        .tx_data(tx_data), .tx_start(tx_start), .tx_busy(tx_busy),
        .tx_done(tx_done), .overflow());
    jtag_uart_transport transport (
        .clk(CLOCK_50), .reset_n(reset_n), .rx_data(rx_data),
        .rx_valid(rx_valid), .rx_ready(rx_ready), .tx_data(tx_data),
        .tx_start(tx_start), .tx_busy(tx_busy), .tx_done(tx_done),
        .av_address(address), .av_chipselect(chipselect), .av_read_n(read_n),
        .av_write_n(write_n), .av_writedata(writedata),
        .av_readdata(readdata), .av_waitrequest(waitrequest));
    jtag_uart_system jtag (
        .clk_clk(CLOCK_50), .reset_reset_n(reset_n),
        .uart_address(address), .uart_chipselect(chipselect),
        .uart_read_n(read_n), .uart_write_n(write_n),
        .uart_writedata(writedata), .uart_readdata(readdata),
        .uart_waitrequest(waitrequest), .irq_irq());
endmodule
