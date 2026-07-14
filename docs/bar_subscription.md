# Bar Subscription 与主周期

`OnlyBarSubscription` 保存不可变 BarType 集、PRIMARY_ONLY delivery mode、freshness policy 和 primary BarType。
首版一个 Subscription 只覆盖一个 Instrument。

未显式指定时，全部 TIME Bar 按 `specification.step` 选择最小周期，稳定 BarType ID 仅用于同 step 消歧，
不使用输入或注册顺序。显式 primary 必须属于订阅集合并优先于默认选择。订阅含任何非 TIME Bar 时，框架
不猜测可比关系，必须显式 primary。

PRIMARY_ONLY 表示主周期关闭才调用一次 `on_bar(primary_bar, context)`；辅助周期只通过不可变 Snapshot
读取。辅助周期当期未关闭时，`latest_closed` 返回上一个已关闭 Bar或 None，`was_updated` 为 false。
EACH_BAR/TIME_SLICE 枚举是扩展点，首版构造时明确拒绝，防止语义含混。
