# markets/testdata: SYNTHETIC test payloads

Every file here is named `synthetic_*`, carries a `_provenance` key, and was **hand-written** from the
documented response schemas to exercise parser branches. None of them is an API response. Their values
must never be displayed or used as data.

Real collected API responses live in `services/api/data/raw/<venue>/<market_id>/` with a `manifest.json`
(url, params, collected_at, sha256), labelled `REAL HISTORICAL`.
