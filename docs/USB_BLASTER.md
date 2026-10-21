# USB-Blaster-only programming and validation (DE2-115)

This project uses Intel JTAG UART over the board's existing USB-Blaster cable.
No RS-232 cable, serial adapter, Nios processor, or firmware is required.
The original RS-232 project remains available as `de2_115_uart.qpf`.

The new path is:

PC Python → JTAG Atlantic → USB-Blaster → generated Intel JTAG UART IP →
Avalon polling adapter → shared packet engine → margin-gated CCL.

## 1. Generate the Intel IP once

Use Quartus with Cyclone IV E support (the projects target Quartus 18.1).
Open a Quartus/Nios command shell with `qsys-script`, `qsys-generate`, and
`quartus_sh` available. On Linux these are typically in Quartus's `sopc_builder/bin`
and `bin` directories. From this repository:

```bash
cd quartus
qsys-script --script=create_jtag_uart.tcl
qsys-generate jtag_uart_system.qsys --synthesis=VERILOG
```

Confirm `jtag_uart_system/synthesis/jtag_uart_system.qip` exists.
The generation Tcl selects the JTAG UART component installed with your Quartus.
If your version rejects a component/interface name, inspect the JTAG UART
component in Platform Designer rather than substituting a UART peripheral.

GUI alternative: create `jtag_uart_system.qsys` in `quartus/` using Platform
Designer, add one Intel **JTAG UART** instance named `uart`, and export:

| Component interface | Export name |
|---|---|
| clk | clk |
| reset | reset |
| avalon_jtag_slave | uart |
| irq | irq |

Select Cyclone IV E / EP4CE115F29C7, save, and Generate HDL for synthesis
(Verilog). No CPU or Avalon interconnect is needed: RTL drives the exported
slave directly. Confirm the generated module ports match `rtl/de2_115_jtag_top.sv`.

## 2. Compile the new project

The JTAG board wrapper explicitly selects MAX_WIDTH=32, MAX_HEIGHT=32,
MAX_LABELS=64. Stop any previous compilation before compiling this change.
Use the deterministic test in step 5 before image crops. This smaller build
reduces synthesis complexity but does not guarantee timing closure or a specific
compile duration. The CCL and RS-232 defaults remain unchanged.


Open `quartus/de2_115_jtag.qpf` in Quartus and Start Compilation, or while
still in `quartus/`:

```bash
quartus_sh --flow compile de2_115_jtag
```

Top-level entity: `de2_115_jtag_top`. Device: EP4CE115F29C7. Check the Fitter
and Timing Analyzer reports; the 50 MHz clock must meet its 20 ns requirement.
Resolve critical timing, clock, or pin warnings. The configuration file is
`quartus/output_files/de2_115_jtag.sof` (relative to the repository).

## 3. Program the board

Power on the DE2-115, connect the USB-Blaster port, set SW19 to RUN.
Tools → Programmer → Hardware Setup → USB-Blaster. Mode: JTAG.
Auto Detect the Cyclone IV device, select `output_files/de2_115_jtag.sof`,
tick Program/Configure, and Start. Wait for 100% success.
Press and release KEY[0] to reset. This build does not drive status LEDs.
Reprogram after a power cycle; SOF programming is volatile.

## 4. Prepare the host

Return to the repository root and activate your Python environment.

```bash
python -m pip install -r requirements.txt
python scripts/uart_host.py --help
```

JTAG mode does not need pyserial. It needs Quartus's native JTAG Atlantic
library matching your Python architecture (usually 64-bit). Find it under
your installation:

```bash
find /path/to/intelFPGA -iname '*jtag_atlantic*'
```

Linux: typically `quartus/linux64/libjtag_atlantic.so`.
Windows: locate `jtag_atlantic.dll` in your Quartus installation, use matching
Python architecture, and expose its dependent DLL directory to the loader.
On Linux, if a dependent shared library cannot load, add its Quartus directory
to `LD_LIBRARY_PATH` before starting Python. Example:

```bash
export LD_LIBRARY_PATH=/path/to/quartus/linux64:${LD_LIBRARY_PATH:-}
```

Use `jtagconfig` to list cable/device information. Keep `jtagd` available via
the Quartus environment. Close `nios2-terminal` and other clients of this
JTAG UART. This host transfers binary packets, so do not use a text terminal
or its output as a map transport.

## 5. Create a small deterministic test

From the repository root:

```bash
python - <<'PY'
from pathlib import Path
import numpy as np
out = Path('data/board_test')
out.mkdir(parents=True, exist_ok=True)
p = np.full((4, 8), 0.05, dtype=np.float32)
t = np.full((4, 8), 0.4, dtype=np.float32)
p[0:2, 0:2] = 0.9
p[0:2, 5:7] = 0.9
np.save(out / 'test_P.npy', p)
np.save(out / 'test_T.npy', t)
PY
```

Press/release KEY[0], then run (substitute your library path):

```bash
python scripts/uart_host.py --transport jtag \
  --jtag-library /path/to/quartus/linux64/libjtag_atlantic.so \
  --p-map data/board_test/test_P.npy \
  --t-map data/board_test/test_T.npy \
  --output data/board_test/test_result.json
```

Expected: two area-4 components centered at (0.5,0.5) and (5.5,0.5).
A successful run prints received components and active cycles and writes JSON.
The host checks component areas and coordinate sums against the CPU reference
on identical 8-bit maps before saving. A mismatch raises an exception.
If auto-selection fails, add `--cable 'USB-Blaster [USB-0]'` using the name from
`jtagconfig`. `--device 1` is the 1-based chain device; `--instance 0` is the
0-based JTAG UART instance. Adjust to your detected hardware.

## 6. Validate real map pairs

Use the same host command with saved P/T maps. Maximum dimensions are
32 wide × 32 high; label capacity is 64 for this bring-up build. Check map sizes first and crop
for bring-up if necessary. Cropped results validate the crop, not the full
image. Synthetic-map correctness does not establish trained-model accuracy.

Create a matching crop pair first:

```bash
python - <<'PYTHON'
from pathlib import Path
import numpy as np
out = Path('data/board_test')
out.mkdir(parents=True, exist_ok=True)
for kind in ('P', 'T'):
    values = np.load(f'data/maps/0002_{kind}.npy')
    np.save(out / f'0002_crop_{kind}.npy', values[:32, :32])
PYTHON
python scripts/uart_host.py --transport jtag \
  --jtag-library /path/to/quartus/linux64/libjtag_atlantic.so \
  --p-map data/board_test/0002_crop_P.npy \
  --t-map data/board_test/0002_crop_T.npy \
  --output data/board_test/0002_jtag.json
```

Repeat for additional maps within the limits. Reset after a timeout/error to
abandon any partially transmitted frame. Record tool version, input size,
resource use, timing, CPU comparison, and `rtl_active_cycles`. At a verified
50 MHz, active seconds = cycles / 50,000,000. JTAG transfer and host latency
are separate; this is a functional validation link, not a throughput benchmark.

## Local simulation

```bash
iverilog -g2012 -s tb_jtag_uart_transport -o /tmp/jtag.vvp \
  rtl/margin_gated_ccl.sv rtl/dense2sparse_protocol.sv \
  rtl/jtag_uart_transport.sv sim/tb_jtag_uart_transport.sv
vvp /tmp/jtag.vvp
python -m unittest discover -s scripts -p 'test_*.py'
```

The test models the Avalon register interface with FIFO availability and bus
wait states. It checks multi-frame handling, exact component records, row
acknowledgments, and invalid dimensions. It does not simulate Intel's physical
JTAG IP or prove Quartus synthesis, timing closure, or USB-Blaster operation.
Those checks require your generated IP, Quartus installation, and board.

Register behavior reference: Intel Embedded Peripherals IP User Guide,
JTAG UART data (RVALID) and control (WSPACE) registers:
https://www.intel.com/programmable/technical-pdfs/683130.pdf

## Error 12006: undefined entity jtag_uart_system

If the report also says `Warning (125092): ... .qip not found`, Intel IP
synthesis output has not been generated at the expected location. Running
`create_jtag_uart.tcl` creates the system description; it does not generate
Verilog. Run BOTH `qsys-script` and `qsys-generate` from step 1, check that
`jtag_uart_system/synthesis/jtag_uart_system.qip` exists, then recompile.
Run the Tcl through **qsys-script**, not the Quartus Tcl Console, which does
not provide the same Platform Designer API environment. If the commands are
not on PATH, use their full paths under your Quartus `sopc_builder/bin/`.
Do not add a black-box stub to suppress this error: the actual IP is required.

The board project must retain `DEVICE EP4CE115F29C7` and pin assignments
CLOCK_50=PIN_Y2, KEY[0]=PIN_M23. If editing QSF externally, close the project
first and reopen afterward so the GUI does not overwrite the saved changes.

## Linux undefined AJI symbol

The host preloads libjtag_client.so then libaji_client.so from the same directory
as libjtag_atlantic.so with global symbol visibility. Use libraries from the
same Quartus release. Test loading with scripts.jtag_atlantic.load_library;
a standalone ctypes.CDLL call does not perform this dependency preload.

## Compare OpenCV CPU baseline against FPGA

From the repository root, with JTAG_LIB set and after KEY[0] reset:

```bash
python reference_algorithm/validate_fpga.py \
  --maps-dir data/board_test --jtag-library "$JTAG_LIB" \
  --cable "USB-Blaster [1-2]" --output exp/fpga_validation.json
```

This reads matching *_P.npy / *_T.npy pairs (up to 32x32). It prints [ok]/[FAIL]
lines similar to validate.py but compares OpenCV CPU decoding against the board,
using identical 8-bit inputs, 4-connectivity and min_area=3. It compares exact
component areas and coordinate sums, not merely counts. Complete frame
mismatches are saved and remaining frames are checked; protocol errors stop
the run and require a board reset. Exit code is nonzero if any case fails.

The report includes warmed median CPU decoder timing (quantization, binarization,
OpenCV CCL), FPGA round-trip time (including host quantization/communication),
and cycle-based core time at an explicitly assumed 50 MHz. Cycle time requires
verified FPGA timing closure. CPU timing excludes conversion of labels into
exact coordinate-sum records used for validation. It is a small-crop diagnostic,
not an end-to-end neural-network benchmark or evidence of acceleration when
correctness fails. This baseline uses matching 4-connectivity, not necessarily
all original upstream IIM settings.

## Validate more photos and print head coordinates

Prepare 20 distinct photos using JHU annotations (synthetic maps, not trained
model output). Reuse an output directory only if you intend to keep its older
map pairs as part of the validation set:

```bash
python scripts/prepare_fpga_samples.py \
  --images ../jhu_crowd_v2.0/val/images \
  --annotations ../jhu_crowd_v2.0/val/gt \
  --out-dir data/fpga_samples_20 --limit 20
python reference_algorithm/validate_fpga.py \
  --maps-dir data/fpga_samples_20 --jtag-library "$JTAG_LIB" \
  --cable "USB-Blaster [1-2]" --output exp/fpga_samples_20.json
```

The validator processes every map pair in the directory unless --max-images
is specified. It prints both CPU and FPGA head coordinates in crop pixels;
with the generated metadata it also prints source-image coordinates, obtained
by adding the crop origin. JSON preserves unrounded coordinates and areas.
Coordinates are zero-based (x rightwards, y downwards). Each crop is decoded
independently: it is not full-image inference, and boundary components can be
cut. The baseline and hardware are distinct implementations intended to give
identical outputs using 8-bit maps, connectivity=4, min_area=3.
Known board mismatches and failing timing must be resolved before claiming
correct FPGA behavior or performance acceleration.

## Cover one entire photo with independent tiles

Prepare tiles from an existing full-size P/T pair in raster order. Optional
--image saves preview crops and verifies that photo and map dimensions match:

```bash
python scripts/prepare_fpga_tiles.py \
  --p-map data/maps/0002_P.npy --t-map data/maps/0002_T.npy \
  --image data/samples/0002.jpg --out-dir data/0002_all_tiles
python reference_algorithm/validate_fpga.py \
  --maps-dir data/0002_all_tiles --jtag-library "$JTAG_LIB" \
  --cable "USB-Blaster [1-2]" --output exp/0002_all_tiles.json
```

Every pixel is covered exactly once, left-to-right within each row and then
 top-to-bottom. Right/bottom tiles may be smaller than 32x32. The output
folder must be empty to prevent stale files from entering the run. The manifest
and per-tile metadata retain source coordinates. No source map is regenerated.
This validates CPU/FPGA agreement tile by tile, not equivalence to a single
full-frame decode: heads crossing boundaries can split, disappear under the
area filter, or be counted more than once. No stitching is implemented. Do
not sum tile counts as a full-photo crowd count. Large photos may take many
minutes over JTAG; timing violations in the programmed design remain unresolved.
