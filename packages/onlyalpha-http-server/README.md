# onlyalpha-http-server

This Rust package owns the native HTTP/WebSocket listener for the first Shipping
workstation: chart and indicator display, the Factor metadata board, and the
Source/Integration/watchlist dependencies required by those flows. Normal user
operations enter through Shipping Web and the versioned Product API.

The actual native route declarations are in `rust/routes.rs`; strict HTTP wire
types are in `rust/wire.rs`. WebSocket declarations are in `rust/stream_wire.rs`.
The same source-built executable serves requests and performs pure
`--export-openapi` / `--export-websocket` projection without starting a Host.
Python and Node contract generators consume those projections; they do not own a
second API schema. Version, strictness, decimal/time representation, security and
breaking-change rules remain in the [Product Transport Contract](../../docs/architecture/product-transport-contracts.md).

The native workstation requires explicit operational configuration, an exact
compatible schema/namespace, the original master key and one owning authority
session. Startup fails closed before READY when those requirements are absent.
The admitted algorithm installation contains only the isolated Factor/Indicator
SDK and its exact dependencies; it does not load a Python Product application.
The Cargo package, native tests and canonical validation paths remain independent
of Python wheel packaging.

Standalone Research, Data, Strategy, Backtest, Agent and System business surfaces
are currently unimplemented or denied according to the actual native route
policy. This implementation sequence does not remove their constitutional
long-term goals. Retired Python serving applications, bootstrap clients and
special-purpose browser servers are not fallback execution paths.

Existing immutable facts, exact revisions, history, keys and recovery readers are
retained. Missing current executable capability does not authorize rewriting
history or substituting a latest revision. See the [Rust Product Backend Contract](../../docs/rust-product-backend.md)
and the canonical dev verification entry for deployment and validation rules.
