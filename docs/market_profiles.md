# Market Profiles

`OnlyMarketProfileResolver` 按 `profile_id + effective date` 要求唯一有效版本。内容指纹覆盖 Session、Settlement、Position、Short、
Margin、Price、Quantity、Fee、Liquidity、Slippage 与 Matching；改变 T+0/T+1、费率、lot、margin 或撮合配置会改变指纹。

当前内建：`CN_A_SHARE_CASH@2025.1`（首个正式 Profile）、`GENERIC_T0_CASH`、
`GENERIC_MARGIN_FUTURES`、`GENERIC_24X7_CRYPTO_SPOT`。HK/US/CN Futures/Crypto derivatives/FX ID 仅预留，
不代表正式市场支持。

