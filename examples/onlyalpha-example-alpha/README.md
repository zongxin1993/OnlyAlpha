# OnlyAlpha Example Alpha

This non-production L3 reference package demonstrates the public Calculation SPI used by future private Alpha distributions. It
contains one hypothesis-bearing Momentum Factor and is installed only by development or acceptance environments.

For a frequently changing local checkout, use an editable path install:

```bash
uv add --editable /path/to/private-alpha
# or
python -m pip install -e /path/to/private-alpha
```

Agent research tooling may also put `/path/to/private-alpha/src` on its explicit development import path and import
`private_alpha.registration:registrations`. It must register that exact provider only inside the controlled research/admission process.
Production nodes do not scan source directories: build a wheel or install the package from a private index so the
`onlyalpha.calculations` entry point is present in distribution metadata.

```bash
uv add private-alpha-package
# or
python -m pip install private-alpha-package
```

The package exposes both execution and management entry points:

```text
onlyalpha.calculations  → exact RESEARCH/TRADING registrations
onlyalpha.quant_assets → versioned L3 provider and content fingerprint
```

For an explicit checkout provider during controlled development:

```python
from onlyalpha.quant_assets import only_discover_quant_asset_providers
from onlyalpha_example_alpha.provider import quant_asset_provider

generation = only_discover_quant_asset_providers(
    (quant_asset_provider(),),
    include_installed=False,
)
```

Change `provider_version` whenever implementation content changes. Change the Factor semantic version as well when its hypothesis or output
semantics change. `distribution_version` must equal the installed distribution metadata (the workspace version tool maintains it for this
reference package). Existing Strategy Revisions keep their exact prior implementation fingerprint.
