# Position comparison data

Literal semantic vectors and actual Python valid-common reference outputs. No Runtime admission or business history conversion. Position IDs are a new component identity, not Python durable identity compatibility.

`valuation-v1.jsonl` contains independently calculated consolidated valuation vectors, including exact cost residuals and HALF_EVEN ties. `valuation-order-contract.json` retains the frozen zero-fee contract unchanged. The Execution valuation test derives the complete contract from the real native Order owner's read-only preview and existing typed Fee Domain constructors, then compares every field with that fixture. The canonical valuation lane requires this test's actual receipt before comparing native valuation outputs. It does not load a Python Order factory or Position implementation. Native exact-cost residuals remain independently specified, rather than using the older rounded-average PnL result as an oracle.
