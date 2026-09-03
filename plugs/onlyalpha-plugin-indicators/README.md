# OnlyAlpha L2 Indicators

This official public package owns deterministic calculations with stable financial/descriptive meaning and no predictive Target
hypothesis. Its existing Indicator semantic identities are retained. Each named Feature remains a Calculation output port; this
package does not create a Feature Store or independent Feature identity authority.

The package exposes exact execution registrations through `onlyalpha.calculations` and the versioned
`onlyalpha.indicator.library` management provider through `onlyalpha.quant_assets`. A checkout can be installed with
`uv add --editable /path/to/indicators` or `python -m pip install -e /path/to/indicators`; released environments may use a wheel or private
index. Content changes require a new provider version, while semantic changes additionally require a new Indicator semantic version.
