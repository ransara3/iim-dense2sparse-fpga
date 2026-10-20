`timescale 1ns/1ps

module tb_margin_gated_ccl_vectors #(
    parameter integer WIDTH = 32,
    parameter integer HEIGHT = 32
);
    localparam integer X_WIDTH = $clog2(WIDTH + 1);
    localparam integer Y_WIDTH = $clog2(HEIGHT + 1);
    localparam integer SUM_WIDTH = 32;
    localparam integer MAX_LABELS = 2 * WIDTH + 2;

    reg clk = 1'b0;
    reg reset_n = 1'b0;
    reg start = 1'b0;
    reg [X_WIDTH-1:0] frame_width = WIDTH;
    reg [Y_WIDTH-1:0] frame_height = HEIGHT;
    reg in_valid = 1'b0;
    wire in_ready;
    reg [7:0] p_value = 0;
    reg [7:0] t_value = 0;
    wire component_valid;
    reg component_ready = 1'b0;
    wire [SUM_WIDTH-1:0] component_sum_x;
    wire [SUM_WIDTH-1:0] component_sum_y;
    wire [31:0] component_area;
    wire frame_done;
    wire overflow;

    reg [15:0] pixels [0:WIDTH*HEIGHT-1];
    integer cycles = 0;
    integer index;
    integer result_fd;
    reg [1023:0] input_path;
    reg [1023:0] result_path;
    reg component_was_stalled = 1'b0;
    reg [SUM_WIDTH-1:0] held_sum_x;
    reg [SUM_WIDTH-1:0] held_sum_y;
    reg [31:0] held_area;

    always #5 clk = ~clk;

    margin_gated_ccl #(
        .MAX_WIDTH(WIDTH),
        .MAX_HEIGHT(HEIGHT),
        .MAX_LABELS(MAX_LABELS),
        .MIN_AREA(3),
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
        if (component_valid && component_ready)
            $fdisplay(result_fd, "%0d,%0d,%0d",
                      component_area, component_sum_x, component_sum_y);
    end

    always @(negedge clk)
        component_ready = (cycles % 4 != 0);

    initial begin
        if (!$value$plusargs("input=%s", input_path))
            $fatal(1, "missing +input=<path>");
        if (!$value$plusargs("results=%s", result_path))
            $fatal(1, "missing +results=<path>");
        $readmemh(input_path, pixels);
        result_fd = $fopen(result_path, "w");
        if (result_fd == 0)
            $fatal(1, "could not open results file");

        repeat (3) @(negedge clk);
        reset_n = 1'b1;
        @(negedge clk);
        start = 1'b1;
        @(negedge clk);
        start = 1'b0;
        wait (in_ready);

        @(negedge clk);
        for (index = 0; index < WIDTH * HEIGHT; index = index + 1) begin
            while (!in_ready)
                @(negedge clk);
            in_valid = 1'b1;
            p_value = pixels[index][15:8];
            t_value = pixels[index][7:0];
            @(posedge clk);
            @(negedge clk);
        end
        in_valid = 1'b0;

        wait (frame_done);
        @(negedge clk);
        if (overflow)
            $fatal(1, "label storage overflowed");
        $fclose(result_fd);
        $display("PASS pixels=%0d cycles=%0d", WIDTH * HEIGHT, cycles);
        $finish;
    end

    initial begin
        #100000000;
        $fatal(1, "simulation timed out");
    end
endmodule
