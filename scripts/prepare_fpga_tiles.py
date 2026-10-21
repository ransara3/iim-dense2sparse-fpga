#!/usr/bin/env python3
"""Tile one P/T map pair in raster order for the 32x32 FPGA build.

Each tile is decoded independently. Coordinates can be mapped back to the source,
but components crossing tile boundaries are not stitched or deduplicated.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.uart_host import quantize_map


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--p-map', type=Path, required=True)
    parser.add_argument('--t-map', type=Path, required=True)
    parser.add_argument('--image', type=Path, help='Optional source image for preview crops; dimensions must match maps')
    parser.add_argument('--out-dir', type=Path, required=True, help='Use a new directory to avoid mixing tiles with older runs')
    parser.add_argument('--tile-size', type=int, default=32)
    args = parser.parse_args()
    if not 1 <= args.tile_size <= 32:
        parser.error('--tile-size must be 1..32')
    p, t = np.load(args.p_map), np.load(args.t_map)
    quantize_map(p, 'P')
    quantize_map(t, 'T')
    if p.ndim != 2 or t.shape != p.shape or not all(p.shape):
        parser.error('P/T must be matching nonempty 2D arrays')
    if np.any((quantize_map(t, 'T') < 51) | (quantize_map(t, 'T') > 178)):
        parser.error('T must quantize to codes 51..178')
    if args.out_dir.exists() and any(args.out_dir.iterdir()):
        parser.error('Output directory is not empty; choose a new directory')
    h, w = p.shape
    image = None
    if args.image:
        with Image.open(args.image) as source:
            image = source.copy()
        if image.size != (w, h):
            parser.error('Source image dimensions do not match maps')
    args.out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for row, y in enumerate(range(0, h, args.tile_size)):
        for col, x in enumerate(range(0, w, args.tile_size)):
            name = f'tile_{len(manifest):06d}_r{row:04d}_c{col:04d}'
            crop_p = p[y:y+args.tile_size, x:x+args.tile_size]
            crop_t = t[y:y+args.tile_size, x:x+args.tile_size]
            prefix = args.out_dir / name
            np.save(str(prefix) + '_P.npy', crop_p)
            np.save(str(prefix) + '_T.npy', crop_t)
            metadata = dict(name=name, crop_origin=[x, y], source_shape=[h, w],
                            tile_shape=list(crop_p.shape),
                            source_p_map=str(args.p_map.resolve()),
                            source_t_map=str(args.t_map.resolve()),
                            source_image=str(args.image.resolve()) if args.image else None,
                            boundary_policy='independent tiles; no component stitching')
            Path(str(prefix) + '_meta.json').write_text(json.dumps(metadata, indent=2) + '\n')
            if image:
                image.crop((x, y, x+crop_p.shape[1], y+crop_p.shape[0])).save(str(prefix) + '_crop.png')
            manifest.append(metadata)
    (args.out_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Prepared {len(manifest)} tiles covering all {w*h} pixels of {w}x{h} maps.')
    print('Order: top-left to top-right, then the next row, ending bottom-right.')
    print('Right/bottom edge tiles retain their actual smaller dimensions.')
    print(f'Validate with: python reference_algorithm/validate_fpga.py --maps-dir {args.out_dir}')
    print('Tile head counts must not be added together as a full-photo crowd count.')


if __name__ == '__main__':
    main()
