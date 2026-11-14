# Recorded runs (RECORDED RUN)

Committed output of `scripts/record_runs.py`, the official Blind Replay run (docs/EVALUATION_PROTOCOL.md §8, §9).
**Empty on purpose until the lead runs it** on the real, reviewed cases. Nothing here is hand-written, and no
dry run (mocked provider) is ever committed here.

```
recorded_runs/
  runs/<run_id>/manifest.json            run index: model tag, variants, cases + case_sha256, both
                                         contamination flags, rows, skipped, failed, scorecards, rows_sha256
  runs/<run_id>/rows/<prediction_id>.json  one saved forecast: Prediction, exact prompt + snapshot JSON,
                                         model-call audit fields, scoring context, every hash
                                         (served read-only, verified, by GET /api/replay/recorded)
  scorecards/<variant>--<UTC>--<sha12>.json  Scorecard snapshot (routes/benchmark.py RecordedScorecard),
                                         served read-only by GET /api/benchmark
```

Rows are written before anything is revealed. Scorecards come later and are the only files that depend on
outcomes. `tests/test_record_runs.py::test_committed_recorded_runs_recompute` recomputes every hash in
every committed row and scorecard: `row_sha256`, `prompt_sha256`, `snapshot_sha256`, `record_sha256`,
`final_prompt_sha256`, `transcript_sha256`, `raw_output_sha256`, `scorecard_sha256`, `snapshot_sha256`.
