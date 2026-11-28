# 一次构建的因子程序

> **历史实现。** 本文记录原 Backend 的受限 Python AST 构建、精确参数认证和数值语义。该产品路径已退役。现行基础库通过 [`FactorExpr::compile`](../crates/calculation/src/factor_expr/mod.rs) 将声明式表达式编译为类型化算子 DAG，供向量或事件内核执行。因子与研究标签的边界见 [ADR 0152](adr/0152-unified-runtime-dual-kernel-operators-qlib-dag-and-wasm-plugins.md)。

## 职责与身份

受限的 `calculate(api, inputs, parameters)` 是声明式编写入口。隔离编译器仅解析 AST 并生成数据，不执行用户 Python 字节码。一个构建身份绑定精确源码、API 与输入／参数／输出契约、sealed SDK 构建器、原语／数值工件。相同程序的新参数只做解析、绑定与精确认证，不重新解析源码。算法执行仅消费 Rust `BoundProgram`，不携带源文件读取能力。程序 JSON 的 decode 与 Python AST 解析是两个不同操作。

`FactorBuildService::request` 记录幂等构建意图；默认参数在不可变版本 INSERT 时自动请求。后台构建在独立普通 PG builder 连接消费现有队列，不新增 Run／Attempt authority。构建事务持有队列行和构建身份 advisory lock，防止多个版本同时重复编译同一程序；构建／认证有明确输入、进程、数值工作与时间预算。这是有限构建事务，不覆盖后续 Research 行情处理。

合法程序与参数证书分别发布。某组参数失败保留合法不可变程序；不发布证书，不授予 READY。未知数据库结果保持未知，由原请求观察，不能记为确定失败后盲重建。`resolve_ready_binding` 检查版本、源码、程序、精确参数、构建／认证工件、case suite、证据和正式关联；缺失、错关联、读取不可用都不提供绑定。规范化等值参数可复用同一证书，A 证书不能认证 B，也不认证整个参数域。

## 编写范围与数值

只允许静态输入／参数引用、局部标量赋值、白名单 api 调用和最终固定输出字典；不允许 import、while、用户 helper、可变容器、外部 IO、未来 Target 或交易账户输入。源码 64 KiB、AST 4096 节点、深度 64、指令 1024；program 1 MiB、输入／输出各 128，窗口最大 100000、总窗口状态一百万单元。精确认证按实际组合进一步限制 rows≤4096、原语工作≤2000000、输入单元≤1000000，超限结构化拒绝，不调整结果或绕过校验。

Rust 负责 DECIMAL28_HALF_EVEN_Q12_V1，复用 operators；不是资金／数量精度。整数输入拒绝小数，输入／参数／整数字面量及 where、coalesce、整数 min/max 保留 INTEGER 类型和精确整数值；普通数学／窗口结果为 DECIMAL。编译器按声明的 DECIMAL 输出插入显式 `to_decimal` 指令，只允许提升，不能把小数静默截断为整数。INTEGER 输出不补 q12 小数位，DECIMAL 输出遵循 q12；二者仍受数值资源预算。精确参数在绑定时解析一次。除零产生缺值，窗口 warmup 与 null、逻辑三值规则沿用声明规范。`None` 字面量默认为数值缺值；布尔缺值通过声明 BOOLEAN 的可空输入表达。布尔与数值不能混用。只接受精确整数／十进制字符串，不接受 Python float。输入只依赖行情、因子、显式参数。

## 认证与执行

认证使用受控输入，不读取未来收益或真实行情：独立数值 golden、每点 batch/event 相等、多个前缀的因果性、null／warmup、checkpoint 恢复后缀及独立实例。两条执行路径共享 Rust 程序与原语，不通过放宽容差判断一致。受控测试证明明确 case suite，不等于科学有效性或正式交易准入。

`ProgramInstance` 只服务一个 instrument／连续 sequence；不同 Run/instrument 创建不同实例，窗口不共享。每 step 先构造完整候选，成功才推进。快照绑定精确程序和参数，恢复检查 schema、位置、窗口长度，不能借另一参数或程序的状态。

## 历史产品接线

原 Backend 通过 `research_preparation.prepare_strategy → _prepare_factor` 读取源码认证结果。直接执行旧源码会返回 `PRIVATE_FACTOR_NATIVE_BUILD_REQUIRED` 或 `PRIVATE_FACTOR_NATIVE_PROGRAM_REQUIRED`。原 PostgreSQL builder、Python 编译器测试及 Backend 作业验证入口均已随原宿主退役。

现行声明式示例按来源和因子集收录在[因子示例目录](../examples/factor/)。仓库通过[单元测试入口](../scripts/unit_tests.py)验证 Rust 库的模块自测。
