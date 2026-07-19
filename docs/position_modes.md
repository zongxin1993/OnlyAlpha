# Position Modes

市场规则层明确 `LONG_ONLY / NETTING / HEDGING`；运行 Position 原有 Side 与 Settlement Bucket 被复用。
Position Effect 定义 `OPEN / CLOSE / CLOSE_TODAY / CLOSE_YESTERDAY / REDUCE_ONLY / AUTO`。

A 股为 LONG_ONLY 且普通裸卖空禁用。Generic Futures 使用 HEDGING 并允许 unrestricted short，用于验证 SELL OPEN/BUY CLOSE 的
领域边界；现有生产 ExecutionProcessor 的完整期货双向写入仍未宣称完成。Borrow 目前只有 Disabled/With Borrow/Unrestricted
规则边界，Locate、费率、Recall 尚未实现。

