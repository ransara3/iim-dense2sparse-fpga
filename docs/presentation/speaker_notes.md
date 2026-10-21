# Presenter notes (approximately 6–8 minutes)

1. Explain baseline CPU and proposed FPGA decoder; inputs and output definition match.
2. Both algorithms on CPU: identical counts and centroids; OpenCV is faster than the Python streaming reference. The table uses the user-supplied full-map timings (0.22/0.005, 0.06/0.001, 0.04/0.000 seconds). Rounded zero is not literal zero. These CCL-only timings differ from later quantization+decoder crop measurements.
3. Cropping: show the five-hour synthesis screenshot. Reducing label and image limits made compilation practical. Fair matched crops are useful for debugging, but do not demonstrate full-frame behavior or resolve timing.
4. Show cycles divided by clock frequency, and distinguish active-core time from JTAG round-trip.
5. Show all 20 cases; head-count agreement alone can conceal a wrong component area.
6. Report CPU mean 52.66 us versus FPGA active estimate 83.86 us and round-trip 1.250 s. Accuracy is not established: 17/20 exact matches, five zero-component cases.
7. Present FPGA potential accurately: fixed work gives nearly constant active cycles, and sample 0136 has a lower estimated core time than CPU. The four-head sample 0116 has a faster CPU and fails agreement, so higher head counts do not establish a speed advantage. Close timing, fix correctness and test controlled input density before claiming speedup. Optional video.

Additional full-photo experiment (before the final slide):
- One photo was covered using 1,230 independent tiles, including smaller edge tiles. This is not a single full-frame decode and boundaries are not stitched.
- 95.85% exact agreement looks high because 1,174 CPU tiles are empty. Only 5/56 nonempty tiles match; 43 failures have equal counts but different records.
- CPU total of per-tile medians is 62.02 ms; FPGA active estimate is 102.14 ms. The ratio is 1.65, so FPGA is slower on this workload. JTAG round-trip sum is 22.25 minutes.
- These findings strengthen the need to fix timing and component correctness before making acceleration claims.
