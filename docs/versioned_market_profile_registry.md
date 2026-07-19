# Versioned Market Profile Registry

`OnlyMarketProfileRegistry` 注册 Family/Version，校验唯一身份和不重叠有效期。解析请求由 `OnlyMarketProfileRequest` 表达；无 version 是 `AUTO_EFFECTIVE_DATE`，有 version 是 `PINNED_VERSION`。Removed 不能创建新运行，Deprecated 保留固定回放边界。

`OnlyResolvedMarketProfile` 保存请求、解析版本、状态、Capability、Reference、Override 与规则指纹；`OnlyResolvedMarketRuleManifest` 是 Artifact/Web 可读取的不可变规则投影。当前四个内建版本均为 Experimental，不能描述为完整生产市场支持。

