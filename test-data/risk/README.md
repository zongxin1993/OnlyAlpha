# Risk common reference vectors

`decisions-v1.jsonl` pins real Python single-order quantity Pipeline outcomes against independently specified limits. `reservations-v1.jsonl` pins actual Python partial-fill/terminal risk-exposure conservation. Rust consumes the same literals. This valid subset does not assert parity with Python ID-only deduplication, silent overfill clipping or incremental restore. Native output comparison is mandatory in both profiles.
