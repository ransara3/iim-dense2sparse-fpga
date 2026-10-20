import unittest

import numpy as np

from reference_algorithm.quantization_sweep import analyze_precision, quantize_unit_interval


class QuantizationSweepTests(unittest.TestCase):
    def test_shared_monotone_quantization_preserves_foreground(self):
        rng = np.random.default_rng(7)
        P = rng.random((32, 48))
        T = rng.uniform(0.2, 0.7, size=P.shape)

        for bits in (1, 2, 4, 8, 16):
            metrics = analyze_precision(P, T, bits)
            self.assertTrue(metrics["baseline_subset_of_quantized"])
            self.assertEqual(metrics["split_count"], 0)

    def test_quantization_merge_and_pixel_f1_metrics(self):
        P = np.array([[0.9, 0.49, 0.9]])
        T = np.full_like(P, 0.5)

        metrics = analyze_precision(P, T, bits=1)

        self.assertEqual(metrics["baseline_components"], 2)
        self.assertEqual(metrics["quantized_components"], 1)
        self.assertEqual(metrics["merge_count"], 1)
        self.assertEqual(metrics["split_count"], 0)
        self.assertEqual(metrics["added_foreground_pixels"], 1)
        self.assertAlmostEqual(metrics["pixel_f1"], 0.8)

    def test_quantizer_rejects_values_outside_unit_interval(self):
        with self.assertRaises(ValueError):
            quantize_unit_interval(np.array([1.01]), bits=8)


if __name__ == "__main__":
    unittest.main()
