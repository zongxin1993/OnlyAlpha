# OnlyAlpha MiniQMT Plugin

MiniQMT 的历史行情与 Broker Adapter，通过 OnlyAlpha 公共 DataSource/Broker SPI 接入。插件负责 SDK 加载、供应商字段校验、
证券代码映射和时间语义转换；Core 不依赖 `xtquant`。

MiniQMT 日线原始时间戳表示 Asia/Shanghai 的交易日零点，并不是可直接发布的 Bar 时间。Adapter 将日线规范化为该交易日
09:30 开始、15:00 结束，再转为 UTC；历史和实时分钟 K 线的供应商时间戳均表示 Bar 结束边界，Adapter 按周期反推开始边界。

真实 QMT 查询属于 Windows 本地外部测试，默认离线测试使用 Fake SDK 合同和已提交的只读 Golden Dataset。插件不会在导入
阶段访问网络，也不会自动提交真实订单。
