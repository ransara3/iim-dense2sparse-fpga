`timescale 1ns/1ps

module tb_de2_115_uart_top;
    localparam integer BIT_CYCLES = 16;

    reg clk = 1'b0;
    reg reset_n = 1'b0;
    reg uart_rxd = 1'b1;
    wire uart_txd;
    wire overflow;
    reg [7:0] received;
    reg [31:0] record_area;
    reg [31:0] record_sum_x;
    reg [31:0] record_sum_y;
    reg [31:0] final_count;
    reg [31:0] rtl_cycles;
    reg [31:0] component_records = 0;
    reg saw_a = 1'b0;
    reg saw_b = 1'b0;
    integer bit_index;

    always #5 clk = ~clk;

    de2_115_uart_top #(
        .CLK_HZ(BIT_CYCLES),
        .BAUD(1),
        .MAX_WIDTH(8),
        .MAX_HEIGHT(4),
        .MAX_LABELS(32),
        .MIN_AREA(2)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .uart_rxd(uart_rxd),
        .uart_txd(uart_txd),
        .overflow(overflow)
    );

    task send_uart_byte;
        input [7:0] value;
        integer i;
        begin
            @(negedge clk);
            uart_rxd = 1'b0;
            repeat (BIT_CYCLES) @(negedge clk);
            for (i = 0; i < 8; i = i + 1) begin
                uart_rxd = value[i];
                repeat (BIT_CYCLES) @(negedge clk);
            end
            uart_rxd = 1'b1;
            repeat (BIT_CYCLES) @(negedge clk);
        end
    endtask

    task receive_uart_byte;
        output [7:0] value;
        integer i;
        begin
            @(negedge uart_txd);
            repeat (BIT_CYCLES + BIT_CYCLES/2) @(posedge clk);
            for (i = 0; i < 8; i = i + 1) begin
                value[i] = uart_txd;
                repeat (BIT_CYCLES) @(posedge clk);
            end
            if (uart_txd !== 1'b1)
                $fatal(1, "UART stop bit was not high");
            repeat (BIT_CYCLES/2) @(posedge clk);
        end
    endtask

    task send_pixel;
        input integer foreground;
        input integer equal_threshold;
        begin
            if (foreground) begin
                send_uart_byte(8'd220);
                send_uart_byte(8'd100);
            end else if (equal_threshold) begin
                send_uart_byte(8'd110);
                send_uart_byte(8'd110);
            end else begin
                send_uart_byte(8'd20);
                send_uart_byte(8'd128);
            end
        end
    endtask

    task receive_component;
        integer i;
        reg [7:0] bytes [0:11];
        begin
            for (i = 0; i < 12; i = i + 1)
                receive_uart_byte(bytes[i]);
            record_area = {bytes[3], bytes[2], bytes[1], bytes[0]};
            record_sum_x = {bytes[7], bytes[6], bytes[5], bytes[4]};
            record_sum_y = {bytes[11], bytes[10], bytes[9], bytes[8]};
            component_records = component_records + 1;
            if (record_area == 5 && record_sum_x == 5 && record_sum_y == 3)
                saw_a = 1'b1;
            else if (record_area == 3 && record_sum_x == 16 && record_sum_y == 2)
                saw_b = 1'b1;
            else
                $fatal(1, "unexpected component (%0d,%0d,%0d)",
                       record_area, record_sum_x, record_sum_y);
        end
    endtask

    initial begin
        repeat (4) @(negedge clk);
        reset_n = 1'b1;

        send_uart_byte(8'h4d);
        send_uart_byte(8'h47);
        send_uart_byte(8'd8);
        send_uart_byte(8'd0);
        send_uart_byte(8'd4);
        send_uart_byte(8'd0);
        receive_uart_byte(received);
        if (received != 8'hac)
            $fatal(1, "expected ready byte AC, got %02x", received);

        send_pixel(1, 0);
        send_pixel(0, 0);
        send_pixel(1, 0);
        send_pixel(0, 0);
        send_pixel(0, 0);
        send_pixel(1, 0);
        send_pixel(0, 0);
        send_pixel(1, 0);
        receive_uart_byte(received);
        if (received != 8'ha6)
            $fatal(1, "expected first row ack A6, got %02x", received);

        send_pixel(1, 0);
        send_pixel(0, 1);
        send_pixel(1, 0);
        send_pixel(0, 0);
        send_pixel(0, 0);
        send_pixel(1, 0);
        send_pixel(1, 0);
        send_pixel(0, 0);
        receive_uart_byte(received);
        if (received != 8'ha6)
            $fatal(1, "expected second row ack A6, got %02x", received);

        repeat (8) send_pixel(0, 0);
        receive_uart_byte(received);
        if (received != 8'hc1)
            $fatal(1, "expected component record C1, got %02x", received);
        receive_component();
        receive_uart_byte(received);
        if (received != 8'hc1)
            $fatal(1, "expected second component record C1, got %02x", received);
        receive_component();
        receive_uart_byte(received);
        if (received != 8'ha6)
            $fatal(1, "expected third row ack A6, got %02x", received);

        send_pixel(0, 0);
        send_pixel(0, 0);
        send_pixel(0, 0);
        send_pixel(0, 1);
        send_pixel(0, 0);
        send_pixel(0, 0);
        send_pixel(0, 0);
        send_pixel(0, 0);
        receive_uart_byte(received);
        if (received != 8'hcf)
            $fatal(1, "expected frame-done tag CF, got %02x", received);
        for (bit_index = 0; bit_index < 4; bit_index = bit_index + 1) begin
            receive_uart_byte(received);
            final_count[bit_index*8 +: 8] = received;
        end
        for (bit_index = 0; bit_index < 4; bit_index = bit_index + 1) begin
            receive_uart_byte(received);
            rtl_cycles[bit_index*8 +: 8] = received;
        end
        if (final_count != 2 || rtl_cycles == 0 || overflow ||
            component_records != 2 || !saw_a || !saw_b)
            $fatal(1, "final UART result mismatch: count=%0d records=%0d overflow=%0d",
                   final_count, component_records, overflow);

        send_uart_byte(8'h4d);
        send_uart_byte(8'h47);
        send_uart_byte(8'd1);
        send_uart_byte(8'd0);
        send_uart_byte(8'd1);
        send_uart_byte(8'd0);
        receive_uart_byte(received);
        if (received != 8'hac)
            $fatal(1, "second frame did not receive ready byte AC");
        send_pixel(0, 0);
        receive_uart_byte(received);
        if (received != 8'hcf)
            $fatal(1, "second frame did not receive frame-done tag CF");
        for (bit_index = 0; bit_index < 4; bit_index = bit_index + 1) begin
            receive_uart_byte(received);
            final_count[bit_index*8 +: 8] = received;
        end
        for (bit_index = 0; bit_index < 4; bit_index = bit_index + 1) begin
            receive_uart_byte(received);
            rtl_cycles[bit_index*8 +: 8] = received;
        end
        if (final_count != 0 || rtl_cycles == 0 || overflow || component_records != 2)
            $fatal(1, "second frame state was not reset correctly");

        send_uart_byte(8'h4d);
        send_uart_byte(8'h47);
        send_uart_byte(8'd0);
        send_uart_byte(8'd0);
        send_uart_byte(8'd1);
        fork
            send_uart_byte(8'd0);
            receive_uart_byte(received);
        join
        if (received != 8'he0)
            $fatal(1, "invalid dimensions should return error tag E0");

        $display("PASS UART protocol: multi-frame, components, row handshake and backpressure");
        $finish;
    end

    initial begin
        #100000000;
        $fatal(1, "UART test timed out: rx_state=%0d tx_state=%0d error_req=%0d",
               dut.rx_state, dut.tx_state, dut.request_error);
    end
endmodule
