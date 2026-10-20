import io
import unittest

import numpy as np

from scripts.uart_host import cpu_reference_records, quantize_map, receive_response, stream_maps


class MemorySerial:
    def __init__(self, responses: bytes):
        self.responses = io.BytesIO(responses)
        self.written = bytearray()

    def read(self, size: int) -> bytes:
        return self.responses.read(size)

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)


class UartHostTests(unittest.TestCase):
    def test_quantize_map_checks_range_and_shape(self):
        np.testing.assert_array_equal(
            quantize_map(np.array([[0.0, 0.5, 1.0]]), "P"),
            np.array([[0, 128, 255]], dtype=np.uint8),
        )
        with self.assertRaises(ValueError):
            quantize_map(np.array([1.1]), "P")
        with self.assertRaises(ValueError):
            quantize_map(np.zeros((1, 1, 1)), "P")

    def test_receive_component_record_and_row_ack(self):
        record = (
            bytes((0xC1,))
            + (3).to_bytes(4, "little")
            + (4).to_bytes(4, "little")
            + (5).to_bytes(4, "little")
        )
        port = MemorySerial(record + bytes((0xA6,)))

        components, frame_count, active_cycles = receive_response(port, final_row=False)

        self.assertEqual(components, [{"x": 4 / 3, "y": 5 / 3, "area": 3}])
        self.assertIsNone(frame_count)
        self.assertIsNone(active_cycles)

    def test_stream_maps_sends_header_and_quantized_pixels(self):
        port = MemorySerial(
            bytes((0xAC, 0xCF))
            + (0).to_bytes(4, "little")
            + (1234).to_bytes(4, "little")
        )
        P = np.array([[0.1, 0.2]], dtype=np.float32)
        T = np.array([[0.5, 0.6]], dtype=np.float32)

        result = stream_maps(port, P, T)

        self.assertEqual(result, {"num": 0, "points": [], "rtl_active_cycles": 1234})
        expected = (
            bytes((0x4D, 0x47, 0x02, 0x00, 0x01, 0x00))
            + bytes((26, 128, 51, 153))
        )
        self.assertEqual(port.written, expected)

    def test_stream_maps_rejects_threshold_outside_iim_range(self):
        port = MemorySerial(b"")
        with self.assertRaises(ValueError):
            stream_maps(port, np.array([[0.5]]), np.array([[0.8]]))
        self.assertEqual(port.written, b"")

    def test_cpu_reference_uses_area_and_coordinate_sums(self):
        P = np.array([[0.9, 0.9], [0.9, 0.1]])
        T = np.full_like(P, 0.5)

        self.assertEqual(cpu_reference_records(P, T), [(3, 1, 1)])


if __name__ == "__main__":
    unittest.main()
