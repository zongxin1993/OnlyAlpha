# user_data

所有非源码运行产物统一位于 user_data。根目录优先级：

```text
--user-data > ONLYALPHA_USER_DATA > <cwd>/user_data
```

正式运行写入 `user_data/runs/<engine_id>/<run_id>/`。缓存、状态、历史数据和临时能力后续也必须使用同一根布局，
不得写入 `src/`、`examples/` 或 `tests/`。绝对路径、run_id、PID 和墙钟耗时不得进入业务确定性指纹。
