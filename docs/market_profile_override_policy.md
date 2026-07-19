# Market Profile Override Policy

普通 Override 允许：流动性最大参与率、滑点 model/value/ticks、撮合 model、strict。默认拒绝其他 leaf path，包括 settlement、position mode、short selling、margin 和制度性 price/quantity 规则。

需要改变制度时注册 Custom Profile，不通过宽松字典绕过。Override 经规范 JSON 生成指纹并进入 resolved rules fingerprint。

