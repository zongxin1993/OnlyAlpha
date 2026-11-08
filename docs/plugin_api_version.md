# Plugin API Version

Rust [PluginProjection](../crates/integration-contract/src/authoring.rs) 支持公共接口 1.0、1.1、1.2。1.2 增加 Probe V2，允许对已声明的非敏感枚举配置逐值给出默认证券。发布时将所选默认证券写入原 Revision 的 probe 配置。V1 的固定默认值及原配置指纹继续按各自原始声明读取。

- major 不同：`PLUGIN_API_VERSION_INCOMPATIBLE`；
- 插件 minor 高于核心：`PLUGIN_API_VERSION_INCOMPATIBLE`；
- major 相同且插件 minor 不高于核心：兼容；
- Descriptor/API 缺失：`PLUGIN_API_VERSION_MISSING` 或 `PLUGIN_DESCRIPTOR_INVALID`。

插件自身业务版本使用 Descriptor 的 `plugin_version`，与 API Version 分离。
