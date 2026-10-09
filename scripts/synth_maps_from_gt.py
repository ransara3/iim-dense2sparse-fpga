#!/usr/bin/env python3
"""Generate realistic stand-in P(x,y)/T(x,y)/B(x,y) maps from JHU-CROWD++
ground-truth point annotations, for use when a pretrained IIM checkpoint is
unavailable (upstream pretrained-weight links are dead, see
https://github.com/taohan10200/IIM/issues/41).

This does NOT run the IIM network at all. Instead it builds maps that are
*statistically realistic* stand-ins, using the exact same math IIM itself
uses downstream of the network:
  - P(x,y): a Gaussian-blurred head-dot density map, squashed to [0, 1] with
    a sigmoid (matching HRNet's `last_layer` which ends in `nn.Sigmoid()`,
    see IIM/model/HR_Net/seg_hrnet.py).
  - T(x,y): a smooth per-pixel threshold bounded in (0.2, 0.7), generated
    with the exact `compressedSigmoid(para=2.0, bias=0.2)` formula IIM uses
    in model/PBM.py, driven by mild low-frequency noise so T varies spatially
    like a learned threshold map would.
  - B(x,y) = 1[P >= T], identical to IIM's BinarizedF.

This lets Step 2 (the margin-gated dense-to-sparse reference algorithm) be
developed and validated against OpenCV's connectedComponentsWithStats without
being blocked on a dead checkpoint download.

GT file format (JHU-CROWD++): one row per head, "x y w h occlusion blur".
Only the first two columns (x, y) are used here.

Usage:
    python scripts/synth_maps_from_gt.py \
        --images data/samples --out-dir data/maps
"""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reference_algorithm.margin_gated_ccl import margin_gated_binarize, streaming_ccl

PARA = 2.0
BIAS = 0.2


def compressed_sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (PARA + np.exp(-x)) + BIAS


def load_points(gt_path: Path) -> np.ndarray:
    pts = []
    for line in gt_path.read_text().splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        x, y = float(parts[0]), float(parts[1])
        pts.append((x, y))
    return np.array(pts, dtype=np.float32)


def gaussian_kernel1d(sigma: float):
    radius = max(1, int(3 * sigma))
    x = np.arange(-radius, radius + 1)
    k = np.exp(-(x ** 2) / (2 * sigma ** 2))
    return k / k.sum()


def separable_blur(img: np.ndarray, sigma: float) -> np.ndarray:
    k = gaussian_kernel1d(sigma)
    out = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), axis=1, arr=img)
    out = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), axis=0, arr=out)
    return out


def synth_P(h: int, w: int, points: np.ndarray, sigma: float = 4.0) -> np.ndarray:
    dots = np.zeros((h, w), dtype=np.float32)
    xs = np.clip(points[:, 0].astype(int), 0, w - 1)
    ys = np.clip(points[:, 1].astype(int), 0, h - 1)
    dots[ys, xs] = 1.0
    density = separable_blur(dots, sigma)
    if density.max() > 0:
        density = density / density.max()
    # Map density -> confidence-like logits, then squash with the same
    # sigmoid shape IIM's HRNet head uses, so P ends up spread across [0, 1]
    # with background near 0 and head centers near 1.
    logits = (density - 0.5) * 10.0
    p = 1.0 / (1.0 + np.exp(-logits))
    return p.astype(np.float32)


def synth_T(h: int, w: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    coarse = rng.normal(size=(h // 16 + 2, w // 16 + 2)).astype(np.float32)
    coarse = separable_blur(coarse, sigma=2.0)
    t_logits = np.array(Image.fromarray(coarse).resize((w, h), Image.BILINEAR))
    return compressed_sigmoid(t_logits).astype(np.float32)


def get_boxInfo_from_Binar_map(binar_numpy: np.ndarray, min_area: int = 3):
    import cv2

    binar_numpy = binar_numpy.squeeze().astype(np.uint8)
    cnt, labels, stats, centroids = cv2.connectedComponentsWithStats(binar_numpy, connectivity=4)
    boxes = stats[1:, :]
    points = centroids[1:, :]
    index = boxes[:, 4] >= min_area
    points = points[index]
    return {"num": int(len(points)), "points": points.tolist()}


def localize_margin_gated(p_np: np.ndarray, t_np: np.ndarray, min_area: int = 3):
    b_np = margin_gated_binarize(p_np, t_np)
    components = streaming_ccl(b_np, min_area=min_area)
    return {"num": len(components), "points": [asdict(c) for c in components]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", type=Path, required=True, help="Directory with <name>.jpg + <name>.txt GT pairs")
    parser.add_argument("--out-dir", type=Path, default=Path("data/maps"))
    parser.add_argument("--sigma", type=float, default=4.0, help="Gaussian blur sigma (px) for the density proxy")
    parser.add_argument("--min-area", type=int, default=3)
    parser.add_argument("--localizer", choices=["margin_gated", "opencv"], default="margin_gated",
                        help="Dense-to-sparse post-processing: our margin-gated streaming CCL "
                             "(reference_algorithm/) or the original IIM/test.py cv2-based baseline")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    img_paths = sorted(p for p in args.images.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not img_paths:
        raise SystemExit(f"No images found in {args.images}")

    for img_path in img_paths:
        gt_path = img_path.with_suffix(".txt")
        if not gt_path.exists():
            print(f"[skip] {img_path.name}: no matching GT file {gt_path.name}")
            continue

        img = Image.open(img_path)
        w, h = img.size
        points = load_points(gt_path)

        p_np = synth_P(h, w, points, sigma=args.sigma) if len(points) else np.zeros((h, w), dtype=np.float32)
        t_np = synth_T(h, w, seed=hash(img_path.stem) & 0xFFFFFFFF)
        b_np = (p_np >= t_np).astype(np.uint8)

        stem = img_path.stem
        np.save(args.out_dir / f"{stem}_P.npy", p_np)
        np.save(args.out_dir / f"{stem}_T.npy", t_np)
        np.save(args.out_dir / f"{stem}_B.npy", b_np)

        pred = localize_margin_gated(p_np, t_np, min_area=args.min_area) if args.localizer == "margin_gated" \
            else get_boxInfo_from_Binar_map(b_np, min_area=args.min_area)
        with open(args.out_dir / f"{stem}_points.json", "w") as f:
            json.dump(pred, f)

        print(f"[ok] {img_path.name}: gt_points={len(points)}, "
              f"P range=({p_np.min():.3f},{p_np.max():.3f}), "
              f"T range=({t_np.min():.3f},{t_np.max():.3f}), "
              f"localizer={args.localizer}, detected_points={pred['num']}")


if __name__ == "__main__":
    main()
