# Market Conformance CLI

当前产品入口：

```text
onlyalpha scenario validate FILE [--format json]
onlyalpha scenario run FILE [--user-data DIR] [--format json]
onlyalpha market profiles [--format json]
onlyalpha market profile PROFILE [--version VERSION] [--format json]
```

Scenario PASSED 返回 0，断言失败返回 1，配置错误返回 2，Runtime 错误返回 3。Conformance list/run 命令将在内建 Pack repository
完成后开放，避免暴露不可运行入口。
