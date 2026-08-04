# Paper Acceptance Artifact Schema

每次运行写入独立目录：

```text
user_data/acceptance/paper/paper-acceptance-<UTC>-<run-id>/
├── manifest.json
├── environment.json
├── sanitized_config.json
├── lifecycle.jsonl
├── inspections.jsonl
├── observations.jsonl
├── health.jsonl
├── orders.jsonl
├── reservations.jsonl
├── worker/
├── assertions.json
├── report.md
└── COMPLETE
```

所有文件通过临时文件、flush、fsync 和 atomic replace 写入；`COMPLETE` 最后创建。没有 `COMPLETE` 的目录不是正式验收结果。

`manifest.json` schema version 1 保存总体 Verdict 和每个 Case 的独立 Verdict。`assertions.json` 保存 Evidence：case、category、Verdict、reason code、UTC 时间、expected、actual、相对 artifact path 和 required 标志。

Historical Inspection 明确区分 `provider_raw_bar_count`、`accepted_bar_count`、Replay attempted/processed/rejected/
duplicate，以及 provider/attempted/processed/watermark 四个尾部。失败 Evidence 记录 `requested_case`、`execution_stage`、
`failure_kind`、`exception_type` 和 `exception_message`。`worker/request.json`、`worker/result.json` 与可选
`worker/failure.json` 会复制、脱敏并通过相对路径关联。

序列化规则：Decimal 使用字符串，Timestamp 使用 UTC ISO-8601，Enum 使用 value，Artifact path 必须为相对路径。账号、Token、Secret、Password、Credential、Auth 字段和绝对用户路径必须脱敏。
