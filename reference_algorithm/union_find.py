"""Union-find (disjoint-set) with per-component accumulators (N, Sx, Sy).

This backs the streaming connected-component labeling in
`margin_gated_ccl.py`. Keeping it in its own module mirrors how a hardware
design would separate the label-equivalence resolution logic from the
per-pixel streaming datapath (Algorithm 1, lines 2-3, 21-44).
"""


class UnionFind:
    def __init__(self):
        self.parent = {}
        self.N = {}
        self.Sx = {}
        self.Sy = {}
        self._next_label = 1

    def make_label(self) -> int:
        label = self._next_label
        self._next_label += 1
        self.parent[label] = label
        self.N[label] = 0
        self.Sx[label] = 0
        self.Sy[label] = 0
        return label

    def find(self, label: int) -> int:
        root = label
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[label] != root:
            self.parent[label], label = root, self.parent[label]
        return root

    def union(self, label_a: int, label_b: int) -> int:
        root_a, root_b = self.find(label_a), self.find(label_b)
        if root_a == root_b:
            return root_a
        # merge root_b's accumulator into root_a and drop root_b's entries
        self.parent[root_b] = root_a
        self.N[root_a] += self.N[root_b]
        self.Sx[root_a] += self.Sx[root_b]
        self.Sy[root_a] += self.Sy[root_b]
        del self.N[root_b], self.Sx[root_b], self.Sy[root_b]
        return root_a

    def add_pixel(self, label: int, x: int, y: int) -> int:
        root = self.find(label)
        self.N[root] += 1
        self.Sx[root] += x
        self.Sy[root] += y
        return root
