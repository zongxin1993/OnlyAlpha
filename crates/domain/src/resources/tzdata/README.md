# Pinned timezone resources

These are runtime inputs for Rust Domain time conversion, separate from Rust source and test fixtures.

- `2026.3/` contains the exact TZif bytes from Python `tzdata==2026.3` (IANA `2026c`).
- `dataset.json` records upstream package provenance and each zone file checksum.
- `LICENSE-0` and `LICENSE-1` preserve the upstream notices.
- `src/tzdb_rules.rs` embeds these resources at compile time; no host timezone database is consulted.

Keep the resource bytes unchanged within a version. The controlled upgrade procedure is documented in
`docs/rust-kernel-development.md` at the repository root. Verify with:

```text
uv run python scripts/domain_timezone_data.py --check
```

Run verification through the canonical dev entry described in `AGENTS.md`.
