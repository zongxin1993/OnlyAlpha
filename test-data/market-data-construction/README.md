# Construction conformance inputs

Records are hand-specified current recipe1, graph1, requirement1, resolution plan3, identity2 and compiled lane1 values.
Expected fingerprints use standard SHA-256 of sorted compact UTF-8 JSON, independently of either implementation. Arithmetic
outputs are literal OHLC/volume/count expectations. No production encoder or executor generates the expected results.
Both Rust and Python consume these files through their real APIs. Operations use the explicit Shanghai calendar from the
shared test fixture and explicit close-time logical init. Rust additionally restores into a fresh executor mid-window.

Common valid behavior is a reference, not whole-module or checkpoint wire parity. Rust tests separately reject coercive
owner aliases, duplicate checkpoint rows, unnormalized grid origins, late/duplicate source input and partial restore;
Python audit found absent unregister mutation and duplicate checkpoint row collapse. Those defects are not Rust oracles.
Rust component manager schema4 is not admitted to Python Runtime schema3 and grants no Source/Generation readiness.
