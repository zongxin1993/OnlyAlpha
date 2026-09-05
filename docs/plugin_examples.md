# Quantitative Plugins and Examples

ADR 0110 defines the active boundary. Public reusable L1 Operators and L2 Indicators live in official plugins. Production L3
Factors and L4 Strategies belong in private repositories. The main repository keeps exactly two non-production references:
`examples/onlyalpha-example-alpha/` and `examples/onlyalpha-example-strategies/`.

Core never imports these concrete implementations. Example Alpha registers through the public Calculation SPI; example Strategy
documents travel through Definition Resolve and verified Freeze rather than becoming callback or filesystem runtime authority.

ADR 0111 defines two consumption modes for future private L3/L4 repositories. A local checkout may be installed editable or imported
through an explicit development source path for controlled Agent research. A released wheel/private-index installation uses standard
distribution metadata: L3 is discovered through `onlyalpha.calculations`, while L4 authoring JSON is read through its package resource
API. Only installed distributions participate in production plugin discovery; no Core component recursively executes arbitrary paths.

Every L1-L4 library also exposes one `onlyalpha.quant_assets` provider. The management catalog binds provider version to exact content and
creates immutable generation fingerprints. A changed provider must use a new provider version; semantic changes also bump their Calculation
or Strategy-asset semantic version. Refresh affects new authoring/admission only and never mutates an active Run or StrategyRevision.

ADR 0117 adds the next boundary: exact wheel bytes become a public immutable Distribution Artifact manifest, then an independent
Infrastructure component clean-installs and revalidates a complete Runtime Generation before durable new-work activation. Public examples
and private repositories derive the same artifact contract. Runtime rollback changes only the guarded new-work pointer, and historical
StrategyRevisions resolve exact implementation fingerprints without a latest-version fallback.
