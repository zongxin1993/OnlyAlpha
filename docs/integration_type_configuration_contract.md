# Integration Type and Configuration Contract

OnlyAlpha projects explicitly declared Integration Types from factories already registered by the DataSource and Broker Plugin SPI.
The catalog does not discover plugins, persist types, or infer product identity from Python classes.

```text
installed Plugin/factory
!= Integration Type
!= future Integration Instance
```

An Integration Type ID is a lowercase, dot-separated stable semantic identifier such as
`binance.spot.market_data`. It contains no package/class path, process identity, filesystem path, creation time, or `latest` alias.
The catalog supports deterministic list/category filtering and exact ID lookup only.

The version-1 configuration contract describes product-visible fields, typed defaults, secret requirements, display metadata, and
bounded validation metadata. It provides basic Product/Web validation metadata; the factory's `parse_config()` remains the sole
provider-specific semantic parser. L1 does not pass contract-shaped data to that parser and does not change runtime admission.

Secret declarations contain requirements only. They never contain credential values and do not read or write the existing Credential
Authority. Binance `api_key`/`api_secret` and Tushare `token` are the future product field identities; the current runtime
`api_key_env`/`api_secret_env`/`token_env` paths remain unchanged until the authorized migration phase.

Probe metadata declares a future read-only validation capability; L1 never executes it. A `default_probe_instrument` is only a probe
input. It is not a Universe, allowlist, subscription list, or runtime DataSource configuration. Consumers continue to select runtime
instruments through the existing DataSource create/admission context.

`AGENT_PROVIDER` does not extend `OnlyPluginType` or add a Plugin entry-point group. The Product catalog publishes the stable
`openai.compatible.agent_provider` component contract, while executable parsing, Probe transport, Model Profile binding, and model I/O
remain inside the independently deployable Agent component. Agent node control and Product API bootstrap tokens are infrastructure
credentials and are never fields of this product Integration.

The Integration Type catalog is an in-memory deterministic projection of declared contracts on already registered factories. It is not
a PostgreSQL authority, does not create Integration instances, and disappears with the installed implementation that supplied it.
