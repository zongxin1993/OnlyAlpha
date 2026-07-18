# OnlyAlpha-plugins MiniQMT 插件实现任务

## 任务目标

当前工作区：

```
OnlyAlpha/
OnlyAlpha-plugins/
```

实现 OnlyAlpha 官方插件仓库中的 MiniQMT 插件。

目标：

```
OnlyAlpha
    |
    | Plugin SPI
    |
OnlyAlpha-plugins
    |
    |
    +── DataSource: miniqmt
    |
    +── Broker: miniqmt
```

MiniQMT 同时提供：

```
1. 市场数据能力
2. 交易能力
3. 合约信息
4. 交易日历
5. 账户同步
```

实现参考：

第一参考：

```
https://github.com/vnpy/vnpy_xt
```

第二参考：

```
https://dict.thinktrader.net/nativeApi/start_now.html
```

原则：

* `vnpy_xt` 是主要实现参考
* 官方文档用于 API 参数、函数语义和版本确认
* 不复制 vnpy 架构
* 不引入 VeighNa EventEngine
* 不引入 VeighNa Gateway 模型
* 按 OnlyAlpha Plugin SPI 重新实现

---

# 一、核心架构要求

## 1. 插件唯一 ID

严格使用：

```
DataSource:
    miniqmt

Broker:
    miniqmt
```

禁止：

```
xtquant
xtdata
xttrader
qmt
thinktrade
xuntou
miniqmt-data
miniqmt-trader
```

等别名。

原因：

MiniQMT 是完整交易环境，而 XtQuant 是内部 SDK。

OnlyAlpha 面向的是：

```
数据来源
交易来源
```

不是供应商 SDK。

---

# 二、依赖方向

必须：

```
OnlyAlpha-plugins
        |
        v
OnlyAlpha
```

禁止：

```
OnlyAlpha
        |
        v
OnlyAlpha-plugins
```

OnlyAlpha 核心禁止出现：

```
xtquant
XtQuantTrader
xtdata
MiniQMT
QMT
国金证券
userdata_mini
```

任何特殊逻辑。

---

# 三、主要参考 vnpy_xt

重点阅读：

```
vnpy_xt/xt_gateway.py
vnpy_xt/xt_datafeed.py
vnpy_xt/xt_constant.py
```

重点学习：

## 行情

参考：

```
XtData
XtData API
subscribe_quote
get_market_data_ex
get_instrument_detail
download_history_data
```

学习：

```
连接流程
行情订阅
Tick转换
Bar转换
合约转换
交易日历
```

---

## 交易

参考：

```
XtQuantTrader
XtQuantTraderCallback
```

学习：

```
connect
subscribe
order_stock_async
cancel_order_stock_async

on_stock_order
on_stock_trade
on_stock_position
on_stock_asset
```

重点参考：

```
vnpy_xt
对于订单状态
交易方向
价格类型
成交回报
ID映射
```

---

# 四、公共 API 边界检查

开始编码前必须检查：

OnlyAlpha：

```
src/onlyalpha/plugin
src/onlyalpha/data
src/onlyalpha/broker
src/onlyalpha/execution
src/onlyalpha/domain
```

确认：

```
OnlyDataSource
OnlyDataSourceFactory
OnlyBrokerGateway
OnlyBrokerFactory
OnlyBrokerInboundQueue
```

是否满足：

DataSource：

```
历史行情
实时行情
合约
交易日历
```

Broker：

```
订单
撤单
账户
持仓
成交
委托
```

如果不足：

必须修改唯一正式 SPI。

禁止：

```
增加 XTQuant 专用接口
增加 MiniQMT 特殊接口
增加兼容旧接口
增加 Adapter 层保持旧调用
```

---

# 五、OnlyAlpha-plugins 工程结构

建立：

```
OnlyAlpha-plugins

├── AGENTS.md
├── README.md
├── pyproject.toml
│
├── packages
│   |
│   └── onlyalpha-plugin-miniqmt
│       |
│       ├── src
│       │   |
│       │   └── onlyalpha_plugin_miniqmt
│       │
│       │       ├── descriptor.py
│       │       ├── config.py
│       │       ├── errors.py
│       │       ├── lifecycle.py
│       │
│       │       ├── sdk
│       │       │   |
│       │       │   ├── loader.py
│       │       │   ├── protocols.py
│       │       │   ├── xtdata_client.py
│       │       │   └── xttrader_client.py
│       │
│       │       ├── mapping
│       │       │   |
│       │       │   ├── instrument.py
│       │       │   ├── exchange.py
│       │       │   ├── order.py
│       │       │   ├── status.py
│       │       │   └── market_data.py
│       │
│       │       ├── data_source
│       │       │   |
│       │       │   ├── factory.py
│       │       │   ├── resource.py
│       │       │   ├── historical.py
│       │       │   └── live.py
│       │
│       │       └── broker
│       │           |
│       │           ├── factory.py
│       │           ├── gateway.py
│       │           └── callback.py
│       |
│       └── tests
│
└── docs
```

---

# 六、Entry Point

pyproject.toml:

```toml
[project.entry-points."onlyalpha.data_sources"]

miniqmt =
"onlyalpha_plugin_miniqmt.data_source.factory:factory"



[project.entry-points."onlyalpha.brokers"]

miniqmt =
"onlyalpha_plugin_miniqmt.broker.factory:factory"
```

最终发现：

```
DATA_SOURCE:
    miniqmt


BROKER:
    miniqmt
```

---

# 七、MiniQMT 默认路径

默认：

Windows:

```
C:\国金证券QMT交易端\userdata_mini
```

配置字段：

唯一：

```
userdata_mini_path
```

例如：

```yaml
data_sources:

  - source_id: miniqmt-main

    plugin: miniqmt

    extensions:

      userdata_mini_path:
        "C:\\国金证券QMT交易端\\userdata_mini"



brokers:

  - gateway_id: miniqmt-main

    plugin: miniqmt

    extensions:

      userdata_mini_path:
        "C:\\国金证券QMT交易端\\userdata_mini"
```

规则：

如果用户没有配置：

自动使用：

```
C:\国金证券QMT交易端\userdata_mini
```

如果配置存在：

优先使用配置。

如果路径不存在：

失败：

```
MINIQMT_PATH_NOT_FOUND
```

禁止自动搜索：

```
D:
E:
桌面
安装目录
其他 userdata
```

---

# 八、SDK 加载

禁止：

模块 import 时：

```python
import xtquant
```

必须：

运行阶段：

```
Factory.create()

      |
      v

SDK Loader

      |
      v

xtquant import
```

错误：

```
XTQUANT_SDK_NOT_INSTALLED
XTQUANT_IMPORT_FAILED
```

必须结构化返回。

---

# 九、DataSource 实现

Plugin:

```
miniqmt
```

提供：

## 历史行情

主要参考：

vnpy_xt:

```
get_market_data_ex
download_history_data
```

支持：

```
1m
5m
15m
30m
1h
1d
```

输出：

```
OnlyBar
```

要求：

```
UTC 时间
稳定排序
重复过滤
非法 OHLC 拒绝
```

---

## 实时行情

支持：

```
subscribe_quote
```

实现：

```
subscribe_tick
subscribe_bar
unsubscribe
```

流程：

```
XtData Callback

       |

       v

MiniQMT Adapter

       |

       v

OnlyAlpha MarketData Port

       |

       v

Runtime
```

禁止：

```
Callback
直接调用 Strategy
直接修改 Runtime
```

---

## 合约信息

参考：

```
get_instrument_detail
```

支持：

```
股票
ETF
指数
可转债
```

转换：

```
OnlyInstrument
```

---

## 交易日历

参考：

```
get_trading_calendar
get_trading_time
```

转换：

```
OnlyTradingCalendar
```

正确处理：

```
Asia/Shanghai
上午交易
午休
下午交易
节假日
```

---

# 十、Broker 实现

Plugin:

```
miniqmt
```

实现：

```
OnlyBrokerGateway
```

初始化：

```
检查 userdata_mini_path

        |

加载 SDK

        |

XtQuantTrader()

        |

register_callback()

        |

start()

        |

connect()

        |

subscribe(account)

        |

同步账户状态

```

---

# 十一、账户

支持：

```
STOCK
```

查询：

```
asset
position
order
trade
```

转换：

```
OnlyAccount
OnlyPosition
OnlyOrder
OnlyTrade
```

---

# 十二、订单

第一阶段：

支持：

```
限价买
限价卖
撤单
```

接口：

```
order_stock_async

cancel_order_stock_async
```

---

# 十三、订单映射

必须实现：

## Direction

```
BUY
SELL
```

## PriceType

```
LIMIT
```

## Status

参考：

vnpy_xt：

```
NOTTRADED
PARTTRADED
ALLTRADED
CANCELLED
REJECTED
```

转换：

OnlyAlpha:

```
SUBMITTING
ACCEPTED
PARTIALLY_FILLED
FILLED
CANCELLED
REJECTED
```

---

# 十四、订单 ID

必须维护：

```
OnlyAlpha client_order_id

        |

        |

Xt order_id

        |

        |

Xt order_sysid
```

推荐：

```
order_remark_prefix:client_order_id
```

保证：

```
可反查
唯一
稳定
```

---

# 十五、交易回调

实现：

```
on_connected

on_disconnected

on_stock_asset

on_stock_order

on_stock_trade

on_stock_position

on_order_error

on_cancel_error
```

回调线程：

只能：

```
转换
去重
入队
```

不能：

```
修改Position
修改Ledger
调用Strategy
```

---

# 十六、断线重连

状态：

```
CONNECTED

DISCONNECTED

RECONNECTING

FAILED
```

要求：

```
单一重连线程
指数退避
最大次数
stop 后不重连
重新订阅账户
重新同步状态
```

---

# 十七、测试

必须支持：

无 MiniQMT 环境：

```
Fake XtData
Fake XtTrader
```

测试：

## DataSource

```
配置
路径
连接
历史行情
实时订阅
合约
交易日历
```

## Broker

```
连接
账户
下单
撤单
成交
持仓
断线
重连
```

---

# 十八、真实环境工具

提供：

```bash
onlyalpha-miniqmt doctor
```

检查：

```
xtquant
userdata_mini
MiniQMT连接
账户
行情
交易接口
```

默认路径：

```
C:\国金证券QMT交易端\userdata_mini
```

---

# 十九、验收标准

必须：

```
OnlyAlpha 无 MiniQMT 特判

OnlyAlpha-plugins 独立安装

插件 ID:
    miniqmt

DataSource:
    miniqmt

Broker:
    miniqmt

支持历史行情

支持实时行情

支持合约

支持交易日历

支持账户查询

支持持仓查询

支持订单查询

支持成交查询

支持限价买卖

支持撤单

支持回调

支持重连

支持 Fake SDK

CI 不依赖 QMT

不存在兼容层

不存在第二套接口
```

---

# 二十、最终报告

生成：

```
OnlyAlpha-plugins/docs/reports/miniqmt_plugin_implementation_report.md
```

包含：

```
vnpy_xt参考内容

官方文档差异

SPI修改

插件结构

配置设计

默认路径设计

行情实现

交易实现

订单映射

状态映射

线程模型

重连模型

测试结果

真实环境验证方法

已支持能力

未支持能力
```

最终状态：

```
ACCEPTED
```

或：

```
REJECTED
```

禁止只提交设计文档，必须完成代码、测试、插件发现和验证工具。
