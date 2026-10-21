# Algorithm comparison presentation

Ten slides in progress.tex. Slide 2 contains the supplied CPU-only results.
The crop slide displays assets/long_compilation.png when available, otherwise a placeholder.
Optional video: assets/demo.mp4. Upload to Overleaf and compile using pdfLaTeX.

Local compilation: run pdflatex progress.tex twice from this folder.
A LaTeX compiler is unavailable in the editing environment; review PDF layout.

The final slide highlights nearly constant active cycles and the provisional
lower FPGA estimate in sample 0136. It does not claim proven acceleration or
a demonstrated relationship between head count and speedup: the results do
not support that claim and the FPGA still fails timing closure.

Two added slides summarize full-photo coverage and timing from exp/0002_all_tiles.json. They distinguish independent tile coverage from stitched full-image inference and highlight the 5/56 nonempty exact matches.

Board slide: save your board photograph as assets/fpga_board.jpg. It contains only the board title and picture (a placeholder appears until the photo is added).
