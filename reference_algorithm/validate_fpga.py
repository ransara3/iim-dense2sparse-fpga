#!/usr/bin/env python3
"""Compare OpenCV CPU decoding with JTAG FPGA decoding of identical 8-bit maps.

Uses 4-connectivity and min_area=3 to match the programmed bring-up build.
CPU timing includes quantization, binarization and OpenCV CCL. FPGA round-trip
includes host quantization and communication, but excludes opening JTAG.
Core time is cycles / clock, an estimate requiring verified timing closure.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.jtag_atlantic import JtagAtlantic
from scripts.uart_host import quantize_map, stream_maps


def baseline(P, T):
    mask = (quantize_map(P, 'P') >= quantize_map(T, 'T')).astype(np.uint8)
    return cv2.connectedComponentsWithStats(mask, connectivity=4)


def baseline_records(decoded):
    count, labels, stats, _ = decoded
    yy, xx = np.indices(labels.shape)
    sx = np.bincount(labels.ravel(), weights=xx.ravel(), minlength=count)
    sy = np.bincount(labels.ravel(), weights=yy.ravel(), minlength=count)
    return sorted((int(stats[i, cv2.CC_STAT_AREA]), int(sx[i]), int(sy[i]))
                  for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= 3)


def fpga_records(result):
    return sorted((int(p['area']), round(p['x'] * p['area']),
                   round(p['y'] * p['area'])) for p in result['points'])


def head_locations(records, origin=(0, 0)):
    return [dict(x=sx / area, y=sy / area, area=area,
                 image_x=sx / area + origin[0], image_y=sy / area + origin[1])
            for area, sx, sy in records]


def compare_case(port, P, T, repeats=20, clock_hz=50_000_000):
    p8, t8 = quantize_map(P, 'P'), quantize_map(T, 'T')
    if p8.shape != t8.shape or any(d < 1 or d > 32 for d in p8.shape):
        raise ValueError('Bring-up FPGA requires matching nonempty P/T maps, at most 32x32')
    if np.any((t8 < 51) | (t8 > 178)):
        raise ValueError('T must quantize to codes 51..178')
    baseline(P, T)  # warm-up, excluded from median
    durations = []
    for _ in range(repeats):
        start = time.perf_counter()
        decoded = baseline(P, T)
        durations.append(time.perf_counter() - start)
    expected = baseline_records(decoded)
    start = time.perf_counter()
    result = stream_maps(port, P, T)
    roundtrip = time.perf_counter() - start
    actual = fpga_records(result)
    return dict(ok=expected == actual, cpu_points=len(expected),
                fpga_points=result['num'], cpu_median_seconds=float(np.median(durations)),
                fpga_roundtrip_seconds=roundtrip, rtl_active_cycles=result['rtl_active_cycles'],
                assumed_clock_hz=clock_hz,
                estimated_core_seconds=result['rtl_active_cycles'] / clock_hz,
                expected_records=expected, actual_records=actual,
                shape=list(p8.shape), fpga_result=result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--maps-dir', type=Path, default=Path('data/board_test'))
    parser.add_argument('--max-images', type=int, default=None, help='Default: all map pairs')
    parser.add_argument('--jtag-library', default=os.environ.get('JTAG_LIB'))
    parser.add_argument('--cable', default=None)
    parser.add_argument('--device', type=int, default=1)
    parser.add_argument('--instance', type=int, default=0)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--repeats', type=int, default=20)
    parser.add_argument('--clock-hz', type=float, default=50_000_000)
    parser.add_argument('--output', type=Path, default=Path('exp/fpga_validation.json'))
    args = parser.parse_args()
    if not args.jtag_library:
        parser.error('Set JTAG_LIB or supply --jtag-library')
    if args.repeats < 1 or args.clock_hz <= 0:
        parser.error('--repeats and --clock-hz must be positive')
    files = sorted(args.maps_dir.glob('*_P.npy'))
    if args.max_images is not None:
        if args.max_images < 1:
            parser.error('--max-images must be positive')
        files = files[:args.max_images]
    if not files:
        parser.error(f'No *_P.npy files in {args.maps_dir}')
    results = []
    print('Comparing OpenCV CPU vs FPGA: identical 8-bit P/T, 4-connectivity, min_area=3')
    with JtagAtlantic(args.jtag_library, args.cable, args.device, args.instance, args.timeout) as port:
        for p_path in files:
            name = p_path.name[:-6]
            try:
                t_path = p_path.with_name(name + '_T.npy')
                result = compare_case(port, np.load(p_path), np.load(t_path),
                                      args.repeats, args.clock_hz)
                result['name'] = name
                metadata_path = p_path.with_name(name + '_meta.json')
                metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
                origin = metadata.get('crop_origin', [0, 0])
                result['metadata'] = metadata
                result['cpu_heads'] = head_locations(result['expected_records'], origin)
                result['fpga_heads'] = head_locations(result['actual_records'], origin)
                status = 'ok' if result['ok'] else 'FAIL'
                print(f"[{status}] {name}: fpga={result['fpga_points']} pts "
                      f"(round-trip {result['fpga_roundtrip_seconds']:.3f}s) vs "
                      f"opencv={result['cpu_points']} pts "
                      f"(median {result['cpu_median_seconds'] * 1e6:.1f} us)")
                print(f"       core={result['rtl_active_cycles']} cycles; "
                      f"estimated {result['estimated_core_seconds'] * 1e6:.2f} us "
                      f"at {args.clock_hz / 1e6:g} MHz (requires timing closure)")
                for label, heads in [('CPU', result['cpu_heads']), ('FPGA', result['fpga_heads'])]:
                    print(f"       {label} head locations (x,y), crop pixels: " +
                          str([(round(h['x'], 4), round(h['y'], 4)) for h in heads]))
                    if metadata:
                        print(f"       {label} locations in source image: " +
                              str([(round(h['image_x'], 4), round(h['image_y'], 4)) for h in heads]))
                if not result['ok']:
                    print(f"       CPU  (area,sum_x,sum_y)[:5]={result['expected_records'][:5]}")
                    print(f"       FPGA (area,sum_x,sum_y)[:5]={result['actual_records'][:5]}")
                results.append(result)
            except (OSError, ValueError, RuntimeError) as exc:
                print(f'[FAIL] {name}: {exc}')
                results.append(dict(name=name, ok=False, error=str(exc)))
                print('Stopping after error; reset KEY[0] before retrying.')
                break
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + '\n')
    passed = sum(r['ok'] for r in results)
    print(f'{passed}/{len(results)} passed; report: {args.output}')
    sys.exit(0 if len(results) == len(files) and passed == len(results) else 1)


if __name__ == '__main__':
    main()
