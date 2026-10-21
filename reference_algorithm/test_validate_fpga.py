import unittest
from unittest.mock import patch
import numpy as np
from reference_algorithm.validate_fpga import compare_case, head_locations


class ValidationTests(unittest.TestCase):
    def test_head_coordinates_and_crop_offset(self):
        self.assertEqual(head_locations([(4, 2, 6)], (10, 20)),
                         [dict(x=0.5, y=1.5, area=4, image_x=10.5, image_y=21.5)])

    def test_exact_records_and_mismatch(self):
        p = np.zeros((4, 8), dtype=np.float32)
        p[:2, :2] = 0.9
        t = np.full_like(p, 0.4)
        result = dict(num=1, points=[dict(area=4, x=0.5, y=0.5)], rtl_active_cycles=100)
        with patch('reference_algorithm.validate_fpga.stream_maps', return_value=result):
            self.assertTrue(compare_case(None, p, t, repeats=1)['ok'])
            result['points'][0]['area'] = 5
            self.assertFalse(compare_case(None, p, t, repeats=1)['ok'])

    def test_oversize_rejected_before_transfer(self):
        with patch('reference_algorithm.validate_fpga.stream_maps') as transfer:
            with self.assertRaises(ValueError):
                compare_case(None, np.zeros((33, 32)), np.full((33, 32), 0.4))
            transfer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
