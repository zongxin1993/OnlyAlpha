# Event independent vectors

`records-v2.jsonl` contains complete explicit schema-2 expected Event records: exact negative nanoseconds, sequences beyond
64 bits, causal IDs, all current scalar payload families, nested mapping data and a Domain Bar. The Bar record reuses the
independent Domain `fact-records-v1.jsonl` expectation; no implementation generated these expected values.

`delivery-v1.jsonl` contains explicit capacities, policies, UUIDs and ordered actions. Expected observer outcomes use
`event_uuid|subscription_uuid|handler_name|OK-or-ERR`; errors use `zero_based_action_index:category`; replacements use
`displaced_event_uuid|accepted_event_uuid`. Event IDs are the zero-padded UUID spelling of the supplied sequence, with zero
Unix event/init nanoseconds and explicit Engine/Runtime scope. No source of random IDs or time supplies expected results.
Python subscription UUID creation is controlled at its existing UUID allocation boundary with these recorded identities.

Publication-result cases check the pure port value's count-conservation contract; no routing or durable delivery occurs.
Both consumers preserve all identity/causal/scope fields. Object member order is not semantic wire identity. Diagnosed Python
mutability/reentrant/concurrent dispatch, unbounded samples and legacy/coercive readers are outside common equivalence;
Rust adversarial/capability/lifecycle tests enforce the approved corrected contract separately. Passing common vectors is not
whole-module parity, Runtime admission, deployment recovery or a benchmark. These files are test transport, not a new journal.
