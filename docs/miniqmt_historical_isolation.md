# Retired MiniQMT adapter and retained historical evidence

The current MiniQMT SDK adapter and its diagnostic/capture commands are retired under
[ADR 0139](adr/0139-linux-first-rust-trading-kernel-migration.md). It is not an installed DataSource or Broker option.
This page preserves the design reference; it does not offer a supported installation or SDK execution path.

Its native historical queries required process isolation because a native abort could terminate the host interpreter.
That lesson remains relevant to plugin/worker boundaries: a worker crash, malformed result or timeout cannot be accepted as
successful warmup or authorize a stale-cache fallback. Generic streaming warmup still requires an explicit provider compatibility
profile when the construction graph consumes historical Bars; no provider is silently selected by Core.

Frozen payloads and manifests under `test-data/miniqmt/cn_a_share_v1/` remain immutable offline inputs for provenance and independent
reference/product conformance. They do not require xtquant or a live QMT installation. Do not recapture them in place, erase their
provider identifiers, or claim that their retention proves the retired adapter is available.

Existing Integration revisions, runtime bindings, sealed history and Evidence remain readable through their owning readers.
Missing implementation admission fails closed; retirement does not rebind old work or delete business data.
