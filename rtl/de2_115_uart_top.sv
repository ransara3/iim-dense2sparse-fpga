`timescale 1ns/1ps

module de2_115_uart_top #(
    parameter integer CLK_HZ = 50_000_000,
    parameter integer BAUD = 115_200,
    parameter integer MAX_WIDTH = 1280,
    parameter integer MAX_HEIGHT = 720,
    parameter integer MAX_LABELS = 2048,
    parameter integer MIN_AREA = 3
) (
    input  wire clk,
    input  wire reset_n,
    input  wire uart_rxd,
    output wire uart_txd,
    output wire overflow
);
    localparam integer CLKS_PER_BIT = (CLK_HZ + BAUD / 2) / BAUD;
    localparam integer X_WIDTH = $clog2(MAX_WIDTH + 1);
    localparam integer Y_WIDTH = $clog2(MAX_HEIGHT + 1);
    localparam [4:0] RX_SYNC_M       = 5'd0;
    localparam [4:0] RX_SYNC_G       = 5'd1;
    localparam [4:0] RX_WIDTH_LO     = 5'd2;
    localparam [4:0] RX_WIDTH_HI     = 5'd3;
    localparam [4:0] RX_HEIGHT_LO    = 5'd4;
    localparam [4:0] RX_HEIGHT_HI    = 5'd5;
    localparam [4:0] RX_WAIT_CORE    = 5'd6;
    localparam [4:0] RX_WAIT_READY   = 5'd7;
    localparam [4:0] RX_PIXEL_P      = 5'd8;
    localparam [4:0] RX_PIXEL_T      = 5'd9;
    localparam [4:0] RX_PIXEL_CORE   = 5'd10;
    localparam [4:0] RX_ROW_END      = 5'd11;
    localparam [4:0] RX_ROW_ACK      = 5'd12;
    localparam [4:0] RX_FRAME_ACK    = 5'd13;
    localparam [4:0] RX_ERROR_ACK    = 5'd14;

    localparam [2:0] TX_IDLE         = 3'd0;
    localparam [2:0] TX_LAUNCH       = 3'd1;
    localparam [2:0] TX_WAIT         = 3'd2;
    localparam [2:0] TX_COMPONENT    = 3'd0;
    localparam [2:0] TX_READY_ACK    = 3'd1;
    localparam [2:0] TX_ROW_ACK      = 3'd2;
    localparam [2:0] TX_FRAME_ACK    = 3'd3;
    localparam [2:0] TX_ERROR_ACK    = 3'd4;

    reg [4:0] rx_state;
    reg [2:0] tx_state;
    reg [2:0] tx_message_kind;
    reg [7:0] tx_payload [0:12];
    reg [4:0] tx_length;
    reg [4:0] tx_index;
    reg [7:0] tx_data;
    reg tx_start;
    wire tx_busy;
    wire tx_done;

    wire [7:0] rx_data;
    wire rx_valid;
    wire rx_framing_error;

    reg [15:0] width_header;
    reg [7:0] height_low;
    reg [X_WIDTH-1:0] core_width;
    reg [Y_WIDTH-1:0] core_height;
    reg [X_WIDTH-1:0] col_pos;
    reg [Y_WIDTH-1:0] row_pos;
    reg [7:0] pixel_p;
    reg [7:0] pixel_t;
    reg pixel_pending;

    reg core_start;
    wire core_in_ready;
    wire core_component_valid;
    wire [31:0] core_sum_x;
    wire [31:0] core_sum_y;
    wire [31:0] core_area;
    wire [31:0] core_active_cycles;
    wire core_frame_done;
    wire core_overflow;
    wire core_component_ready = (tx_state == TX_IDLE);
    reg [31:0] component_count;

    reg request_ready;
    reg request_row;
    reg request_frame;
    reg request_error;
    reg ready_sent;
    reg row_sent;
    reg frame_sent;
    reg error_sent;

    uart_rx_8n1 #(.CLKS_PER_BIT(CLKS_PER_BIT)) receiver (
        .clk(clk),
        .reset_n(reset_n),
        .rx(uart_rxd),
        .data(rx_data),
        .valid(rx_valid),
        .framing_error(rx_framing_error)
    );

    uart_tx_8n1 #(.CLKS_PER_BIT(CLKS_PER_BIT)) transmitter (
        .clk(clk),
        .reset_n(reset_n),
        .start(tx_start),
        .data(tx_data),
        .tx(uart_txd),
        .busy(tx_busy),
        .done(tx_done)
    );

    margin_gated_ccl #(
        .MAX_WIDTH(MAX_WIDTH),
        .MAX_HEIGHT(MAX_HEIGHT),
        .MAX_LABELS(MAX_LABELS),
        .MIN_AREA(MIN_AREA),
        .SUM_WIDTH(32),
        .X_WIDTH(X_WIDTH),
        .Y_WIDTH(Y_WIDTH)
    ) engine (
        .clk(clk),
        .reset_n(reset_n),
        .start(core_start),
        .frame_width(core_width),
        .frame_height(core_height),
        .in_valid(pixel_pending),
        .in_ready(core_in_ready),
        .p_value(pixel_p),
        .t_value(pixel_t),
        .component_valid(core_component_valid),
        .component_ready(core_component_ready),
        .component_sum_x(core_sum_x),
        .component_sum_y(core_sum_y),
        .component_area(core_area),
        .active_cycles(core_active_cycles),
        .frame_done(core_frame_done),
        .overflow(core_overflow)
    );

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            rx_state <= RX_SYNC_M;
            tx_state <= TX_IDLE;
            tx_message_kind <= TX_COMPONENT;
            tx_length <= 0;
            tx_index <= 0;
            tx_data <= 8'h00;
            tx_start <= 1'b0;
            width_header <= 0;
            height_low <= 0;
            core_width <= 0;
            core_height <= 0;
            col_pos <= 0;
            row_pos <= 0;
            pixel_p <= 0;
            pixel_t <= 0;
            pixel_pending <= 1'b0;
            core_start <= 1'b0;
            component_count <= 0;
            request_ready <= 1'b0;
            request_row <= 1'b0;
            request_frame <= 1'b0;
            request_error <= 1'b0;
            ready_sent <= 1'b0;
            row_sent <= 1'b0;
            frame_sent <= 1'b0;
            error_sent <= 1'b0;
        end else begin
            tx_start <= 1'b0;
            core_start <= 1'b0;
            ready_sent <= 1'b0;
            row_sent <= 1'b0;
            frame_sent <= 1'b0;
            error_sent <= 1'b0;

            if (core_overflow && rx_state != RX_SYNC_M) begin
                request_error <= 1'b1;
                pixel_pending <= 1'b0;
                rx_state <= RX_ERROR_ACK;
            end else if (rx_framing_error) begin
                request_error <= 1'b1;
                pixel_pending <= 1'b0;
                rx_state <= RX_ERROR_ACK;
            end else begin
                case (rx_state)
                    RX_SYNC_M: begin
                        if (rx_valid) begin
                            if (rx_data == 8'h4d)
                                rx_state <= RX_SYNC_G;
                            else
                                rx_state <= RX_SYNC_M;
                        end
                    end
                    RX_SYNC_G: begin
                        if (rx_valid) begin
                            if (rx_data == 8'h47)
                                rx_state <= RX_WIDTH_LO;
                            else if (rx_data == 8'h4d)
                                rx_state <= RX_SYNC_G;
                            else
                                rx_state <= RX_SYNC_M;
                        end
                    end
                    RX_WIDTH_LO: begin
                        if (rx_valid) begin
                            width_header[7:0] <= rx_data;
                            rx_state <= RX_WIDTH_HI;
                        end
                    end
                    RX_WIDTH_HI: begin
                        if (rx_valid) begin
                            width_header[15:8] <= rx_data;
                            rx_state <= RX_HEIGHT_LO;
                        end
                    end
                    RX_HEIGHT_LO: begin
                        if (rx_valid) begin
                            height_low <= rx_data;
                            rx_state <= RX_HEIGHT_HI;
                        end
                    end
                    RX_HEIGHT_HI: begin
                        if (rx_valid) begin
                            if (width_header == 0 || width_header > MAX_WIDTH ||
                                {rx_data, height_low} == 0 ||
                                {rx_data, height_low} > MAX_HEIGHT) begin
                                request_error <= 1'b1;
                                rx_state <= RX_ERROR_ACK;
                            end else begin
                                core_width <= width_header[X_WIDTH-1:0];
                                core_height <= {rx_data, height_low};
                                col_pos <= 0;
                                row_pos <= 0;
                                component_count <= 0;
                                core_start <= 1'b1;
                                rx_state <= RX_WAIT_CORE;
                            end
                        end
                    end
                    RX_WAIT_CORE: begin
                        if (core_in_ready) begin
                            request_ready <= 1'b1;
                            rx_state <= RX_WAIT_READY;
                        end
                    end
                    RX_WAIT_READY: begin
                        if (ready_sent)
                            rx_state <= RX_PIXEL_P;
                    end
                    RX_PIXEL_P: begin
                        if (rx_valid) begin
                            pixel_p <= rx_data;
                            rx_state <= RX_PIXEL_T;
                        end
                    end
                    RX_PIXEL_T: begin
                        if (rx_valid) begin
                            pixel_t <= rx_data;
                            pixel_pending <= 1'b1;
                            rx_state <= RX_PIXEL_CORE;
                        end
                    end
                    RX_PIXEL_CORE: begin
                        if (core_in_ready) begin
                            pixel_pending <= 1'b0;
                            if (col_pos == core_width - 1'b1) begin
                                col_pos <= 0;
                                rx_state <= RX_ROW_END;
                            end else begin
                                col_pos <= col_pos + 1'b1;
                                rx_state <= RX_PIXEL_P;
                            end
                        end
                    end
                    RX_ROW_END: begin
                        if (core_overflow) begin
                            request_error <= 1'b1;
                            rx_state <= RX_ERROR_ACK;
                        end else if (row_pos == core_height - 1'b1) begin
                            if (core_frame_done) begin
                                request_frame <= 1'b1;
                                rx_state <= RX_FRAME_ACK;
                            end
                        end else if (core_in_ready) begin
                            request_row <= 1'b1;
                            rx_state <= RX_ROW_ACK;
                        end
                    end
                    RX_ROW_ACK: begin
                        if (row_sent) begin
                            row_pos <= row_pos + 1'b1;
                            rx_state <= RX_PIXEL_P;
                        end
                    end
                    RX_FRAME_ACK: begin
                        if (frame_sent)
                            rx_state <= RX_SYNC_M;
                    end
                    RX_ERROR_ACK: begin
                        if (error_sent)
                            rx_state <= RX_SYNC_M;
                    end
                    default: rx_state <= RX_SYNC_M;
                endcase
            end

            if (tx_state == TX_IDLE) begin
                if (core_component_valid) begin
                    tx_payload[0] <= 8'hc1;
                    tx_payload[1] <= core_area[7:0];
                    tx_payload[2] <= core_area[15:8];
                    tx_payload[3] <= core_area[23:16];
                    tx_payload[4] <= core_area[31:24];
                    tx_payload[5] <= core_sum_x[7:0];
                    tx_payload[6] <= core_sum_x[15:8];
                    tx_payload[7] <= core_sum_x[23:16];
                    tx_payload[8] <= core_sum_x[31:24];
                    tx_payload[9] <= core_sum_y[7:0];
                    tx_payload[10] <= core_sum_y[15:8];
                    tx_payload[11] <= core_sum_y[23:16];
                    tx_payload[12] <= core_sum_y[31:24];
                    tx_length <= 13;
                    tx_index <= 0;
                    tx_message_kind <= TX_COMPONENT;
                    component_count <= component_count + 1'b1;
                    tx_state <= TX_LAUNCH;
                end else if (request_error) begin
                    tx_payload[0] <= 8'he0;
                    tx_length <= 1;
                    tx_index <= 0;
                    tx_message_kind <= TX_ERROR_ACK;
                    request_error <= 1'b0;
                    tx_state <= TX_LAUNCH;
                end else if (request_ready) begin
                    tx_payload[0] <= 8'hac;
                    tx_length <= 1;
                    tx_index <= 0;
                    tx_message_kind <= TX_READY_ACK;
                    request_ready <= 1'b0;
                    tx_state <= TX_LAUNCH;
                end else if (request_row) begin
                    tx_payload[0] <= 8'ha6;
                    tx_length <= 1;
                    tx_index <= 0;
                    tx_message_kind <= TX_ROW_ACK;
                    request_row <= 1'b0;
                    tx_state <= TX_LAUNCH;
                end else if (request_frame) begin
                    tx_payload[0] <= 8'hcf;
                    tx_payload[1] <= component_count[7:0];
                    tx_payload[2] <= component_count[15:8];
                    tx_payload[3] <= component_count[23:16];
                    tx_payload[4] <= component_count[31:24];
                    tx_payload[5] <= core_active_cycles[7:0];
                    tx_payload[6] <= core_active_cycles[15:8];
                    tx_payload[7] <= core_active_cycles[23:16];
                    tx_payload[8] <= core_active_cycles[31:24];
                    tx_length <= 9;
                    tx_index <= 0;
                    tx_message_kind <= TX_FRAME_ACK;
                    request_frame <= 1'b0;
                    tx_state <= TX_LAUNCH;
                end
            end else if (tx_state == TX_LAUNCH) begin
                tx_data <= tx_payload[tx_index];
                tx_start <= 1'b1;
                tx_state <= TX_WAIT;
            end else if (tx_state == TX_WAIT && tx_done) begin
                if (tx_index == tx_length - 1'b1) begin
                    tx_state <= TX_IDLE;
                    case (tx_message_kind)
                        TX_READY_ACK: ready_sent <= 1'b1;
                        TX_ROW_ACK: row_sent <= 1'b1;
                        TX_FRAME_ACK: frame_sent <= 1'b1;
                        TX_ERROR_ACK: error_sent <= 1'b1;
                        default: begin end
                    endcase
                end else begin
                    tx_index <= tx_index + 1'b1;
                    tx_state <= TX_LAUNCH;
                end
            end
        end
    end
endmodule
