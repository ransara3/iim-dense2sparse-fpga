`timescale 1ns/1ps
module de2_115_uart_top #(
    parameter integer CLK_HZ = 50_000_000,
    parameter integer BAUD = 115_200,
    parameter integer MAX_WIDTH = 1280,
    parameter integer MAX_HEIGHT = 720,
    parameter integer MAX_LABELS = 2048,
    parameter integer MIN_AREA = 3
) (
    input wire clk, reset_n, uart_rxd,
    output wire uart_txd, overflow
);
    localparam integer CLKS_PER_BIT = (CLK_HZ + BAUD / 2) / BAUD;
    wire [7:0] rx_data, tx_data;
    wire rx_valid, framing_error, tx_start, tx_busy, tx_done;
    uart_rx_8n1 #(.CLKS_PER_BIT(CLKS_PER_BIT)) receiver (
        .clk(clk), .reset_n(reset_n), .rx(uart_rxd), .data(rx_data),
        .valid(rx_valid), .framing_error(framing_error));
    uart_tx_8n1 #(.CLKS_PER_BIT(CLKS_PER_BIT)) transmitter (
        .clk(clk), .reset_n(reset_n), .start(tx_start), .data(tx_data),
        .tx(uart_txd), .busy(tx_busy), .done(tx_done));
    dense2sparse_protocol #(.MAX_WIDTH(MAX_WIDTH), .MAX_HEIGHT(MAX_HEIGHT),
        .MAX_LABELS(MAX_LABELS), .MIN_AREA(MIN_AREA)) protocol (
        .clk(clk), .reset_n(reset_n), .rx_data(rx_data), .rx_valid(rx_valid),
        .rx_framing_error(framing_error), .rx_ready(), .tx_data(tx_data),
        .tx_start(tx_start), .tx_busy(tx_busy), .tx_done(tx_done), .overflow(overflow));
endmodule
