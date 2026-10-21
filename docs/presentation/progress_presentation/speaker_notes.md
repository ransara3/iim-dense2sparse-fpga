# Suggested narration (approximately 12–15 minutes)

1. Title: This is an implementation progress report, including the problems that remain.
2. Scope: The neural network provides P and T; our work targets the final map-to-coordinate decoder.
3. Algorithms: Margin gating avoids adaptive comparisons outside the threshold range. Streaming CCL uses another control flow but should preserve the baseline answer.
4. Code upgrades: Explain the complete change on this one slide. JTAG makes it possible to use the available USB-Blaster without an RS-232 adapter.
5. CPU validation: Both run on the CPU here. Matching count plus centroid checks establish reference agreement on three saved full maps. Python execution speed is not evidence of hardware speed.
6. FPGA implementation: Trace one frame from Python through JTAG to component records and back. Compilation and programming alone do not prove correctness.
7. Problems: Missing IP, environment setup and device identifiers were fixed. The large label configuration was reduced. Negative timing slack remains unresolved.
8. Evidence: Show the five-hour screenshot and the final setup-slack report. Explain that the small design gets through compilation but still fails its required clock period.
9. Bring-up: Library dependencies and exported function names were integration issues. Two simple components passed on the physical board; harder inputs uncovered errors.
10. Experiment: Each case is one 32x32 crop from a different photograph, using synthetic maps. Explain count, CPU timing, round-trip and cycle counter separately.
11. Table: Point out 17 passes and three failures. Five passes have zero detections. Neither 85% exact agreement nor 90% count agreement is detection accuracy.
12. Failure cases: 0068 and 0134 show merge-like behavior. 0116 has the same head positions but a different area, so checking only printed points would miss an error. Timing failure is plausible but not yet proven as the sole cause.
13. Locations and video: Explain crop vs source coordinates. Start the external video separately if the PDF link is blocked. Show both a passing and failing input.
14. Performance: CPU median timing is generally lower than estimated FPGA active time for these crops. JTAG round-trip is about a second. Do not claim speedup; fixing correctness comes first.
15. Advantages: These are architectural opportunities, not results we have measured. A streaming connection near the map producer can remove the JTAG bottleneck in a future integrated design.
16. Improvement plan: First close timing or create a real slower-clock test build, then reproduce failures and rerun. Next move label storage toward synchronous memories and sequence/pipeline dependent lookups. Full-photo tiling needs boundary stitching.
17. Decision: We have a reproducible prototype with physical dataflow. It is not a validated accelerator yet. State the next measurable milestone: timing clean and all current component tests passing.
18. Evidence: These paths let the audience reproduce the checks and distinguish measured results from estimates.
