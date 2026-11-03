# Order reference inputs

`domain-inputs.json` retains its frozen canonical bytes. The native Order fixture test independently constructs requests, creates real Order snapshots, derives the explicit zero-fee contracts with Fee Domain constructors and checks exact regeneration. The same owner checks the retained Execution, Broker, Margin and multi-Cluster valuation Order/Fee fixtures. Zero fees here are controlled test inputs, never a product default.

Lifecycle and arithmetic expected values remain independently asserted by Rust tests and the literal output checker, without importing the old Python Manager. Source/recovery and corrected/unsupported paths remain separate native invariants, not claims of legacy checkpoint or Runtime compatibility.
