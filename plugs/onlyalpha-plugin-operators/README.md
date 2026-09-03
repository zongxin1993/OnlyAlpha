# OnlyAlpha L1 Operators

This public L1 library exposes exact Calculation registrations through `onlyalpha.calculations` and a versioned management provider through
`onlyalpha.quant_assets`. Install it from a checkout with `uv add --editable /path/to/operators` or
`python -m pip install -e /path/to/operators`; released environments may use a wheel or package index.

The management provider ID is `onlyalpha.operator.library`. Any implementation content change requires a new provider version; any semantic
change also requires a new Operator semantic version. Hot-plug refresh affects new catalog snapshots only.
