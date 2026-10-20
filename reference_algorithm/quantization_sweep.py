#!/usr/bin/env python3
"""Measure the effect of uniform P/T quantization on masks and CCL topology.

Usage:
    python reference_algorithm/quantization_sweep.py --maps-dir data/maps
"""
import argparse
import csv
import sys
from pathlib import Path
from typing import Union

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def quantize_unit_interval(values: np.ndarray, bits: int) -> np.ndarray:
    """Return unsigned integer codes for round-to-nearest uniform quantization."""
    if not 1 <= bits <= 16:
        raise ValueError("bits must be between 1 and 16")
    if not np.all(np.isfinite(values)):
        raise ValueError("map values must all be finite")
    if np.any((values < 0) | (values > 1)):
        raise ValueError("P and T values must be in [0, 1]")

    max_code = (1 << bits) - 1
    return np.rint(values * max_code).astype(np.uint32)


def _component_labels(mask: np.ndarray) -> tuple[int, np.ndarray]:
    import cv2

    count, labels = cv2.connectedComponents(mask.astype(np.uint8), connectivity=4)
    return count - 1, labels


def _topology_changes(
    baseline_labels: np.ndarray,
    quantized_labels: np.ndarray,
) -> tuple[int, int]:
    baseline_mask = baseline_labels != 0
    if np.any(baseline_mask & (quantized_labels == 0)):
        raise AssertionError("quantized mask removed baseline foreground pixels")

    overlaps = np.unique(
        np.column_stack((baseline_labels[baseline_mask], quantized_labels[baseline_mask])),
        axis=0,
    )
    if overlaps.size == 0:
        return 0, 0

    baseline_to_quantized = np.bincount(overlaps[:, 0])
    quantized_to_baseline = np.bincount(overlaps[:, 1])
    split_count = int(np.maximum(baseline_to_quantized - 1, 0).sum())
    merge_count = int(np.maximum(quantized_to_baseline - 1, 0).sum())
    return merge_count, split_count


def analyze_precision(
    P: np.ndarray,
    T: np.ndarray,
    bits: int,
) -> dict[str, Union[int, float, bool]]:
    """Analyze one precision against the full-precision P >= T reference."""
    if P.ndim != 2 or T.ndim != 2 or P.shape != T.shape:
        raise ValueError("P and T must be same-shaped 2-D arrays")

    baseline = P >= T
    p_codes = quantize_unit_interval(P, bits)
    t_codes = quantize_unit_interval(T, bits)
    quantized = p_codes >= t_codes
    subset = bool(np.all(~baseline | quantized))
    if not subset:
        raise AssertionError("monotone shared quantization must preserve B subset B_q")

    true_positive = int(np.count_nonzero(baseline & quantized))
    false_positive = int(np.count_nonzero(~baseline & quantized))
    false_negative = int(np.count_nonzero(baseline & ~quantized))
    denominator = 2 * true_positive + false_positive + false_negative
    pixel_f1 = 1.0 if denominator == 0 else (2.0 * true_positive / denominator)

    baseline_count, baseline_labels = _component_labels(baseline)
    quantized_count, quantized_labels = _component_labels(quantized)
    merge_count, split_count = _topology_changes(baseline_labels, quantized_labels)

    return {
        "bits": bits,
        "baseline_components": baseline_count,
        "quantized_components": quantized_count,
        "merge_count": merge_count,
        "split_count": split_count,
        "added_foreground_pixels": false_positive,
        "pixel_f1": pixel_f1,
        "pixel_f1_drift": 1.0 - pixel_f1,
        "baseline_subset_of_quantized": subset,
    }


def parse_bits(value: str) -> list[int]:
    try:
        bits = [int(part.strip()) for part in value.split(",")]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("bits must be comma-separated integers") from exc
    if not bits or any(not 1 <= bit <= 16 for bit in bits):
        raise argparse.ArgumentTypeError("each precision must be between 1 and 16 bits")
    if len(set(bits)) != len(bits):
        raise argparse.ArgumentTypeError("precisions must not contain duplicates")
    return bits


def load_map(path: Path) -> np.ndarray:
    values = np.load(path)
    values = np.squeeze(values)
    if values.ndim != 2:
        raise ValueError(f"{path} must contain a 2-D map after squeezing")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--maps-dir", type=Path, default=Path("data/maps"))
    parser.add_argument("--bits", type=parse_bits, default=parse_bits("4,6,8,10,12,16"))
    parser.add_argument("--output", type=Path, help="Optional CSV output path (default: stdout)")
    args = parser.parse_args()

    p_files = sorted(args.maps_dir.glob("*_P.npy"))
    if not p_files:
        parser.error(f"no *_P.npy maps found in {args.maps_dir}")

    rows: list[dict[str, Union[str, int, float, bool]]] = []
    for p_path in p_files:
        stem = p_path.name[:-6]
        t_path = p_path.with_name(f"{stem}_T.npy")
        b_path = p_path.with_name(f"{stem}_B.npy")
        if not t_path.is_file():
            raise FileNotFoundError(f"missing threshold map for {p_path.name}: {t_path}")

        P, T = load_map(p_path), load_map(t_path)
        if P.shape != T.shape:
            raise ValueError(f"{p_path.name} and {t_path.name} have different shapes")
        baseline = P >= T
        if b_path.is_file() and not np.array_equal(load_map(b_path).astype(bool), baseline):
            raise ValueError(f"saved binary map {b_path.name} does not match P >= T")

        for bit in args.bits:
            metrics = analyze_precision(P, T, bit)
            rows.append({"image": stem, **metrics})

    columns = [
        "image",
        "bits",
        "baseline_components",
        "quantized_components",
        "merge_count",
        "split_count",
        "added_foreground_pixels",
        "pixel_f1",
        "pixel_f1_drift",
        "baseline_subset_of_quantized",
    ]
    output = args.output.open("w", newline="") if args.output else sys.stdout
    try:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if args.output:
            output.close()


if __name__ == "__main__":
    main()
