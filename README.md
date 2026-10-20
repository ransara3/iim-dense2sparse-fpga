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
- [x] Step 2: Pure-Python/NumPy reference implementation of Algorithm 1
      (margin-gated binarization + single-pass streaming connected-component
      labeling) validated against OpenCV's result.
- [x] Step 3: Quantization sweep of `P`/`T` (topology-aware precision analysis):
      pixel F1 drift, component merge/split counts, verifying `B ⊆ B_q`.
- [x] Step 4: Parameterized SystemVerilog RTL for the margin-gated decoder +
      streaming 4-connected CCL, with Icarus Verilog differential simulation.
- [ ] Step 5: Real-FPGA evaluation vs. CPU/GPU baseline.

## Repository layout

```
iim-dense2sparse-fpga/
├── scripts/              # tooling that talks to the IIM model (inference, map dumping)
├── reference_algorithm/  # pure Python/NumPy reference of Algorithm 1 (margin-gated CCL)
├── rtl/                  # parameterized SystemVerilog streaming core
├── sim/                  # RTL testbenches and differential validation
├── quartus/              # DE2-115 Quartus project, pin assignments, timing constraints
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

## Reference algorithm (Step 2)

`reference_algorithm/` is a pure-Python/NumPy implementation of Algorithm 1
("Margin-Gated Dense-to-Sparse Localization") from the FPGA paper:

- `margin_gated_binarize(P, T)`: vectorized margin-gated binarization. Provably
  identical to naive `B = 1[P >= T]` for any `T` bounded in `(0.2, 0.7)`.
- `streaming_ccl(B, min_area=1)`: single-pass, row-buffer 4-connected labeling
  with union-find label equivalence (`union_find.py`) and early component
  closing — a label's centroid is emitted and its accumulator memory released
  as soon as it provably cannot be extended by any future row, matching the
  paper's bounded-memory streaming datapath rather than just a generic
  two-pass CCL.

Validate both properties (math equivalence + exact agreement with OpenCV's
`connectedComponentsWithStats`) on the dumped/synthesized maps:

```bash
python reference_algorithm/validate.py --maps-dir data/maps
```

### Quantization sweep (Step 3)

Sweep shared unsigned round-to-nearest quantization of `P` and `T` over the
selected bit widths. The CSV reports pixel-mask F1 against full-precision
`B = 1[P >= T]`, added foreground pixels, and 4-connected component merge/split
counts. The shared monotone quantizer must preserve `B ⊆ B_q`; violations or
maps inconsistent with their saved `_B.npy` are treated as errors.

```bash
python reference_algorithm/quantization_sweep.py \
  --maps-dir data/maps \
  --bits 4,6,8,10,12,16 \
  --output exp/quantization_sweep.csv
```

Omit `--output` to write CSV to stdout. Pixel F1 is a binary-map agreement
metric, not point-localization F1 against annotated head coordinates.

### DE2-115 streaming RTL (Step 4)

The DE2-115 uses a Cyclone IV E device, which Intel's HLS flow does not target.
The decoder and connected-component labeler are therefore implemented as
portable synthesizable SystemVerilog in `rtl/margin_gated_ccl.sv`. The core
accepts one raster-ordered `(P,T)` pair per accepted input cycle and emits
components through a back-pressured output stream. Inputs are unsigned 8-bit
uniform quantization codes (`round(value * 255)`); thresholds must come from
IIM's `(0.2, 0.7)` range. Components are emitted as `(area, sum_x, sum_y)` so
the integration layer can compute centroids, and components smaller than
`MIN_AREA` are discarded. The default label capacity is 2048; `overflow` flags
an undersized configuration instead of silently returning incomplete results.

Run the differential simulation against the NumPy reference, including
synthetic edge cases and the highest-foreground 32x32 crop from each saved map:

```bash
iverilog -g2012 -s tb_margin_gated_ccl \
  -o /tmp/tb_margin_gated_ccl.vvp \
  rtl/margin_gated_ccl.sv sim/tb_margin_gated_ccl.sv
vvp /tmp/tb_margin_gated_ccl.vvp

python sim/run_rtl_validation.py --maps-dir data/maps
```

The UART/top-level protocol test can be run independently:

```bash
iverilog -g2012 -s tb_de2_115_uart_top \
  -o /tmp/tb_de2_115_uart_top.vvp \
  rtl/uart_8n1.sv rtl/margin_gated_ccl.sv rtl/de2_115_uart_top.sv \
  sim/tb_de2_115_uart_top.sv
vvp /tmp/tb_de2_115_uart_top.vvp
```

The Python validator requires Icarus Verilog (`iverilog` and `vvp`) and compares
the emitted areas and coordinate sums exactly with `streaming_ccl`. Simulated
cycle counts are functional/scheduling data, not FPGA timing or throughput
measurements.

### DE2-115 UART bring-up and hardware evaluation (Step 5)

`rtl/de2_115_board_top.sv` and `quartus/de2_115_uart.qsf` provide a DE2-115
wrapper for `CLOCK_50`, `KEY[0]`, and the board's RS-232 transceiver pins. The
assignments follow the [Terasic DE2-115 user manual](https://www.terasic.com.tw/wiki/File:DE2_115_User_manual_2013.pdf).
The Quartus project targets EP4CE115F29C7N at 50 MHz; it still needs to be
compiled with a Quartus release that supports Cyclone IV E.

The UART protocol uses 115200 baud, 8-N-1:

- Host sends `4D 47`, then width and height as little-endian 16-bit values.
- FPGA replies `AC` when the core is ready (`E0` indicates an error).
- Host sends each row in raster order as interleaved 8-bit `P,T` bytes.
- After each non-final row, FPGA emits zero or more component records
  (`C1`, then 32-bit little-endian `area`, `sum_x`, and `sum_y`) followed by
  `A6`. The host must wait for this row acknowledgment before sending more
  pixels.
- After the last row and its component records, FPGA emits `CF` followed by
  the little-endian 32-bit component count and 32-bit active-core-cycle count.
  The cycle counter includes accepted pixels and internal scan/emit cycles,
  but excludes UART input gaps and time stalled waiting for a component record
  to finish transmitting.

The row acknowledgment intentionally provides backpressure so the UART does
not overrun while the CCL closes and emits components. Use
`scripts/uart_host.py` to transfer saved maps and write centroid JSON:

```bash
pip install -r requirements-hardware.txt
python scripts/uart_host.py \
  --port /dev/ttyUSB0 \
  --p-map data/maps/0002_P.npy \
  --t-map data/maps/0002_T.npy \
  --output data/maps/0002_uart_points.json
```

Compile the board project with a Cyclone-IV-capable Quartus installation using
`quartus_sh --flow compile quartus/de2_115_uart`.

The UART is a functional bring-up path, not a throughput benchmark: serial
transfer dominates processing time. The host utility also runs the NumPy CPU
reference on the same quantized inputs and fails if its component areas and
coordinate sums differ from the FPGA. Use the Quartus timing report together
with `rtl_active_cycles` to estimate core latency; the UART transfer duration
is intentionally excluded from that cycle count.

Step 5 is **not yet complete**. This environment has no Quartus installation
or attached DE2-115, so Cyclone IV synthesis, place-and-route, clock frequency,
resource use, power, and board throughput have not been measured. The wrapper
and host utility make a board run reproducible, but simulation does not
substitute for physical FPGA results. Record tool versions, resource/timing
reports, clock, image dimensions, pixel count, and end-to-end latency against
the CPU baseline on identical quantized inputs before marking Step 5 complete.

## License / attribution

Code here is original work (MIT, see `LICENSE`). It depends on and references
IIM (`https://github.com/taohan10200/IIM`, MIT licensed, Copyright (c) 2020 tao han).
