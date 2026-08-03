# PR5.1.3 Paper Real Product Acceptance Report

执行日期：2026-08-03（Asia/Shanghai）

## AUTOMATED RESULTS

```text
Automated Contract : PASS
Acceptance tests   : 15 passed
Related offline    : 62 passed
Full offline gate  : 1267 passed
```

自动化覆盖 Verdict、Evidence JSON、脱敏、原子 Artifact、正式 Engine 历史纵切面、Historical Worker 失败分类、Observation、经济隔离和有序 Shutdown。自动化结果不替代真实环境结果。

## REAL ENVIRONMENT RESULTS

冻结环境：

```text
Platform              : Windows 11
Python                : 3.12.12
OnlyAlpha             : 0.3.3
MiniQMT Plugin        : 0.3.3
XtQuant               : 250807.1.2
Runtime               : PAPER
Execution Capability  : SHADOW
Instrument            : 000001.XSHE / 000001.SZ
External / Internal   : 1m / 3m
Historical Profile    : miniqmt-history-v2
Historical Protocol   : 2
Time Semantics        : 2
Cache Policy          : force_refresh
Real Broker           : disabled
Working Tree          : dirty (PR5.1.3 implementation under acceptance)
```

真实 Historical Snapshot：PASS。

```text
Preflight                     : PASS
Core / Plugin Version         : PASS (0.3.3 / 0.3.3)
Historical Worker             : PASS
Pipeline-processed Bars       : 51 (required >= 50)
Historical Watermark          : PASS (1)
Historical Observation        : PASS
MACD Ready                    : PASS
Required Factor Snapshot      : PASS
Cash                          : unchanged (1000000.00)
Position / Fill / Fee         : 0 / 0 / 0
Settlement                    : 0
Active Reservations           : 0
Active Subscriptions at Stop  : 0
Streaming Worker at Stop      : stopped
Observation Publisher Pending : 0
Runtime Final State           : CLOSED
```

最终真实 Historical Artifact：

```text
user_data/acceptance/paper/paper-acceptance-20260803T082951Z-4b3de9769b9a/
```

## NOT EXECUTED RESULTS

执行 Live Gate 前只读检查得到：

```text
Observed At          : 2026-08-03 16:24 Asia/Shanghai
Market Session State : POST_CLOSE
Live Handoff         : NOT_EXECUTED
Reason               : MARKET_SESSION_NOT_OPEN
```

未连接、等待或修改实时数据，未因休市重复测试。Live 判定 Artifact：

```text
user_data/acceptance/paper/paper-acceptance-20260803T082449Z-f23c42e53840/
```

## KNOWN EXTERNAL LIMITATIONS

```text
Streaming Reconnect         : NOT IMPLEMENTED
Gap Recovery                : NOT IMPLEMENTED
Streaming Recovery          : NOT IMPLEMENTED
Broad MiniQMT Compatibility : PARTIAL
Live Runtime                : NOT IMPLEMENTED
```

## VERDICT

```text
Automated Contract                 : PASS
Real Historical Snapshot           : PASS
Real Historical Economic Isolation : PASS
Real Ordered Shutdown              : PASS
Real Live Handoff                  : NOT_EXECUTED

PR5.1 Read-Only Observation Scope  : NOT_EXECUTED
Production Paper Runtime           : PARTIAL
```

由于真实 Live Handoff 未执行，本报告不把 README、Paper Runtime、Roadmap 或 AGENTS 状态更新为 CURRENT SCOPE ACCEPTED。
