`timescale 1ns/1ps

module tb_margin_gated_ccl;
    localparam integer WIDTH = 8;
    localparam integer HEIGHT = 4;
    localparam integer SUM_WIDTH = 16;

    reg clk = 1'b0;
    reg reset_n = 1'b0;
    reg start = 1'b0;
    reg [3:0] frame_width = WIDTH;
    reg [2:0] frame_height = HEIGHT;
    reg in_valid = 1'b0;
    wire in_ready;
    reg [7:0] p_value = 0;
    reg [7:0] t_value = 8'd128;
    wire component_valid;
    reg component_ready = 1'b0;
    wire [SUM_WIDTH-1:0] component_sum_x;
    wire [SUM_WIDTH-1:0] component_sum_y;
    wire [31:0] component_area;
    wire frame_done;
    wire overflow;

    integer found_a = 0;
    integer found_b = 0;
    integer received = 0;
    integer cycles = 0;
    integer row;
    integer col;
    reg foreground;
    reg component_was_stalled = 1'b0;
    reg [SUM_WIDTH-1:0] held_sum_x;
    reg [SUM_WIDTH-1:0] held_sum_y;
    reg [31:0] held_area;

    always #5 clk = ~clk;

    margin_gated_ccl #(
        .MAX_WIDTH(WIDTH),
        .MAX_HEIGHT(HEIGHT),
        .MAX_LABELS(32),
        .MIN_AREA(2),
        .SUM_WIDTH(SUM_WIDTH)
    ) dut (
        .clk(clk),
        .reset_n(reset_n),
        .start(start),
        .frame_width(frame_width),
        .frame_height(frame_height),
        .in_valid(in_valid),
        .in_ready(in_ready),
        .p_value(p_value),
        .t_value(t_value),
        .component_valid(component_valid),
        .component_ready(component_ready),
        .component_sum_x(component_sum_x),
        .component_sum_y(component_sum_y),
        .component_area(component_area),
        .frame_done(frame_done),
        .overflow(overflow)
    );

    always @(posedge clk) begin
        if (reset_n)
            cycles <= cycles + 1;
        if (component_valid && !component_ready) begin
            if (component_was_stalled &&
                (component_sum_x !== held_sum_x ||
                 component_sum_y !== held_sum_y ||
                 component_area !== held_area))
                $fatal(1, "component output changed while back-pressured");
            component_was_stalled = 1'b1;
            held_sum_x = component_sum_x;
            held_sum_y = component_sum_y;
            held_area = component_area;
        end else if (component_was_stalled) begin
            if (!component_valid ||
                component_sum_x !== held_sum_x ||
                component_sum_y !== held_sum_y ||
                component_area !== held_area)
                $fatal(1, "component output was not held until accepted");
            component_was_stalled = 1'b0;
        end
        if (component_valid && component_ready) begin
            received = received + 1;
            if (component_area == 5 && component_sum_x == 5 && component_sum_y == 3)
                found_a = found_a + 1;
            else if (component_area == 3 && component_sum_x == 16 && component_sum_y == 2)
                found_b = found_b + 1;
            else begin
                $display("Unexpected component: area=%0d sum_x=%0d sum_y=%0d",
                         component_area, component_sum_x, component_sum_y);
                $fatal(1);
            end

        end
    end

    always @(negedge clk)
        component_ready = (cycles % 4 != 0);

    task send_pixel;
        input integer x;
        input integer y;
        begin
            foreground = ((y == 0 && (x == 0 || x == 2 || x == 5 || x == 7)) ||
                          (y == 1 && (x == 0 || x == 1 || x == 2 || x == 5 || x == 6)) ||
                          (y == 3 && x == 3));
            @(negedge clk);
            in_valid = 1'b1;
            if (foreground) begin
                p_value = 8'd220;
                t_value = 8'd100;
            end else begin
                p_value = 8'd20;
                t_value = 8'd128;
            end
            if (x == 1 && y == 1) begin
                p_value = 8'd110;
                t_value = 8'd110;
            end
            if (x == 4 && y == 2) begin
                p_value = 8'd150;
                t_value = 8'd128;
            end
            while (!in_ready)
                @(negedge clk);
            @(posedge clk);
            @(negedge clk);
            in_valid = 1'b0;
        end
    endtask

    initial begin
        repeat (3) @(negedge clk);
        reset_n = 1'b1;
        @(negedge clk);
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;
        wait (in_ready);

        for (row = 0; row < HEIGHT; row = row + 1)
            for (col = 0; col < WIDTH; col = col + 1)
                send_pixel(col, row);

        wait (frame_done);
        @(negedge clk);
        if (overflow)
            $fatal(1, "label storage overflowed");
        if (received != 2 || found_a != 1 || found_b != 1)
            $fatal(1, "wrong component results: received=%0d A=%0d B=%0d",
                   received, found_a, found_b);

        $display("PASS pixels=%0d components=%0d cycles=%0d",
                 WIDTH * HEIGHT, received, cycles);
        $finish;
    end

    initial begin
        #1000000;
        $fatal(1, "simulation timed out");
    end
endmodule
