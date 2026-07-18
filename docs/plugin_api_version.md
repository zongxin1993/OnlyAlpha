# Plugin API Version

公共版本为 `ONLYALPHA_PLUGIN_API_VERSION = OnlyPluginApiVersion(1, 0)`。

- major 不同：`PLUGIN_API_VERSION_INCOMPATIBLE`；
- 插件 minor 高于核心：`PLUGIN_API_VERSION_INCOMPATIBLE`；
- major 相同且插件 minor 不高于核心：兼容；
- Descriptor/API 缺失：`PLUGIN_API_VERSION_MISSING` 或 `PLUGIN_DESCRIPTOR_INVALID`。

插件自身业务版本使用 Descriptor 的 `plugin_version`，与 API Version 分离。
