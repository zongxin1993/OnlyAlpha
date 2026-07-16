# Indicator Factory Registry

`OnlyIndicatorFactoryRegistry` 以可扩展 `OnlyIndicatorTypeId` 为键。内置 ID 使用大写规范；包含点的第三方 ID 规范化为小写。重复注册和未知类型均 Fail Fast。

创建请求包含 type、local indicator ID、BarType 和参数。空参数使用具体 Config 默认值，非空参数覆盖默认值。Factor-scoped `OnlyIndicatorRegistry` 用以下完整键保存实例：

```text
runtime_id / cluster_id / factor_id / indicator_id
```

相同 local ID 可在不同 Cluster 或 Factor 使用，但可变实例绝不共享。Factor 拥有创建能力；Strategy 只有 Factor View；Runtime/Assembly 不识别具体算法。
