# Position Demo

- `account_position_demo.py`：账户 Average Cost；
- `multi_cluster_allocation_demo.py`：Cluster 独立成本；
- `t1_settlement_demo.py`：SETTLED/UNSETTLED 迁移；
- `position_reservation_demo.py`：卖出预占；
- `broker_reconciliation_demo.py`：券商总量冲突与阻断；
- `unallocated_position_demo.py`：未知归属进入 Unallocated；
- `deterministic_replay_demo.py`：100 次重放一致。

在项目根目录执行：

```bash
UV_CACHE_DIR=/tmp/onlyalpha-uv-cache uv run python examples/position_demo/account_position_demo.py
```
