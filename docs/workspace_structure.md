# OnlyAlpha 工作区结构

目录职责遵守 [ADR 0142](adr/0142-library-product-boundaries-and-independent-releases.md) 和
[Repository architecture](repository-product-architecture.md)。目录位置不代表能力已经完成迁移或验收。

```text
OnlyAlpha/
├── crates/
│   ├── onlyalpha-kernel/          按职责独立构建的 Rust Kernel libraries
│   └── onlyalpha-*/               非 Kernel 的共享 Rust libraries
├── packages/
│   ├── backend/                  onlyalpha-backend：Application、存储、安全、Transport、子进程监督与启动
│   ├── frontend/                 onlyalpha-frontend：Shipping Web UI
│   └── onlyalpha-*/               迁移期间仍有消费者的 Python 参考执行环境与待迁移工具
├── src/onlyalpha/                 待逐模块退役的 Python 实现及必要算法 SDK 源码
├── plugs/onlyalpha-plugin-*/      concrete Provider、Market、Broker 与算法插件
├── contracts/                    版本化 Product 与跨进程协议
├── tests/                        独立向量、scenario、conformance 与 correctness proof
├── deploy/                       部署与生命周期配置
└── scripts/                      工程与 operator 工具
```

归属按职责判断：市场或 Provider 差异进入 Plugin/Adapter/Gateway；市场无关的交易语义进入对应 Kernel
library；可复用基础设施进入非 Kernel library；产品业务、存储、接口与进程组合进入 backend 内部模块；
正常人机交互进入 frontend。不得为每个 worker、源文件或假设中的扩展点创建独立包。

backend 与 frontend 是独立发行的产品包；Rust libraries 统一版本，插件独立版本。保留中的 Python 包不是
额外 worker 产品发行线。它们的资源归并与实现删除必须按实际消费者、admission 和恢复边界逐项完成，不能
通过移动目录宣称完成 Rust 迁移。OpenAPI 等正式 Contract 仍由根目录 `contracts/` 治理。

`backend/examples/` 中的算法桥接诊断和回测参考程序是技术验证入口，不属于 Shipping 用户操作界面，也不开放
正式 Backtest/worker admission。可复用 bridge 只接受显式通道、生命周期控制和恢复连接接口；解释器选择、
spawn、kill/wait、失败 owner 保留与容量释放由 `backend/src/workers/` 持有。

`backend/python/algorithms` 与 `backend/python/gateway_protocol` 是 backend 的内部 wheel 构建成分，不拥有
额外发行线。`src/onlyalpha/algorithm` 等纯数学 SDK 源码仍被参考环境和算法共同使用，保持单一源码；Shipping
安装只收录 `scripts/build_algorithm_sdk.py` 声明的最小闭包，不引入 Python Product/Trading 业务服务。
