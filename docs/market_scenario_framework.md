# Deterministic Market Scenario Framework

当前正式链为 Parser → Planner → exact DataSource → Action Strategy (`ctx.orders`) → OnlyEngine → Runtime → Collector →
Assertion → Artifact。BACKTEST 可自动执行；其他模式共享 schema 但明确返回 capability error。

```text
Scenario Document → Parser → Planner → OnlyEngine → Runtime → Standard Facts → Assertion → Artifact
```

`onlyalpha.scenario` 是外层验证包。Domain 不拥有市场规则；Parser 不判断订单合法性；Planner 不执行 Runtime；Action 不调用
Manager；Runner 不制造 Broker update；Collector 不重算规则；Assertion 不访问 Runtime 私有状态；Artifact 不推导业务事实。

当前可用：不可变 Domain、严格 Parser、Command planning、只读 Assertion 和 input fingerprint。当前不可用：正式 Action Strategy、
Engine Runner、Scenario Artifact、五个验收场景。因此不得把本页理解为 Scenario 自动执行已经交付。
