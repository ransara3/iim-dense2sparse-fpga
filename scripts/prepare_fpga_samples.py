#!/usr/bin/env python3
"""Prepare 32x32 synthetic map pairs from many JHU image/annotation pairs.

These are annotation-driven synthetic maps, NOT trained IIM predictions.
Full-size synthetic maps are generated first; only a head-centered crop is saved.
"""
import argparse
import json
from pathlib import Path
import sys
import zlib

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.synth_maps_from_gt import load_points, synth_P, synth_T


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--annotations', type=Path, required=True, help='JHU gt/ folder with matching .txt files')
    parser.add_argument('--out-dir', type=Path, default=Path('data/fpga_samples'))
    parser.add_argument('--limit', type=int, default=20, help='Number of distinct photos to prepare')
    args = parser.parse_args()
    if args.limit < 1:
        parser.error('--limit must be positive')
    if not args.images.is_dir() or not args.annotations.is_dir():
        parser.error('Image and annotation directories must exist')
    args.out_dir.mkdir(parents=True, exist_ok=True)
    made = 0
    for image_path in sorted(args.images.iterdir()):
        if image_path.suffix.lower() not in ('.jpg', '.jpeg', '.png'):
            continue
        gt = args.annotations / (image_path.stem + '.txt')
        if not gt.exists():
            continue
        points = load_points(gt)
        with Image.open(image_path) as image:
            w, h = image.size
            if min(w, h) < 32:
                continue
            # Center the crop on an annotated point, or the image center for empty GT.
            x, y = points[0] if len(points) else (w // 2, h // 2)
            x0 = max(0, min(int(x) - 16, w - 32))
            y0 = max(0, min(int(y) - 16, h - 32))
            p = synth_P(h, w, points) if len(points) else np.zeros((h, w), dtype=np.float32)
            t = synth_T(h, w, seed=zlib.crc32(image_path.stem.encode()))
            prefix = args.out_dir / image_path.stem
            np.save(str(prefix) + '_P.npy', p[y0:y0+32, x0:x0+32])
            np.save(str(prefix) + '_T.npy', t[y0:y0+32, x0:x0+32])
            image.crop((x0, y0, x0+32, y0+32)).save(str(prefix) + '_crop.png')
            metadata = dict(source_image=str(image_path.resolve()), annotations=str(gt.resolve()),
                            source_shape=[h, w], crop_origin=[x0, y0],
                            map_source='synthetic_from_ground_truth')
            Path(str(prefix) + '_meta.json').write_text(json.dumps(metadata, indent=2) + '\n')
        made += 1
        print(f'[ok] {image_path.name}: synthetic crop origin=({x0},{y0})', flush=True)
        if made >= args.limit:
            break
    if not made:
        parser.error('No usable image/annotation pairs found')
    print(f'Prepared {made} distinct photos in {args.out_dir}')


if __name__ == '__main__':
    main()
