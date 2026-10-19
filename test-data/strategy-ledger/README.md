# Strategy Ledger reference vectors

Hand-authored valuation-v1.jsonl is consumed by the actual Python Ledger/Allocation/Valuation reference and Rust lifecycle tests in debug/release. It covers same-instrument independent Cluster costs, losses, zero fees and exact cumulative cost with half-even rounding. Rust-only adversarial lifecycle cases classify unsupported Python rebate/partial-reservation and identity/recovery defects separately; these vectors do not certify Runtime admission or deployment history.
