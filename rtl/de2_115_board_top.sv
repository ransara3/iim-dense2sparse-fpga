`timescale 1ns/1ps

module de2_115_board_top (
    input  wire CLOCK_50,
    input  wire [3:0] KEY,
    input  wire UART_RXD,
    output wire UART_TXD
);
    wire overflow;

    de2_115_uart_top uart_localizer (
        .clk(CLOCK_50),
        .reset_n(KEY[0]),
        .uart_rxd(UART_RXD),
        .uart_txd(UART_TXD),
        .overflow(overflow)
    );
endmodule
