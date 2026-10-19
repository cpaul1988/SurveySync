# Synthetic benchmark contract data

These files are invented labels and saved predictions for two invented pipes.
They contain no page images and were not produced by an OCR model.

- `gold.jsonl`: exact identity `0001`, two spatially separate pipes.
- `correct.json`: both pipe records agree with the labels.
- `swapped.json`: only the two dip values are swapped. The set of values on the
  page is unchanged, but both complete pipe bindings must fail.

Image hashes and run commits are intentionally unknown. No timing, memory,
hardware, real-book accuracy, or release-acceptance claim follows from this data.
See `docs/FIELDBOOK_BENCHMARK.md` for private annotation and run instructions.
