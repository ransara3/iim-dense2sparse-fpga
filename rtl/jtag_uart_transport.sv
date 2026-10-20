`timescale 1ns/1ps
// Avalon-MM JTAG UART, word address 0=data, 1=control; read latency zero.
module jtag_uart_transport (
    input wire clk, reset_n,
    output reg [7:0] rx_data,
    output reg rx_valid,
    input wire rx_ready,
    input wire [7:0] tx_data,
    input wire tx_start,
    output reg tx_busy, tx_done,
    output wire av_address,
    output wire av_chipselect, av_read_n, av_write_n,
    output wire [31:0] av_writedata,
    input wire [31:0] av_readdata,
    input wire av_waitrequest
);
    localparam POLL=0, READ_RX=1, WRITE_TX=2;
    reg [1:0] state;
    reg [7:0] pending_tx;
    assign av_address = (state == POLL);
    assign av_chipselect = (state == POLL || state == WRITE_TX ||
                            (state == READ_RX && rx_ready));
    assign av_read_n = !(av_chipselect && state != WRITE_TX);
    assign av_write_n = !(state == WRITE_TX);
    assign av_writedata = {24'd0, pending_tx};
    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state <= POLL;
            rx_data <= 0;
            rx_valid <= 0;
            tx_busy <= 0;
            tx_done <= 0;
            pending_tx <= 0;
        end else begin
            rx_valid <= 0;
            tx_done <= 0;
            if (tx_start && !tx_busy) begin
                pending_tx <= tx_data;
                tx_busy <= 1;
            end
            if (av_chipselect && !av_waitrequest) begin
                case (state)
                    POLL: begin
                        if (tx_busy && av_readdata[31:16] != 0)
                            state <= WRITE_TX;
                        else if (rx_ready && !rx_valid)
                            state <= READ_RX;
                    end
                    READ_RX: begin
                        rx_data <= av_readdata[7:0];
                        rx_valid <= av_readdata[15];
                        state <= POLL;
                    end
                    WRITE_TX: begin
                        tx_busy <= 0;
                        tx_done <= 1;
                        state <= POLL;
                    end
                endcase
            end else if (state == READ_RX && !rx_ready)
                state <= POLL;
        end
    end
endmodule
