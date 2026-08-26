# P9.K.4 Closure-2 — Response Compatibility Completeness

- Date: 2026-08-26
- Environment: macOS arm64, Python 3.12, Node 24
- `TASK_BASE_SHA`: `4f7524fa3fc158ae6c702a00b13157ba8c7dd060`
- `AUDIT_BASE_SHA`: `4f7524fa3fc158ae6c702a00b13157ba8c7dd060`
- `AUDIT_HEAD_SHA`: `7c25a3cc42c7ea6e189044b5b8d8c62dc8b78d5f`
- `IMPLEMENTATION_SHA`: `7c25a3cc42c7ea6e189044b5b8d8c62dc8b78d5f`
- `PUBLIC_API_COMPATIBILITY_BASE_SHA`: `d9713159eeb2e3dcc294d1dbd456e7332ef2cbac`
- Gate: impact-aware Task Gate; not a Phase Gate or Final-SHA Certification
- Scope: response compatibility completeness in the existing OpenAPI governance authority

## Executive summary

Closure-2 repairs three response-side false-negative classes in the existing comparator: new named properties that exceed the old
`additionalProperties` acceptance space, new response statuses, and new response media types. The implementation preserves the frozen
old-v2-client→new-v2-server model:

```text
Request:  OldValidRequests ⊆ NewAcceptedRequests
Response: NewPossibleResponses ⊆ OldClientConsumableResponses
```

The fix adds no comparator, baseline, waiver, cache, framework, public API delta, K5 code or semantic identity. Local Task Gate evidence
and the directly applicable exact-SHA remote jobs passed. The canonical OpenAPI and generated TypeScript bytes remain unchanged.

```text
BLOCKER: 0
MAJOR: 0
MINOR: 0
SUGGESTION: 0
```

## Previous findings status

### F-K4-001 — Compatibility engine incompleteness

- Severity: MAJOR
- Previous Status: PARTIALLY_RESOLVED
- New Evidence Classification: PREVIOUSLY_HIDDEN
- Status: RESOLVED
- Evidence: baseline characterization returned `COMPATIBLE` for closed-response optional/required fields, an AP-schema value-space
  violation, a new response status and a new response media type. After the fix, the complete contract suite reports `50 passed`.
- Violated Rule: ADR 0103 requires deterministic, mechanical, fail-closed v2 compatibility in the old-client→new-server direction.
- Previous Actual Behavior: new server response values outside the old client's consumable set could receive a false `COMPATIBLE` verdict.
- Expected Behavior: every current-v2 response compatibility-sensitive surface enforces `new response set ⊆ old consumable set`.
- Fix: traverse sorted new-only response properties against the old AP policy, reuse `_schema_changes()` for AP schema containment, and
  reject sorted new-only response status/media surfaces in the one existing comparator.
- Reproduction: the RED run was `5 failed, 45 passed`; failures covered both closed-field requiredness variants, AP-schema narrowing,
  status addition and media addition.
- Verification: GREEN contract run `50 passed`; local and exact-SHA remote Task Gate evidence below.
- Blocking: NO

No semantically duplicate finding was created.

## First-principles implementation

For a new-only named response property:

| Old `additionalProperties` | Result |
|---|---|
| `false` | BREAKING |
| `true` | COMPATIBLE |
| missing (`true`) | COMPATIBLE |
| schema containing the new property schema | COMPATIBLE |
| schema not containing the new property schema | BREAKING |

The AP-schema case calls the existing direction-aware `_schema_changes()` with the old wildcard schema and new named-property schema.
The existing wildcard-to-wildcard AP comparison remains intact. Added and removed response statuses and media types both follow the
frozen strict v2 policy and produce stable sorted evidence.

## RED characterization evidence

Before production code changed:

```text
tests/contracts/test_openapi_contract.py: 5 failed, 45 passed

closed response + optional new property:       false COMPATIBLE
closed response + required new property:       false COMPATIBLE
old AP schema narrower than new named property: false COMPATIBLE
new response status:                            false COMPATIBLE
new response media type:                        false COMPATIBLE
```

Removed status/media behavior and the remaining existing suite were already green.

## Tests added

- AP=false with optional and required new response property;
- AP=true and missing AP with a new response property;
- broader/narrower AP schema containment for a new named property;
- existing response property value-set narrowing/broadening regression;
- added and removed response status with exact stable evidence;
- added and removed response media type with exact stable evidence;
- repeated comparison equality plus sorted/deduplicated breaking evidence.

## Verification evidence

```text
contract RED characterization:              EXPECTED FAIL — 5 failed, 45 passed
contract GREEN:                             PASS — 50 passed
openapi verify --base d9713159...:          PASS — UNCHANGED; 0 breaking changes
architecture:                               PASS — 465 passed
research-command:                           PASS — 47 passed
research-query:                             PASS — 110 passed
targeted Ruff:                              PASS
targeted Ruff format:                       PASS
governance mypy:                            PASS
version sync:                               PASS — 0.9.0
git diff --check:                           PASS
remote exact-SHA openapi-contract:          PASS — run 32968024259 / job 98175007850
remote exact-SHA architecture:              PASS — run 32968024259 / job 98175007884
remote exact-SHA static:                    PASS — run 32968024259 / job 98175007535
remote exact-SHA web:                       PASS — run 32968024259 / job 98175007866
remote exact-SHA research-command:          PASS — run 32968024259 / job 98175007989
remote exact-SHA research-query:            PASS — run 32968024259 / job 98175008196
```

The direct required jobs are the Task Gate evidence. A duplicate same-SHA run was concurrency-cancelled and is not counted as PASS.
The broader non-Task-required `core-full` job in the same run was **FAIL** (`2555 passed, 1 failed`):
`test_engine_sim_virtual_broker_executes_accepted_then_next_bar_trade` timed out waiting for an unrelated SIM trade projection. This
Closure changes only the OpenAPI governance script and its contract tests, and the failure has no dependency path to the comparator;
therefore it is recorded truthfully as wider CI evidence but does not replace the impact-aware Task Gate verdict. Repository-wide release,
Phase Gate and Final-SHA Certification were not required or executed, and the overall workflow run is not claimed as PASS.

## Byte identity evidence

```text
OpenAPI before:      c72395d6b9ba921c7e286f45e9b41ba0dbce7de3008fbdd76519d66d768f8b0e
OpenAPI after:       c72395d6b9ba921c7e286f45e9b41ba0dbce7de3008fbdd76519d66d768f8b0e
generated.ts before: 7f9be5af016ae6685a03818056027a1dee88a1ab37334f4f9d5530e3e16b13fd
generated.ts after:  7f9be5af016ae6685a03818056027a1dee88a1ab37334f4f9d5530e3e16b13fd
```

## Invariant matrix

| Invariant | Status | Evidence |
|---|---|---|
| INV-K4-C01 directional request compatibility | PASS | existing request matrix remains green |
| INV-K4-C02 directional response compatibility | PASS | new response set containment tests |
| response new-only property under AP=false | PASS | optional and required cases BREAKING |
| response new-only property under AP=true/missing | PASS | both cases COMPATIBLE |
| response new-only property under AP schema | PASS | broader/narrower containment matrix |
| response status surface governance | PASS | additions and removals BREAKING |
| response media surface governance | PASS | additions and removals BREAKING |
| referenced semantics | PASS | existing component-reference regression green |
| recursive termination | PASS | existing recursive regression green |
| deterministic verdict/evidence | PASS | repeated result equality; sorted/deduplicated tuple |
| discriminator fail closed | PASS | existing discriminator regression green |
| vocabulary completeness | PASS | exact current-v2 vocabulary test green |
| unknown semantics fail closed | PASS | unsupported keyword test green |
| one compatibility authority | PASS | only `scripts/openapi_contract.py` owns comparison |
| canonical identity immutability | PASS | OpenAPI bytes unchanged |
| generated consumer immutability | PASS | generated.ts bytes unchanged |
| Research/Trading/Runtime boundary | PASS | no semantic source delta; architecture and Research lanes green |
| persistence/recovery boundary | PASS | no persistence, schema, retry or recovery delta |
| identity uniqueness | PASS | one canonical contract and immutable Git baseline mechanism |
| determinism | PASS | sorted differences and final sorted unique evidence |
| single authority | PASS | no second comparator, baseline, waiver or fallback |

## Non-blocking technical debt / suggestions

None. This closure intentionally does not expand into a general JSON Schema theorem prover.

## Audit verdict

```text
Verdict: GO — P9.K.4 DONE / VERIFIED
P9.K.5: IMPLEMENTATION READY
```

```text
设计是否被正确实现？ YES
是否违反唯一性？     NO
是否违反确定性？     NO
是否违反 ADR/架构？  NO
F-K4-001 是否关闭？  RESOLVED
P9.K.4 是否完成？     YES
是否可进入 P9.K.5？  GO
```
