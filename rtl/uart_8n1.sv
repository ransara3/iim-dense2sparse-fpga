`timescale 1ns/1ps

module uart_rx_8n1 #(
    parameter integer CLKS_PER_BIT = 434
) (
    input  wire       clk,
    input  wire       reset_n,
    input  wire       rx,
    output reg  [7:0] data,
    output reg        valid,
    output reg        framing_error
);
    localparam [1:0] RX_IDLE  = 2'd0;
    localparam [1:0] RX_START = 2'd1;
    localparam [1:0] RX_DATA  = 2'd2;
    localparam [1:0] RX_STOP  = 2'd3;
    localparam integer HALF_BIT = CLKS_PER_BIT / 2;

    reg [1:0] state;
    reg [31:0] clock_count;
    reg [2:0] bit_index;
    reg [7:0] shift;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state <= RX_IDLE;
            clock_count <= 0;
            bit_index <= 0;
            shift <= 0;
            data <= 0;
            valid <= 1'b0;
            framing_error <= 1'b0;
        end else begin
            valid <= 1'b0;
            framing_error <= 1'b0;
            case (state)
                RX_IDLE: begin
                    if (!rx) begin
                        clock_count <= 0;
                        state <= RX_START;
                    end
                end
                RX_START: begin
                    if (clock_count == HALF_BIT - 1) begin
                        clock_count <= 0;
                        if (!rx) begin
                            bit_index <= 0;
                            state <= RX_DATA;
                        end else begin
                            state <= RX_IDLE;
                        end
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
                RX_DATA: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 0;
                        shift[bit_index] <= rx;
                        if (bit_index == 7)
                            state <= RX_STOP;
                        else
                            bit_index <= bit_index + 1'b1;
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
                RX_STOP: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 0;
                        state <= RX_IDLE;
                        if (rx) begin
                            data <= shift;
                            valid <= 1'b1;
                        end else begin
                            framing_error <= 1'b1;
                        end
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
                default: state <= RX_IDLE;
            endcase
        end
    end
endmodule


module uart_tx_8n1 #(
    parameter integer CLKS_PER_BIT = 434
) (
    input  wire       clk,
    input  wire       reset_n,
    input  wire       start,
    input  wire [7:0] data,
    output reg        tx,
    output reg        busy,
    output reg        done
);
    localparam [1:0] TX_IDLE  = 2'd0;
    localparam [1:0] TX_START = 2'd1;
    localparam [1:0] TX_DATA  = 2'd2;
    localparam [1:0] TX_STOP  = 2'd3;

    reg [1:0] state;
    reg [31:0] clock_count;
    reg [2:0] bit_index;
    reg [7:0] shift;

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state <= TX_IDLE;
            clock_count <= 0;
            bit_index <= 0;
            shift <= 0;
            tx <= 1'b1;
            busy <= 1'b0;
            done <= 1'b0;
        end else begin
            done <= 1'b0;
            case (state)
                TX_IDLE: begin
                    tx <= 1'b1;
                    busy <= 1'b0;
                    if (start) begin
                        shift <= data;
                        tx <= 1'b0;
                        busy <= 1'b1;
                        clock_count <= 0;
                        state <= TX_START;
                    end
                end
                TX_START: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 0;
                        bit_index <= 0;
                        tx <= shift[0];
                        state <= TX_DATA;
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
                TX_DATA: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 0;
                        if (bit_index == 7) begin
                            tx <= 1'b1;
                            state <= TX_STOP;
                        end else begin
                            bit_index <= bit_index + 1'b1;
                            tx <= shift[bit_index + 1'b1];
                        end
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
                TX_STOP: begin
                    if (clock_count == CLKS_PER_BIT - 1) begin
                        clock_count <= 0;
                        tx <= 1'b1;
                        busy <= 1'b0;
                        done <= 1'b1;
                        state <= TX_IDLE;
                    end else begin
                        clock_count <= clock_count + 1'b1;
                    end
                end
                default: state <= TX_IDLE;
            endcase
        end
    end
endmodule
