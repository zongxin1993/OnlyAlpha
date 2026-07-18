# Plugin Lifecycle

统一状态为 CREATED、INITIALIZED、CONNECTING、CONNECTED、RUNNING、STOPPING、STOPPED、FAILED。Runtime 启动顺序为
DataSource、Broker 的 initialize/connect/start，再启动 Cluster；停止时先 Cluster/Runtime，再按 Broker、DataSource 的逆序
stop/close。

initialize/connect/start 任一失败均携带 plugin_id/resource_id，并逆序 stop/close 已初始化资源。stop/close 必须幂等。
单个资源在 stop/close 中失败不会跳过其余资源；Runtime 完成其余清理后抛出包含 plugin_id/resource_id 的结构化错误。
`OnlyPluginHealth` 统一报告 UNKNOWN、HEALTHY、DEGRADED、UNHEALTHY、STOPPED；Engine Snapshot 汇总 Descriptor、Resource、
Lifecycle、Health、Capability 和引用计数。
