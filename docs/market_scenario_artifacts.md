# Market Scenario Artifacts

Scenario Artifact 必须扩展现有 Result/Artifact writer，并包含稳定 schema、row count、hash、input/result fingerprint。墙钟、绝对路径、
PID、hostname、随机 UUID 和 traceback 路径不得进入确定性指纹。

当前仅实现 canonical input fingerprint；Scenario summary、assertion/action 表、profile timeline、compiled rules 和标准 Scenario
manifest 尚未实现，不能建立平行存储或宣称零行 Schema 门禁已通过。
