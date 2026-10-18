# Clock independent vectors

`timers-v1.tsv` records exact input instants, registrations and expected ordered events. Timer records use
`id,ONCE|RATE,first_deadline,interval|-`; events use `id,deadline,registration_sequence,fire_count`.
Integers are exact decimal text; this is test transport, not a persistent Clock or Runtime protocol.
Python and Rust consume the same independently specified expectations. Correct-contract adversarial Rust cases
are separate from common behavior vectors; known Python defects must never become expected Rust behavior.

`lifecycle-v1.tsv` defines five small scenario inputs and expected events/failure count/active state:
`cancel` removes the second Timer before advancement; `register` cancels it inside the first callback and registers
`child` at that callback deadline; `failure` fails the first periodic callback while a second one-shot continues;
`close` closes before advancement; `restore` advances a periodic Timer to `second`, restores its valid snapshot into
a fresh instance with explicit callback binding, then continues to `target`. All begin at zero. `first` is the initial
deadline/interval, `second` the second deadline or pre-restore target. `-` means no events. These are common correct
behaviors, not equivalence of snapshot formats or certification of defective Python recovery paths.
