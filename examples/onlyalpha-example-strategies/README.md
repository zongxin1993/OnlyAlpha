# OnlyAlpha Example Strategies

This non-production L4 library contains canonical authoring documents only. `simple_momentum` is a display/asset name, not a
runtime strategy identity. Submit the Research Definition through the versioned Product API, then use verified Research evidence
and Freeze to obtain the immutable `strategy_fingerprint` authority.

The read-only asset API has no OnlyAlpha runtime import. The optional management provider depends only on the public
`onlyalpha.quant_assets` contract and does not call Engine, Broker, databases or Strategy publication services.

Both source checkouts and installed distributions use the same read API:

```python
from onlyalpha_example_strategies import load_strategy_definition

# uv/pip-installed package resource
payload = load_strategy_definition("simple_momentum")

# explicit local/private checkout root during rapid iteration
payload = load_strategy_definition("simple_momentum", library_root="/path/to/private-strategies")
```

Install a changing checkout with `uv add --editable /path/to/private-strategies` or
`python -m pip install -e /path/to/private-strategies`. For a released private build, use `uv add <distribution>` or
`python -m pip install <distribution>`. The returned JSON is authoring input for the Product API; its filesystem/package location never
becomes Strategy identity or Runtime authority.

The distribution also registers `example-strategies` under `onlyalpha.quant_assets`. Exact resolution uses provider ID/version plus asset
ID/semantic version:

```python
from onlyalpha.quant_assets import only_discover_quant_asset_providers

generation = only_discover_quant_asset_providers()
asset = generation.resolve_strategy_asset(
    "example.strategy.library",
    "1",
    "example.strategy.simple_momentum",
    "1",
)
payload = asset.resource_bytes("research-definition.json")
```

Any resource change requires a new provider version. A Strategy semantic change also requires a new asset semantic version. The selected
catalog generation and content hashes are admission inputs. `distribution_version` must equal installed distribution metadata (the workspace
version tool maintains it for this reference package); verified Freeze remains the point that creates runtime Strategy identity.
