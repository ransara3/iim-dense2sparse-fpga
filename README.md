# Margin-Gated, Quantization-Aware Dense-to-Sparse Engine for Crowd Localization

Research project building a hardware-friendly (FPGA-targeted) dense-to-sparse
decoding engine for the localization head of
[IIM (Independent Instance Maps)](https://github.com/taohan10200/IIM) —
*"Learning Independent Instance Maps for Crowd Localization"* (Gao et al., 2020).

This repo does **not** reimplement or retrain IIM's backbone. It targets only the
last stage of the pipeline: turning a dense confidence map `P(x,y)` and a learned
per-pixel threshold map `T(x,y)` into sparse head coordinates, as described in
`Margin-Gated, Quantization-Aware FPGA Engine for Dense-to-Sparse Crowd Localization`.

## Background

IIM's `BinarizedModule` (see `model/PBM.py` in the IIM repo) predicts a threshold
`T(x,y)` compressed into the fixed range `(0.2, 0.7)` via `compressedSigmoid`, then
binarizes `B(x,y) = 1[P(x,y) >= T(x,y)]`, and finally runs
`cv2.connectedComponentsWithStats` to get head centroids.

The margin-gated idea: pixels with `P < 0.2` or `P >= 0.7` can be classified
instantly without touching `T` at all; only the ambiguous band
`0.2 <= P < 0.7` needs the full adaptive-threshold compare. This repo implements
and evaluates that idea end to end, working toward an FPGA datapath.

## Project status / roadmap

- [x] Step 1: Generate `P(x,y)` / `T(x,y)` / `B(x,y)` dense maps, either from a working
      IIM model (`scripts/dump_maps.py`) or, since upstream's pretrained checkpoints are
      currently undownloadable (dead OneDrive/SharePoint links, see
      [taohan10200/IIM#41](https://github.com/taohan10200/IIM/issues/41)), from a
      statistically realistic synthetic generator driven by real JHU-CROWD++ ground
      truth (`scripts/synth_maps_from_gt.py`).
- [ ] Step 2: Pure-Python/NumPy reference implementation of Algorithm 1
      (margin-gated binarization + single-pass streaming connected-component
      labeling) validated against OpenCV's result.
- [ ] Step 3: Quantization sweep of `P`/`T` (topology-aware precision analysis):
      F1 drift, component merge/split counts, verifying `B ⊆ B_q`.
- [ ] Step 4: HLS/RTL implementation of the margin-gated decoder + streaming CCL.
- [ ] Step 5: Real-FPGA evaluation vs. CPU/GPU baseline.

## Repository layout

```
iim-dense2sparse-fpga/
├── scripts/              # tooling that talks to the IIM model (inference, map dumping)
├── reference_algorithm/  # pure Python/NumPy reference of Algorithm 1 (margin-gated CCL)
├── data/
│   ├── checkpoints/      # pretrained IIM weights (not committed, see below)
│   ├── samples/          # a few test images (not committed, see below)
│   └── maps/             # dumped P/T/B maps + visualizations (generated, not committed)
└── docs/                 # notes, write-ups, experiment logs
```

## Dependency: the IIM repository

This project needs a working clone of IIM next to it (as a sibling folder, not
vendored in this repo, since it's a separate upstream project with its own
license/history):

```
<parent>/
├── IIM/                       # https://github.com/taohan10200/IIM (MIT licensed)
└── iim-dense2sparse-fpga/     # this repo
```

Note: a stock IIM checkout hardcodes `.cuda()` inside `BinarizedF.forward`
(`model/PBM.py`), which crashes on CPU-only machines even for inference. If you
don't have a CUDA GPU, apply this one-line-per-call fix in your IIM clone:

```python
# model/PBM.py, BinarizedF.forward
a = torch.ones_like(input)   # was: torch.ones_like(input).cuda()
b = torch.zeros_like(input)  # was: torch.zeros_like(input).cuda()
```

## Getting a pretrained checkpoint

IIM's pretrained weights are hosted on personal OneDrive/SharePoint links in its
README (not scriptable/downloadable headlessly). Manually download one checkpoint
(e.g. the smallest, SHHB or FDST) and place it at:

```
data/checkpoints/<name>.pth
```

## Usage

```bash
python scripts/dump_maps.py \
  --iim-root ../IIM \
  --net HR_Net \
  --checkpoint data/checkpoints/<name>.pth \
  --dataset SHHB \
  --images data/samples \
  --out-dir data/maps
```

Without `--checkpoint`, the script runs in **smoke-test mode** with randomly
initialized weights — useful to validate the pipeline's shapes/dataflow, but the
resulting maps/points are not meaningful for localization accuracy.

### Alternative: synthetic maps from ground truth (no checkpoint needed)

Upstream IIM's pretrained-weight links (OneDrive/SharePoint) are currently dead for
everyone (see [taohan10200/IIM#41](https://github.com/taohan10200/IIM/issues/41)), so
as a stand-in, `scripts/synth_maps_from_gt.py` builds realistic `P`/`T`/`B` maps
directly from a crowd-counting dataset's point annotations (e.g. JHU-CROWD++),
using the exact same `compressedSigmoid` and `B = 1[P>=T]` math as IIM's `PBM.py`,
so Step 2/3 work isn't blocked on a working checkpoint:

```bash
# data/samples/<name>.jpg + data/samples/<name>.txt (JHU-CROWD++ GT: "x y w h occ blur" per line)
python scripts/synth_maps_from_gt.py --images data/samples --out-dir data/maps
```

## License / attribution

Code here is original work (MIT, see `LICENSE`). It depends on and references
IIM (`https://github.com/taohan10200/IIM`, MIT licensed, Copyright (c) 2020 tao han).
