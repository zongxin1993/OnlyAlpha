# 编码规范

## 1. 命名

自定义类型必须以 `Only` 开头。

Python：

- 函数和变量：`snake_case`；
- 常量：`UPPER_SNAKE_CASE`；
- 文件：小写下划线。

## 2. 类型

公共接口必须完整类型标注。

核心领域避免：

- `dict[str, Any]`；
- `Any`；
- 裸字符串 ID；
- 无约束 float。

## 3. 函数

函数应：

- 职责单一；
- 参数明确；
- 返回明确；
- 错误明确；
- 不隐藏副作用。

## 4. 类

避免：

- 上帝类；
- 循环依赖；
- 深层继承；
- 隐式单例；
- 全局可变状态。

## 5. 异常

```text
OnlyError
OnlyConfigError
OnlyEngineError
OnlyRuntimeError
OnlyClusterError
OnlyGatewayError
OnlyOrderError
OnlyRiskError
OnlyCacheError
OnlyStorageError
OnlyBacktestError
OnlyResearchError
```

禁止空 `except` 和静默吞错。

## 6. 工具

建议：

```text
ruff
mypy
pytest
```

## 7. 注释

注释解释“为什么”，不是重复代码。

公共领域类型应有文档字符串和使用示例。
