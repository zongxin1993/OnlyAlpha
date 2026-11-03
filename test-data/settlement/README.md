# Settlement common input

`common-v1.json` is a controlled language-neutral cash-security fixture with a full explicit Domain Calendar, October 26 holiday, compiled six-axis policy, immutable owner/Position/Allocation/economic inputs and non-secret technical provenance. It is not live-market or production deployment evidence.

The native checker compares all six schedule dates, initial status, signed cash flow and ordered due transitions against independent T0/T1/T2/T3 literals. October 24/25 are weekend days and October 26 is the declared holiday. Buying four units for 40.00 with 1.00 charges debits 41.00; selling for 48.00 credits 47.00. It also checks native economic maturity, complete status and real fresh-process checkpoint continuation. The Rust owner tests preserve exact Calendar roundtrip and duplicate registration idempotence.

IDs/codecs are not equated with historical Python records. Future booking completeness, whitespace/venue rejection, safe pre-reserved slots and strict restore remain independently tested Rust corrections/extensions. No whole Python parity is claimed.
