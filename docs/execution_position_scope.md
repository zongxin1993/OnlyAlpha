# Execution Position Scope

`OnlyExecutionPositionScope` 是一次 Broker Update 对 Position 的唯一不可变身份：包含 runtime、account、cluster、
instrument、side、effect、mode、Position Key、Allocation Key 和解析来源。`OnlyExecutionPositionScopeResolver` 是唯一
执行期方向解析入口；Market Trade Instruction 优先于 Order 的显式 Offset，冲突会以 `POSITION_SCOPE_CONFLICT` 失败。

Execution Processor 在分派前解析一次 Scope，并将它传递给成交、Snapshot、Audit、Reconciliation Request 和失败阻断。
Broker Position Snapshot 必须显式携带 side；数量始终非负，不能以正负号表示 LONG/SHORT。
