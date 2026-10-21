#!/usr/bin/env python3
"""Stream P/T maps to the DE2-115 UART wrapper and save detected centroids.

Protocol and board setup are documented in README.md.
"""
import argparse
import json
import time
from pathlib import Path
from typing import BinaryIO, Dict, List, Optional, Tuple, Union

import numpy as np

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reference_algorithm.margin_gated_ccl import streaming_ccl

READY = 0xAC
ROW_ACK = 0xA6
FRAME_DONE = 0xCF
COMPONENT = 0xC1
DEVICE_ERROR = 0xE0
MAX_WIDTH = 1280
MAX_HEIGHT = 720


def quantize_map(values: np.ndarray, name: str) -> np.ndarray:
    if values.ndim != 2:
        values = np.squeeze(values)
    if values.ndim != 2:
        raise ValueError(f"{name} must be a 2-D map after squeezing")
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{name} contains non-finite values")
    if np.any((values < 0) | (values > 1)):
        raise ValueError(f"{name} values must be in [0, 1]")
    return np.rint(values * 255).astype(np.uint8)


def read_exact(port: BinaryIO, length: int) -> bytes:
    data = port.read(length)
    if len(data) != length:
        raise TimeoutError(f"UART timed out: expected {length} bytes, received {len(data)}")
    return data


def write_all(port: BinaryIO, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = port.write(data[offset:])
        if written is None or written <= 0:
            raise TimeoutError(f"UART write stopped after {offset}/{len(data)} bytes")
        offset += written


def receive_response(
    port: BinaryIO,
    final_row: bool,
) -> Tuple[List[Dict[str, Union[int, float]]], Optional[int], Optional[int]]:
    components = []
    while True:
        tag = read_exact(port, 1)[0]
        if tag == COMPONENT:
            area, sum_x, sum_y = (
                int.from_bytes(read_exact(port, 4), byteorder="little")
                for _ in range(3)
            )
            if area == 0:
                raise RuntimeError("FPGA returned a zero-area component")
            components.append(
                {"x": sum_x / area, "y": sum_y / area, "area": area}
            )
        elif tag == DEVICE_ERROR:
            raise RuntimeError("FPGA rejected the frame or reported a core overflow")
        elif final_row and tag == FRAME_DONE:
            count = int.from_bytes(read_exact(port, 4), byteorder="little")
            active_cycles = int.from_bytes(read_exact(port, 4), byteorder="little")
            return components, count, active_cycles
        elif not final_row and tag == ROW_ACK:
            return components, None, None
        else:
            raise RuntimeError(f"unexpected UART response tag 0x{tag:02x}")


def stream_maps(port: BinaryIO, P: np.ndarray, T: np.ndarray) -> dict[str, object]:
    p8 = quantize_map(P, "P")
    t8 = quantize_map(T, "T")
    if p8.shape != t8.shape:
        raise ValueError("P and T must have the same shape")
    height, width = p8.shape
    if not (1 <= width <= MAX_WIDTH and 1 <= height <= MAX_HEIGHT):
        raise ValueError(f"frame must be within 1..{MAX_WIDTH} x 1..{MAX_HEIGHT}")
    if np.any((t8 < 51) | (t8 > 178)):
        raise ValueError("T must quantize into codes 51..178 (IIM's (0.2, 0.7) range)")

    header = bytes((0x4D, 0x47)) + width.to_bytes(2, "little") + height.to_bytes(2, "little")
    write_all(port, header)
    response = read_exact(port, 1)[0]
    if response == DEVICE_ERROR:
        raise ValueError("FPGA rejected the frame dimensions")
    if response != READY:
        raise RuntimeError(f"expected ready tag 0x{READY:02x}, got 0x{response:02x}")

    components: list[dict[str, int]] = []
    frame_count: Optional[int] = None
    active_cycles: Optional[int] = None
    for row in range(height):
        pixels = np.empty((width * 2,), dtype=np.uint8)
        pixels[0::2] = p8[row]
        pixels[1::2] = t8[row]
        write_all(port, pixels.tobytes())
        row_components, row_count, row_cycles = receive_response(
            port, final_row=row == height - 1
        )
        components.extend(row_components)
        if row_count is not None:
            frame_count = row_count
            active_cycles = row_cycles

    if frame_count != len(components) or active_cycles is None:
        raise RuntimeError(
            f"invalid final response: FPGA reported {frame_count} components, "
            f"host received {len(components)} records, active_cycles={active_cycles}"
        )
    return {
        "num": len(components),
        "points": components,
        "rtl_active_cycles": active_cycles,
    }


def cpu_reference_records(P: np.ndarray, T: np.ndarray) -> list[tuple[int, int, int]]:
    p8 = quantize_map(P, "P")
    t8 = quantize_map(T, "T")
    components = streaming_ccl((p8 >= t8).astype(np.uint8), min_area=3)
    return sorted(
        (
            component.area,
            round(component.x * component.area),
            round(component.y * component.area),
        )
        for component in components
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", choices=["uart", "jtag"], default="uart")
    parser.add_argument("--jtag-library", type=Path, help="Path to libjtag_atlantic.so or jtag_atlantic.dll")
    parser.add_argument("--cable", help="USB-Blaster cable name; omit to auto-select")
    parser.add_argument("--device", type=int, default=1, help="JTAG chain device index (1-based)")
    parser.add_argument("--instance", type=int, default=0, help="JTAG UART instance index (0-based)")
    parser.add_argument("--port", help="serial device (e.g. /dev/ttyUSB0)")
    parser.add_argument("--p-map", type=Path, required=True)
    parser.add_argument("--t-map", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="destination JSON file")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout", type=float, default=30.0)
    args = parser.parse_args()

    if args.transport == "jtag":
        if args.jtag_library is None:
            parser.error("--jtag-library is required for JTAG transport")
        from scripts.jtag_atlantic import JtagAtlantic
        connection = lambda: JtagAtlantic(args.jtag_library, args.cable, args.device,
                                          args.instance, args.timeout)
    else:
        if not args.port:
            parser.error("--port is required for UART transport")
        try:
            import serial
        except ImportError as exc:
            raise SystemExit("Install requirements-hardware.txt for UART transport") from exc
        connection = lambda: serial.Serial(args.port, args.baud, timeout=args.timeout,
                                           write_timeout=args.timeout)

    P = np.load(args.p_map)
    T = np.load(args.t_map)
    if args.transport == "jtag":
        shape = quantize_map(P, "P").shape
        if any(dimension > 32 for dimension in shape):
            parser.error("JTAG bring-up build supports at most 32x32 pixels; use a crop")
    start = time.perf_counter()
    expected = cpu_reference_records(P, T)
    cpu_seconds = time.perf_counter() - start
    with connection() as port:
        result = stream_maps(port, P, T)
    actual = sorted(
        (
            int(point["area"]),
            round(float(point["x"]) * int(point["area"])),
            round(float(point["y"]) * int(point["area"])),
        )
        for point in result["points"]
    )
    if actual != expected:
        raise RuntimeError(f"FPGA output differs from CPU reference\n"
                           f"expected={expected}\nactual={actual}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"CPU reference: {cpu_seconds:.3f}s; "
          f"RTL active cycles (UART stalls excluded): {result['rtl_active_cycles']}")
    print(f"Received {result['num']} components; wrote {args.output}")


if __name__ == "__main__":
    main()
