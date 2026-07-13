# ADR-0003：Cache 与 Storage 分离

- 状态：Accepted
- 日期：2026-07-13
- 关联模块：cache、storage

## 背景

缓存和持久化具有不同一致性、可靠性和性能目标。

## 决策

定义独立接口：

```text
OnlyCache
OnlyStorage
OnlyRepository
```

初始实现使用 Memory Cache 和 SQLite Storage。

## 结果

- 策略不依赖数据库；
- 缓存可替换；
- Storage 可审计和恢复；
- 需要明确双写和失效策略。
