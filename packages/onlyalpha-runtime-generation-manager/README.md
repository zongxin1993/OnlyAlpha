# OnlyAlpha Runtime Generation Manager

This infrastructure component verifies immutable wheel bytes, constructs a clean isolated Python process generation, validates
installed `onlyalpha.quant_assets` and `onlyalpha.calculations` content, and records durable compare-and-set activation facts for
new work. It owns no Calculation, Catalog, StrategyRevision, Research Result or LIVE authority.

Artifact identities are public `onlyalpha.distribution` contracts; runtime-generation identities are public
`onlyalpha.runtime.generation` contracts. Paths, registry URLs, process IDs and
hosts are operational details. Every candidate is fully validated before READY; every work binding is immutable; rollback changes
only the new-work pointer; historical resolution requires exact StrategyRevision implementation fingerprints.

Admission records the existing Product Run ID as the work ID. A process must call `require_work_generation` with its own immutable
generation before executing or claiming that work; a different or released binding fails before execution. This adapter preserves
the existing Research/Backtest Run authorities rather than adding a second Run store.
