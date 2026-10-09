#!/usr/bin/env python3
"""Run a (pretrained or randomly initialized) IIM model and dump the dense
confidence map P(x,y), the learned threshold map T(x,y), and the binary map
B(x,y) = 1[P >= T] for a set of images.

These maps are the realistic test vectors needed by the margin-gated,
quantization-aware dense-to-sparse FPGA engine project: see ../README.md.

Usage:
    python scripts/dump_maps.py \
        --iim-root ../IIM \
        --net HR_Net \
        --checkpoint data/checkpoints/some_model.pth \
        --dataset SHHB \
        --images data/samples \
        --out-dir data/maps

Omit --checkpoint to run in "smoke test" mode with random weights, which
validates shapes/dataflow only (outputs are not meaningful for accuracy).
"""
import argparse
import json
import os
import sys
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reference_algorithm.margin_gated_ccl import margin_gated_binarize, streaming_ccl

# Per-dataset normalization stats, copied from IIM/test.py so preprocessing
# matches what each checkpoint was trained with.
MEAN_STD = {
    "NWPU": ([0.446139603853, 0.409515678883, 0.395083993673], [0.288205742836, 0.278144598007, 0.283502370119]),
    "SHHA": ([0.410824894905, 0.370634973049, 0.359682112932], [0.278580576181, 0.26925137639, 0.27156367898]),
    "SHHB": ([0.452016860247, 0.447249650955, 0.431981861591], [0.23242045939, 0.224925786257, 0.221840232611]),
    "QNRF": ([0.413525998592, 0.378520160913, 0.371616870165], [0.284849464893, 0.277046442032, 0.281509846449]),
    "FDST": ([0.452016860247, 0.447249650955, 0.431981861591], [0.23242045939, 0.224925786257, 0.221840232611]),
    "JHU": ([0.429683953524, 0.437104910612, 0.421978861094], [0.235549390316, 0.232568427920, 0.2355950474739]),
}

IMG_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


class CPUCrowdLocator(nn.Module):
    """CPU-friendly re-implementation of IIM's Crowd_locator.

    Mirrors the submodule names ("Extractor", "Binar") used by the upstream
    Crowd_locator so that pretrained checkpoints load without key renaming,
    but never forces `.cuda()`, so it also works on machines without a GPU.
    """

    def __init__(self, net_name: str):
        super().__init__()
        if net_name == "HR_Net":
            from model.HR_Net.seg_hrnet import get_seg_model

            self.Extractor = get_seg_model()
            from model.PBM import BinarizedModule

            self.Binar = BinarizedModule(input_channels=720)
        elif net_name == "VGG16_FPN":
            from model.VGG.VGG16_FPN import VGG16_FPN
            from model.PBM import BinarizedModule

            self.Extractor = VGG16_FPN()
            self.Binar = BinarizedModule(input_channels=768)
        else:
            raise ValueError(f"Unknown net_name: {net_name}")

    def forward(self, img: torch.Tensor):
        feature, pre_map = self.Extractor(img)
        threshold_matrix, binar_map = self.Binar(feature, pre_map)
        return threshold_matrix, pre_map, binar_map


def load_checkpoint(model: nn.Module, checkpoint_path: Path):
    state_dict = torch.load(checkpoint_path, map_location="cpu")
    cleaned = OrderedDict((k.replace("module.", ""), v) for k, v in state_dict.items())
    missing, unexpected = model.load_state_dict(cleaned, strict=False)
    if missing:
        print(f"[warn] missing keys when loading checkpoint: {missing}")
    if unexpected:
        print(f"[warn] unexpected keys when loading checkpoint: {unexpected}")


def pad_to_multiple(img: torch.Tensor, multiple: int = 32):
    """Pad NCHW tensor so H and W are multiples of `multiple`. Returns padded
    tensor and the (h, w) to crop back to afterward."""
    _, _, h, w = img.shape
    pad_h = (multiple - h % multiple) % multiple
    pad_w = (multiple - w % multiple) % multiple
    if pad_h or pad_w:
        img = F.pad(img, (0, pad_w, 0, pad_h), mode="constant", value=0)
    return img, (h, w)


def get_boxInfo_from_Binar_map(binar_numpy: np.ndarray, min_area: int = 3):
    """Same connected-component + centroid logic as IIM's test.py, kept here
    so dumped maps can be cross-checked against the baseline post-processing."""
    import cv2

    binar_numpy = binar_numpy.squeeze().astype(np.uint8)
    assert binar_numpy.ndim == 2
    cnt, labels, stats, centroids = cv2.connectedComponentsWithStats(binar_numpy, connectivity=4)
    boxes = stats[1:, :]
    points = centroids[1:, :]
    index = boxes[:, 4] >= min_area
    boxes = boxes[index]
    points = points[index]
    return {"num": int(len(points)), "points": points.tolist()}


def localize_margin_gated(p_np: np.ndarray, t_np: np.ndarray, min_area: int = 3):
    """Our margin-gated binarization + streaming CCL (reference_algorithm/),
    in place of the original plain-threshold + cv2 pipeline above."""
    b_np = margin_gated_binarize(p_np, t_np)
    components = streaming_ccl(b_np, min_area=min_area)
    return {"num": len(components), "points": [asdict(c) for c in components]}


def find_images(images_arg: Path):
    if images_arg.is_file():
        return [images_arg]
    return sorted(p for p in images_arg.iterdir() if p.suffix.lower() in IMG_EXTENSIONS)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--iim-root", type=Path, default=Path("../IIM"), help="Path to the IIM repo checkout")
    parser.add_argument("--net", choices=["HR_Net", "VGG16_FPN"], default="HR_Net")
    parser.add_argument("--checkpoint", type=Path, default=None, help="Pretrained .pth file (omit for smoke test)")
    parser.add_argument("--dataset", choices=sorted(MEAN_STD), default="SHHB", help="Selects normalization stats")
    parser.add_argument("--images", type=Path, required=True, help="Image file or directory of images")
    parser.add_argument("--out-dir", type=Path, default=Path("data/maps"))
    parser.add_argument("--min-area", type=int, default=3, help="Min blob area (px) kept as a detected point")
    parser.add_argument("--localizer", choices=["margin_gated", "opencv"], default="margin_gated",
                        help="Dense-to-sparse post-processing: our margin-gated streaming CCL "
                             "(reference_algorithm/) or the original IIM/test.py cv2-based baseline")
    args = parser.parse_args()

    # Resolve all user-provided paths to absolute *before* changing directory,
    # since upstream IIM code (get_seg_model) loads its HRNet yaml config via
    # a path relative to the current working directory.
    args.checkpoint = args.checkpoint.resolve() if args.checkpoint else None
    args.images = args.images.resolve()
    args.out_dir = args.out_dir.resolve()
    iim_root = args.iim_root.resolve()

    sys.path.insert(0, str(iim_root))
    os.chdir(iim_root)

    model = CPUCrowdLocator(args.net)
    model.eval()

    if args.checkpoint is not None:
        load_checkpoint(model, args.checkpoint)
        print(f"[info] loaded checkpoint: {args.checkpoint}")
    else:
        print("[warn] no --checkpoint given: running in SMOKE-TEST mode with random weights. "
              "Dumped maps/points are only useful to validate shapes/dataflow, not accuracy.")

    mean, std = MEAN_STD[args.dataset]
    mean_t = torch.tensor(mean).view(1, 3, 1, 1)
    std_t = torch.tensor(std).view(1, 3, 1, 1)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    images = find_images(args.images)
    if not images:
        raise SystemExit(f"No images found at {args.images}")

    for img_path in images:
        img = Image.open(img_path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        arr = torch.from_numpy(np.array(img)).permute(2, 0, 1).float().div(255.0).unsqueeze(0)
        arr = (arr - mean_t) / std_t
        arr, (orig_h, orig_w) = pad_to_multiple(arr, multiple=32)

        with torch.no_grad():
            threshold_matrix, pre_map, binar_map = model(arr)

        # crop back to the original (un-padded) image size
        threshold_matrix = threshold_matrix[:, :, :orig_h, :orig_w]
        pre_map = pre_map[:, :, :orig_h, :orig_w]
        binar_map = binar_map[:, :, :orig_h, :orig_w]

        p_np = pre_map.squeeze(0).squeeze(0).numpy()
        t_np = threshold_matrix.squeeze(0).squeeze(0).numpy()
        b_np = binar_map.squeeze(0).squeeze(0).numpy()

        stem = img_path.stem
        np.save(args.out_dir / f"{stem}_P.npy", p_np.astype(np.float32))
        np.save(args.out_dir / f"{stem}_T.npy", t_np.astype(np.float32))
        np.save(args.out_dir / f"{stem}_B.npy", b_np.astype(np.uint8))

        if args.localizer == "margin_gated":
            pre_data = localize_margin_gated(p_np, t_np, min_area=args.min_area)
        else:
            pre_data = get_boxInfo_from_Binar_map(b_np, min_area=args.min_area)
        with open(args.out_dir / f"{stem}_points.json", "w") as f:
            json.dump(pre_data, f)

        print(f"[ok] {img_path.name}: P/T range=({p_np.min():.3f},{p_np.max():.3f})/"
              f"({t_np.min():.3f},{t_np.max():.3f}), localizer={args.localizer}, "
              f"detected points={pre_data['num']}")


if __name__ == "__main__":
    main()
