"""Pure-Python/NumPy reference implementation of Algorithm 1 (Margin-Gated
Dense-to-Sparse Localization) from
`Margin-Gated, Quantization-Aware FPGA Engine for Dense-to-Sparse Crowd
Localization`.

Two pieces, matching the paper's two datapath stages:

1. `margin_gated_binarize`: vectorized margin-gated binarization. Exploits
   IIM's `compressedSigmoid`-bounded threshold (0.2 < T(x,y) < 0.7, see
   IIM/model/PBM.py) so pixels outside [0.2, 0.7) never need to read T at
   all. Mathematically identical to the naive `B = 1[P >= T]` for any T
   bounded in (0.2, 0.7) -- see `reference_algorithm/test_margin_gated_ccl.py`
   for the proof-by-random-testing of that equivalence.

2. `streaming_ccl`: single-pass, row-buffer-based 4-connected labeling with
   union-find label equivalence and early component closing, implementing
   Algorithm 1 lines 1-65 directly (not just "a CCL that gives the same
   answer"): a label is closed out (centroid emitted, memory released) as
   soon as it provably cannot be extended by any future row, i.e. once it
   no longer appears in the row just completed.
"""
from dataclasses import dataclass

import numpy as np

from .union_find import UnionFind

BACKGROUND = 0


def margin_gated_binarize(P: np.ndarray, T: np.ndarray, lo: float = 0.2, hi: float = 0.7) -> np.ndarray:
    """Vectorized form of Algorithm 1 lines 7-17."""
    B = np.where(P >= T, 1, 0)
    B = np.where(P < lo, 0, B)
    B = np.where(P >= hi, 1, B)
    return B.astype(np.uint8)


@dataclass
class Component:
    x: float
    y: float
    area: int


def streaming_ccl(B: np.ndarray, min_area: int = 1) -> list[Component]:
    """Single-pass streaming 4-connected labeling, faithful to Algorithm 1
    lines 1-65 (row-buffer label equivalence + early closing on each row)."""
    H, W = B.shape
    uf = UnionFind()
    prev_row_labels = np.zeros(W, dtype=np.int64)
    emitted_roots: set[int] = set()
    results: list[Component] = []

    def close_components(candidate_roots: set[int]):
        for root in candidate_roots - emitted_roots:
            n = uf.N[root]
            if n >= min_area:
                results.append(Component(x=uf.Sx[root] / n, y=uf.Sy[root] / n, area=n))
            emitted_roots.add(root)

    for y in range(H):
        cur_row_labels = np.zeros(W, dtype=np.int64)
        for x in range(W):
            if not B[y, x]:
                continue
            Lleft = cur_row_labels[x - 1] if x > 0 else BACKGROUND
            Lup = prev_row_labels[x] if y > 0 else BACKGROUND
            if Lleft == BACKGROUND and Lup == BACKGROUND:
                L = uf.make_label()
            elif Lleft != BACKGROUND and Lup == BACKGROUND:
                L = uf.find(Lleft)
            elif Lleft == BACKGROUND and Lup != BACKGROUND:
                L = uf.find(Lup)
            else:
                L1, L2 = uf.find(Lleft), uf.find(Lup)
                L = L1 if L1 == L2 else uf.union(L1, L2)
            cur_row_labels[x] = L
            uf.add_pixel(L, x, y)

        # Close out any component that was active before this row but has no
        # presence in the row we just finished -- it cannot grow further.
        prev_roots = {uf.find(int(l)) for l in prev_row_labels if l != BACKGROUND}
        cur_roots = {uf.find(int(l)) for l in cur_row_labels if l != BACKGROUND}
        close_components(prev_roots - cur_roots)

        prev_row_labels = cur_row_labels

    # Flush whatever is still active after the last row.
    remaining_roots = {uf.find(int(l)) for l in prev_row_labels if l != BACKGROUND}
    close_components(remaining_roots)

    return results
