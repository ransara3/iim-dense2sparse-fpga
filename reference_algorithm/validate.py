#!/usr/bin/env python3
"""Validate the reference_algorithm implementation of Algorithm 1 against:

1. Mathematical equivalence: margin-gated binarization must produce exactly
   the same B as naive `1[P >= T]`, for any T bounded in (0.2, 0.7) -- this
   is the core property the FPGA paper's datapath optimization relies on.
2. Baseline agreement: `streaming_ccl`'s detected centroids/count must match
   OpenCV's `cv2.connectedComponentsWithStats(..., connectivity=4)` on the
   same B map (same algorithm, same answer, different control flow).

Usage:
    python reference_algorithm/validate.py --maps-dir data/maps
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reference_algorithm.margin_gated_ccl import margin_gated_binarize, streaming_ccl


def check_binarization_equivalence(rng: np.random.Generator, trials: int = 20, size=(64, 64)) -> bool:
    ok = True
    for _ in range(trials):
        P = rng.uniform(0.0, 1.0, size=size)
        # T bounded strictly inside (0.2, 0.7), as compressedSigmoid guarantees.
        T = rng.uniform(0.2001, 0.6999, size=size)
        gated = margin_gated_binarize(P, T)
        naive = (P >= T).astype(np.uint8)
        if not np.array_equal(gated, naive):
            ok = False
            print("[FAIL] margin-gated binarization diverged from naive P>=T")
    if ok:
        print(f"[ok] margin-gated binarization == naive P>=T across {trials} random trials")
    return ok


def check_ccl_against_opencv(b_path: Path, min_area: int = 3) -> bool:
    import cv2

    B = np.load(b_path)
    B2d = B.squeeze().astype(np.uint8)

    t0 = time.perf_counter()
    ref_components = streaming_ccl(B2d, min_area=min_area)
    t1 = time.perf_counter()

    cnt, labels, stats, centroids = cv2.connectedComponentsWithStats(B2d, connectivity=4)
    boxes = stats[1:, :]
    cv_points = centroids[1:, :][boxes[:, 4] >= min_area]
    t2 = time.perf_counter()

    ref_points = np.array(sorted((c.x, c.y) for c in ref_components))
    cv_points_sorted = np.array(sorted(map(tuple, cv_points)))

    same_count = len(ref_points) == len(cv_points_sorted)
    same_points = same_count and np.allclose(ref_points, cv_points_sorted, atol=1e-6)

    status = "ok" if same_points else "FAIL"
    print(f"[{status}] {b_path.name}: streaming_ccl={len(ref_points)} pts "
          f"({t1 - t0:.2f}s) vs opencv={len(cv_points_sorted)} pts ({t2 - t1:.3f}s)")
    if not same_points:
        print(f"       ref_points[:5]={ref_points[:5].tolist()}")
        print(f"       cv_points[:5] ={cv_points_sorted[:5].tolist()}")
    return same_points


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--maps-dir", type=Path, default=Path("data/maps"))
    parser.add_argument("--min-area", type=int, default=3)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    all_ok = check_binarization_equivalence(rng)

    b_files = sorted(args.maps_dir.glob("*_B.npy"))
    if not b_files:
        print(f"[warn] no *_B.npy files found in {args.maps_dir}; "
              "run scripts/dump_maps.py or scripts/synth_maps_from_gt.py first")
    for b_path in b_files:
        all_ok &= check_ccl_against_opencv(b_path, min_area=args.min_area)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
