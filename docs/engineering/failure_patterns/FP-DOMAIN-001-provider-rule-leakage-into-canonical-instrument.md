# FP-DOMAIN-001 — Provider/market rules leak into canonical Instrument semantics

## Failure family

A generic Instrument or DataSource contract embeds market-specific assumptions such as board categories, lot size, adjustment flags, suspension rules, yield-curve concepts, or exchange-specific permissions.

## External / internal evidence

- RQAlpha issue #474: `board_type` and hard-coded lot-size assumptions were insufficient for newer Chinese boards and their different permissions/rules.
  - https://github.com/ricequant/rqalpha/issues/474
- RQAlpha issue #321: extending DataSource/Instrument beyond the original asset assumptions was difficult because generic interfaces still embedded stock/bond-specific fields and hidden `Instrument` expectations.
  - https://github.com/ricequant/rqalpha/issues/321
- Evidence status: observed upstream extension/modeling defects.

## Observed symptom

Adding a new board, asset class or provider requires patching generic Core code, hidden attribute assumptions trigger runtime errors, or a single canonical field attempts to represent changing market permissions/rules.

## Generalized root cause

Stable identity/domain semantics and externally changing market/provider rules were not separated at the contract boundary.

## Risk to OnlyAlpha

The Market-Agnostic Core invariant is weakened, provider changes force Core changes, hidden compatibility assumptions become runtime failures, and one canonical field may acquire multiple incompatible meanings.

## OnlyAlpha invariant

Canonical Instrument identity contains only stable cross-market semantics. Rules that can change with market, venue, provider, regulation, board or protocol remain behind Market Product / Reference / Plugin contracts unless evidence proves a genuinely universal concept is missing from Core.

## Required protection

- explicit Instrument contract with no undocumented required attributes;
- provider/reference rules represented through typed capabilities/reference snapshots rather than hidden Core conditionals;
- fail closed on unsupported execution-relevant provider rules;
- architecture tests preventing concrete provider imports/DTOs from entering Core;
- public example/private plugin contract parity for newly admitted universal concepts.

## Required tests

- add a provider/board with different lot/permission rules without changing canonical Instrument identity semantics;
- unsupported execution-relevant rule → plugin/reference admission fails closed rather than defaulting;
- custom DataSource/Provider implementation satisfies only the documented public contract and does not depend on hidden attributes;
- architecture test confirms provider-specific DTOs/enums do not leak into `onlyalpha.domain` canonical business logic.

## Non-solutions / rejected shortcuts

Adding more `if board == ...`, expanding one generic enum for every provider distinction, or relying on duck-typed undocumented attributes only postpones the boundary failure.

## Scope notes

Applies to Instrument, Market Product, Market Reference, Provider/DataSource/Broker SPI and plugin-admission design.