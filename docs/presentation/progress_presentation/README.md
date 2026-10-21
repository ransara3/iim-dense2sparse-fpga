# Progress presentation

`progress.tex` is a complete 18-slide, 16:9 Beamer presentation.

## Compile

From this folder, with a LaTeX distribution containing Beamer:

```bash
pdflatex -interaction=nonstopmode -halt-on-error progress.tex
pdflatex -interaction=nonstopmode -halt-on-error progress.tex
```

Alternatively upload progress.tex and assets/ to Overleaf and select pdfLaTeX.
The source does not require shell escape, external fonts, or a bibliography tool.
A LaTeX compiler was not available in the preparation environment; PDF rendering
and slide overflow have not been checked. Review the rendered slides before presenting.

## Add your evidence

Place files in assets/:

- long_compilation.png: five-hour synthesis screenshot.
- timing_report.png: final negative-slack timing report (not just compilation success).
- validation_demo.png: terminal output or a crop with detected points.
- demo.mp4: your 20-photo demonstration video.

Missing screenshots show labeled placeholders, so you can compile before adding them.
The video is an external run link, not an embedded movie; viewers may block it.
Keep the video ready for separate playback. Set the author/date in progress.tex as needed.

## Evidence boundaries

- Results table: exp/fpga_samples_20.json; 17/20 exact component matches.
- CPU-only full-map counts were rechecked: 29/29, 87/87, 5/5 and matching centroids.
- Five of the 17 passing board crops contain no components.
- 18/20 head counts match; this is not annotation-based detection accuracy.
- Mean CPU median = 52.66 us; mean JTAG round-trip = 1.250 s.
- FPGA active time 83.84–83.92 us assumes 50 MHz; setup slack is -41.265 ns.
- No acceleration, energy saving or full-photo correctness has been established.
- Maps are synthetic from annotations; these are decoder tests, not learned-model accuracy.

See speaker_notes.md for suggested narration.
