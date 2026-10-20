`timescale 1ns/1ps

module margin_gated_ccl #(
    parameter integer MAX_WIDTH = 1280,
    parameter integer MAX_HEIGHT = 1024,
    parameter integer MAX_LABELS = 2048,
    parameter integer MIN_AREA = 3,
    parameter integer SUM_WIDTH = 48,
    parameter integer X_WIDTH = $clog2(MAX_WIDTH + 1),
    parameter integer Y_WIDTH = $clog2(MAX_HEIGHT + 1),
    parameter integer LABEL_WIDTH = $clog2(MAX_LABELS)
) (
    input  wire                  clk,
    input  wire                  reset_n,
    input  wire                  start,
    input  wire [X_WIDTH-1:0]    frame_width,
    input  wire [Y_WIDTH-1:0]    frame_height,
    input  wire                  in_valid,
    output wire                  in_ready,
    input  wire [7:0]            p_value,
    input  wire [7:0]            t_value,
    output reg                   component_valid,
    input  wire                  component_ready,
    output reg  [SUM_WIDTH-1:0]  component_sum_x,
    output reg  [SUM_WIDTH-1:0]  component_sum_y,
    output reg  [31:0]           component_area,
    output reg  [31:0]           active_cycles,
    output reg                   frame_done,
    output reg                   overflow
);

    localparam [2:0] ST_IDLE    = 3'd0;
    localparam [2:0] ST_CLEAR   = 3'd1;
    localparam [2:0] ST_PIXELS  = 3'd2;
    localparam [2:0] ST_CANON   = 3'd3;
    localparam [2:0] ST_SWEEP   = 3'd4;
    localparam [2:0] ST_EMIT    = 3'd5;
    localparam [2:0] ST_DONE    = 3'd6;

    localparam integer CLEAR_CYCLES =
        (MAX_LABELS > MAX_WIDTH) ? MAX_LABELS : MAX_WIDTH;

    reg [2:0] state;
    reg [X_WIDTH-1:0] width_reg;
    reg [Y_WIDTH-1:0] height_reg;
    reg [X_WIDTH-1:0] x_pos;
    reg [Y_WIDTH-1:0] y_pos;
    reg prev_bank;
    reg [31:0] clear_pos;
    reg [X_WIDTH-1:0] canon_pos;
    reg [LABEL_WIDTH:0] sweep_pos;

    reg [LABEL_WIDTH-1:0] row0 [0:MAX_WIDTH-1];
    reg [LABEL_WIDTH-1:0] row1 [0:MAX_WIDTH-1];
    reg [LABEL_WIDTH-1:0] parent [0:MAX_LABELS-1];
    reg [LABEL_WIDTH-1:0] rank [0:MAX_LABELS-1];
    reg used [0:MAX_LABELS-1];
    reg seen_this_row [0:MAX_LABELS-1];
    reg [31:0] area [0:MAX_LABELS-1];
    reg [SUM_WIDTH-1:0] sum_x [0:MAX_LABELS-1];
    reg [SUM_WIDTH-1:0] sum_y [0:MAX_LABELS-1];

    reg [LABEL_WIDTH-1:0] left_label;
    reg [LABEL_WIDTH-1:0] up_label;
    reg [LABEL_WIDTH-1:0] left_root;
    reg [LABEL_WIDTH-1:0] up_root;
    reg [LABEL_WIDTH-1:0] alloc_label;
    reg alloc_found;
    integer alloc_i;
    wire pixel_foreground =
        (p_value >= 8'd51) && ((p_value >= 8'd179) || (p_value >= t_value));

    function [LABEL_WIDTH-1:0] find_root;
        input [LABEL_WIDTH-1:0] label;
        integer depth;
        reg [LABEL_WIDTH-1:0] root;
        begin
            root = label;
            for (depth = 0; depth < LABEL_WIDTH; depth = depth + 1) begin
                if (parent[root] != root)
                    root = parent[root];
            end
            find_root = root;
        end
    endfunction

    always @* begin
        left_label = {LABEL_WIDTH{1'b0}};
        up_label = {LABEL_WIDTH{1'b0}};
        if (x_pos != 0) begin
            if (prev_bank)
                left_label = row0[x_pos - 1'b1];
            else
                left_label = row1[x_pos - 1'b1];
        end
        if (prev_bank)
            up_label = row1[x_pos];
        else
            up_label = row0[x_pos];

        left_root = {LABEL_WIDTH{1'b0}};
        up_root = {LABEL_WIDTH{1'b0}};
        if (left_label != 0)
            left_root = find_root(left_label);
        if (up_label != 0)
            up_root = find_root(up_label);

        alloc_found = 1'b0;
        alloc_label = {LABEL_WIDTH{1'b0}};
        for (alloc_i = 1; alloc_i < MAX_LABELS; alloc_i = alloc_i + 1) begin
            if (!alloc_found && !used[alloc_i]) begin
                alloc_found = 1'b1;
                alloc_label = alloc_i[LABEL_WIDTH-1:0];
            end
        end
    end

    assign in_ready = (state == ST_PIXELS);

    always @(posedge clk or negedge reset_n) begin
        if (!reset_n) begin
            state <= ST_IDLE;
            width_reg <= 0;
            height_reg <= 0;
            x_pos <= 0;
            y_pos <= 0;
            prev_bank <= 1'b0;
            clear_pos <= 0;
            canon_pos <= 0;
            sweep_pos <= 0;
            component_valid <= 1'b0;
            component_sum_x <= 0;
            component_sum_y <= 0;
            component_area <= 0;
            active_cycles <= 0;
            frame_done <= 1'b0;
            overflow <= 1'b0;
        end else begin
            frame_done <= 1'b0;

            case (state)
                ST_IDLE, ST_DONE: begin
                    if (start) begin
                        component_valid <= 1'b0;
                        overflow <= 1'b0;
                        active_cycles <= 0;
                        width_reg <= frame_width;
                        height_reg <= frame_height;
                        x_pos <= 0;
                        y_pos <= 0;
                        prev_bank <= 1'b0;
                        clear_pos <= 0;
                        if (frame_width == 0 || frame_width > MAX_WIDTH ||
                            frame_height == 0 || frame_height > MAX_HEIGHT) begin
                            overflow <= 1'b1;
                            frame_done <= 1'b1;
                            state <= ST_DONE;
                        end else begin
                            state <= ST_CLEAR;
                        end
                    end
                end

                ST_CLEAR: begin
                    active_cycles <= active_cycles + 1'b1;
                    if (clear_pos < MAX_WIDTH) begin
                        row0[clear_pos] <= 0;
                        row1[clear_pos] <= 0;
                    end
                    if (clear_pos < MAX_LABELS) begin
                        used[clear_pos] <= 1'b0;
                        seen_this_row[clear_pos] <= 1'b0;
                    end
                    if (clear_pos == CLEAR_CYCLES - 1) begin
                        clear_pos <= 0;
                        state <= ST_PIXELS;
                    end else begin
                        clear_pos <= clear_pos + 1'b1;
                    end
                end

                ST_PIXELS: begin
                    if (in_valid) begin
                        active_cycles <= active_cycles + 1'b1;
                        if (p_value < 8'd51) begin
                            if (prev_bank)
                                row0[x_pos] <= 0;
                            else
                                row1[x_pos] <= 0;
                        end else if (pixel_foreground) begin
                            if (left_root == 0 && up_root == 0) begin
                                if (!alloc_found) begin
                                    overflow <= 1'b1;
                                    frame_done <= 1'b1;
                                    state <= ST_DONE;
                                end else begin
                                    used[alloc_label] <= 1'b1;
                                    parent[alloc_label] <= alloc_label;
                                    rank[alloc_label] <= 0;
                                    area[alloc_label] <= 1;
                                    sum_x[alloc_label] <= x_pos;
                                    sum_y[alloc_label] <= y_pos;
                                    seen_this_row[alloc_label] <= 1'b1;
                                    if (prev_bank)
                                        row0[x_pos] <= alloc_label;
                                    else
                                        row1[x_pos] <= alloc_label;
                                end
                            end else if (left_root == 0 || up_root == 0 ||
                                         left_root == up_root) begin
                                if (left_root != 0) begin
                                    area[left_root] <= area[left_root] + 1'b1;
                                    sum_x[left_root] <= sum_x[left_root] + x_pos;
                                    sum_y[left_root] <= sum_y[left_root] + y_pos;
                                    seen_this_row[left_root] <= 1'b1;
                                    if (prev_bank)
                                        row0[x_pos] <= left_root;
                                    else
                                        row1[x_pos] <= left_root;
                                end else begin
                                    area[up_root] <= area[up_root] + 1'b1;
                                    sum_x[up_root] <= sum_x[up_root] + x_pos;
                                    sum_y[up_root] <= sum_y[up_root] + y_pos;
                                    seen_this_row[up_root] <= 1'b1;
                                    if (prev_bank)
                                        row0[x_pos] <= up_root;
                                    else
                                        row1[x_pos] <= up_root;
                                end
                            end else begin
                                if (rank[left_root] >= rank[up_root]) begin
                                    parent[up_root] <= left_root;
                                    area[left_root] <= area[left_root] + area[up_root] + 1'b1;
                                    sum_x[left_root] <= sum_x[left_root] + sum_x[up_root] + x_pos;
                                    sum_y[left_root] <= sum_y[left_root] + sum_y[up_root] + y_pos;
                                    seen_this_row[left_root] <= 1'b1;
                                    seen_this_row[up_root] <= 1'b0;
                                    if (rank[left_root] == rank[up_root])
                                        rank[left_root] <= rank[left_root] + 1'b1;
                                    if (prev_bank)
                                        row0[x_pos] <= left_root;
                                    else
                                        row1[x_pos] <= left_root;
                                end else begin
                                    parent[left_root] <= up_root;
                                    area[up_root] <= area[left_root] + area[up_root] + 1'b1;
                                    sum_x[up_root] <= sum_x[left_root] + sum_x[up_root] + x_pos;
                                    sum_y[up_root] <= sum_y[left_root] + sum_y[up_root] + y_pos;
                                    seen_this_row[up_root] <= 1'b1;
                                    seen_this_row[left_root] <= 1'b0;
                                    if (prev_bank)
                                        row0[x_pos] <= up_root;
                                    else
                                        row1[x_pos] <= up_root;
                                end
                            end
                        end else begin
                            if (prev_bank)
                                row0[x_pos] <= 0;
                            else
                                row1[x_pos] <= 0;
                        end

                        if (!(pixel_foreground && left_root == 0 &&
                              up_root == 0 && !alloc_found)) begin
                            if (x_pos == width_reg - 1'b1) begin
                                x_pos <= 0;
                                canon_pos <= 0;
                                state <= ST_CANON;
                            end else begin
                                x_pos <= x_pos + 1'b1;
                            end
                        end
                    end
                end

                ST_CANON: begin
                    active_cycles <= active_cycles + 1'b1;
                    if (canon_pos < width_reg) begin
                        if (prev_bank) begin
                            if (row0[canon_pos] != 0)
                                row0[canon_pos] <= find_root(row0[canon_pos]);
                        end else begin
                            if (row1[canon_pos] != 0)
                                row1[canon_pos] <= find_root(row1[canon_pos]);
                        end
                        canon_pos <= canon_pos + 1'b1;
                    end else begin
                        sweep_pos <= 1;
                        state <= ST_SWEEP;
                    end
                end

                ST_SWEEP: begin
                    active_cycles <= active_cycles + 1'b1;
                    if (sweep_pos < MAX_LABELS) begin
                        if (used[sweep_pos]) begin
                            if (parent[sweep_pos] == sweep_pos) begin
                                if (y_pos == height_reg - 1'b1 ||
                                    !seen_this_row[sweep_pos]) begin
                                    used[sweep_pos] <= 1'b0;
                                    seen_this_row[sweep_pos] <= 1'b0;
                                    if (area[sweep_pos] >= MIN_AREA) begin
                                        component_sum_x <= sum_x[sweep_pos];
                                        component_sum_y <= sum_y[sweep_pos];
                                        component_area <= area[sweep_pos];
                                        component_valid <= 1'b1;
                                        state <= ST_EMIT;
                                    end
                                end else begin
                                    seen_this_row[sweep_pos] <= 1'b0;
                                end
                            end else begin
                                used[sweep_pos] <= 1'b0;
                                seen_this_row[sweep_pos] <= 1'b0;
                            end
                        end
                        sweep_pos <= sweep_pos + 1'b1;
                    end else if (y_pos == height_reg - 1'b1) begin
                        frame_done <= 1'b1;
                        state <= ST_DONE;
                    end else begin
                        prev_bank <= ~prev_bank;
                        y_pos <= y_pos + 1'b1;
                        state <= ST_PIXELS;
                    end
                end

                ST_EMIT: begin
                    if (component_valid && component_ready) begin
                        active_cycles <= active_cycles + 1'b1;
                        component_valid <= 1'b0;
                        state <= ST_SWEEP;
                    end
                end

                default: begin
                    state <= ST_IDLE;
                end
            endcase
        end
    end

endmodule
