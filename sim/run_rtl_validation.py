#!/usr/bin/env python3
"""Differentially test the streaming RTL against the NumPy reference.

Requires Icarus Verilog (`iverilog` and `vvp`). Example:
    python sim/run_rtl_validation.py --maps-dir data/maps
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from reference_algorithm.margin_gated_ccl import streaming_ccl


WIDTH = 32
HEIGHT = 32
MIN_AREA = 3


def build_cases(maps_dir: Optional[Path]) -> list[tuple[str, np.ndarray, np.ndarray]]:
    rng = np.random.default_rng(24)
    cases: list[tuple[str, np.ndarray, np.ndarray]] = []

    cases.append(
        ("all_background", np.full((HEIGHT, WIDTH), 0.1), np.full((HEIGHT, WIDTH), 0.5))
    )
    cases.append(
        ("all_foreground", np.full((HEIGHT, WIDTH), 0.9), np.full((HEIGHT, WIDTH), 0.5))
    )

    checker = (np.indices((HEIGHT, WIDTH)).sum(axis=0) % 2).astype(bool)
    cases.append(
        ("checkerboard", np.where(checker, 0.9, 0.1), np.full((HEIGHT, WIDTH), 0.5))
    )

    random_p = rng.random((HEIGHT, WIDTH))
    random_t = rng.uniform(0.2, 0.7, size=(HEIGHT, WIDTH))
    cases.append(("random_maps", random_p, random_t))

    if maps_dir is not None:
        p_files = sorted(maps_dir.glob("*_P.npy"))
        if not p_files:
            raise FileNotFoundError(f"no *_P.npy maps found in {maps_dir}")
        for p_path in p_files:
            t_path = p_path.with_name(p_path.name[:-6] + "_T.npy")
            if not t_path.is_file():
                raise FileNotFoundError(f"missing threshold map {t_path}")
            p_map = np.squeeze(np.load(p_path))
            t_map = np.squeeze(np.load(t_path))
            if p_map.ndim != 2 or t_map.shape != p_map.shape:
                raise ValueError(f"invalid map shape in {p_path.name}")
            if p_map.shape[0] < HEIGHT or p_map.shape[1] < WIDTH:
                raise ValueError(f"{p_path.name} is smaller than {WIDTH}x{HEIGHT}")
            full_mask = p_map >= t_map
            integral = np.pad(full_mask.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
            counts = (
                integral[HEIGHT:, WIDTH:]
                - integral[:-HEIGHT, WIDTH:]
                - integral[HEIGHT:, :-WIDTH]
                + integral[:-HEIGHT, :-WIDTH]
            )
            y, x = np.unravel_index(np.argmax(counts), counts.shape)
            cases.append((p_path.name[:-6], p_map[y:y + HEIGHT, x:x + WIDTH],
                          t_map[y:y + HEIGHT, x:x + WIDTH]))
    return cases


def expected_components(P: np.ndarray, T: np.ndarray) -> list[tuple[int, int, int]]:
    p8 = np.rint(P * 255).astype(np.uint8)
    t8 = np.rint(T * 255).astype(np.uint8)
    binary = p8 >= t8
    components = streaming_ccl(binary.astype(np.uint8), min_area=MIN_AREA)
    return sorted(
        (component.area, round(component.x * component.area), round(component.y * component.area))
        for component in components
    )


def run_case(
    name: str,
    P: np.ndarray,
    T: np.ndarray,
    iverilog: str,
    vvp: str,
    testbench: Path,
) -> int:
    if P.shape != (HEIGHT, WIDTH) or T.shape != P.shape:
        raise ValueError(f"{name}: expected {HEIGHT}x{WIDTH} matching maps")
    if not np.all(np.isfinite(P)) or not np.all(np.isfinite(T)):
        raise ValueError(f"{name}: maps contain non-finite values")
    if np.any((P < 0) | (P > 1)) or np.any((T < 0) | (T > 1)):
        raise ValueError(f"{name}: P and T must be in [0, 1]")

    p8 = np.rint(P * 255).astype(np.uint8)
    t8 = np.rint(T * 255).astype(np.uint8)
    expected = expected_components(P, T)
    with tempfile.TemporaryDirectory(prefix="rtl-ccl-") as temp_dir:
        temp = Path(temp_dir)
        source = temp / "pixels.hex"
        results = temp / "components.csv"
        image = np.column_stack((p8.ravel(), t8.ravel()))
        source.write_text("".join(f"{int(p):02x}{int(t):02x}\n" for p, t in image))

        executable = temp / "rtl_test.vvp"
        rtl = ROOT / "rtl" / "margin_gated_ccl.sv"
        compilation = subprocess.run(
            [iverilog, "-g2012", "-s", "tb_margin_gated_ccl_vectors",
             "-o", str(executable), str(rtl), str(testbench)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if compilation.returncode:
            raise RuntimeError(f"{name}: RTL compilation failed\n{compilation.stderr}")
        simulation = subprocess.run(
            [vvp, str(executable), f"+input={source}", f"+results={results}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if simulation.returncode:
            raise RuntimeError(f"{name}: RTL simulation failed\n"
                               f"{simulation.stdout}\n{simulation.stderr}")
        match = re.search(r"PASS pixels=\d+ cycles=(\d+)", simulation.stdout)
        if not match:
            raise RuntimeError(f"{name}: simulator did not report successful completion\n"
                               f"{simulation.stdout}\n{simulation.stderr}")
        cycles = int(match.group(1))
        actual = []
        if results.exists():
            actual = sorted(
                tuple(map(int, line.split(",")))
                for line in results.read_text().splitlines()
                if line.strip()
            )
        if actual != expected:
            raise AssertionError(
                f"{name}: RTL components differ\nexpected={expected}\nactual={actual}"
            )
        print(f"[ok] {name}: {len(actual)} components, {cycles} RTL cycles")
        return cycles


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps-dir", type=Path, default=ROOT / "data" / "maps")
    parser.add_argument("--no-saved-maps", action="store_true",
                        help="run only the generated edge-case and random vectors")
    parser.add_argument("--iverilog", default=shutil.which("iverilog"))
    parser.add_argument("--vvp", default=shutil.which("vvp"))
    args = parser.parse_args()
    if not args.iverilog or not args.vvp:
        parser.error("Icarus Verilog was not found; supply --iverilog and --vvp paths")

    maps_dir = None if args.no_saved_maps else args.maps_dir
    testbench = ROOT / "sim" / "tb_margin_gated_ccl_vectors.sv"
    cycle_counts = [
        run_case(name, P, T, args.iverilog, args.vvp, testbench)
        for name, P, T in build_cases(maps_dir)
    ]
    print(f"Validated {len(cycle_counts)} maps; "
          f"median simulated cycles/image={int(np.median(cycle_counts))}")


if __name__ == "__main__":
    main()
