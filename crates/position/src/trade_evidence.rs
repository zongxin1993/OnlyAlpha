//! 由已应用的真实 Position 成交签发，供两个经济投影核对同一笔原输入。
use crate::{Manager, Status, model::*};
use serde_json::{Value, json};

/// 只能从 Position 的原成交 Journal 取得；配置与规范原交易指令共同决定身份。
pub struct TradeEvidence {
    configuration: String,
    command: Value,
    account: String,
    allocation: String,
    notional: Decimal,
}

impl TradeEvidence {
    /// 核对消费者收到的原命令关联和该笔成交的实际投影，返回已验证的紧凑身份。
    pub fn verify_projection(
        &self,
        config: &Value,
        command: &Value,
        ledger: bool,
    ) -> Result<&str, Error> {
        let p = &command["payload"];
        let original = &self.command;
        let trade = &original["payload"];
        let (sequence, result) = if ledger {
            ("source_sequence", "allocation_evidence")
        } else {
            ("sequence", "position_evidence")
        };
        let expected_result = if ledger {
            self.allocation.as_str()
        } else {
            self.account.as_str()
        };
        if config["position_configuration"] != self.configuration
            || command["op"] != "TRADE"
            || [
                "engine",
                "runtime",
                "account",
                "generation",
                "time",
                "cause",
            ]
            .iter()
            .any(|k| command[*k] != original[*k])
            || [
                "order",
                "trade",
                "venue_trade",
                "execution",
                "side",
                "terminal_fill",
            ]
            .iter()
            .any(|k| p[*k] != trade[*k])
            || p[sequence] != trade["sequence"]
            || decimal(&p["notional"])? != self.notional
            || decimal(&p["charges"])? != decimal(&trade["fee"])?
            || decimal(&p["rebates"])? != decimal(&trade["rebates"])?
            || p[result] != expected_result
            || (ledger
                && (command["cluster"] != trade["cluster"]
                    || p["instrument"] != trade["instrument"]))
            || (!ledger && command["gateway"] != original["gateway"])
        {
            return Err(err("POSITION_TRADE_PROJECTION_RELATION"));
        }
        text(&trade["trade_evidence"])
    }
}

impl Manager {
    /// 根据实际规范 TRADE 原文生成输入身份。校验或恢复同样重新计算；签发投影证据还须实际应用成功。
    pub fn trade_input_digest(&self, command: &Value) -> Result<String, Error> {
        if self.config.get("funding_rules").is_none()
            || command["op"] != "TRADE"
            || command["payload"]["schema_version"] != 3
        {
            return Err(err("POSITION_TRADE_EVIDENCE_PROFILE"));
        }
        let mut payload = command["payload"].clone();
        payload
            .as_object_mut()
            .ok_or_else(|| err("POSITION_TRADE_SCHEMA"))?
            .remove("trade_evidence");
        Ok(hash(&json!([
            "POSITION_PERPETUAL_TRADE_V1",
            hash(&self.config),
            command["cause"],
            command["time"],
            payload
        ])))
    }

    /// 从正式 Journal 重放到首次已应用的指定成交，保留该时刻账户与分配结果。
    pub fn trade_evidence(&self, trade: &str) -> Result<TradeEvidence, Error> {
        let mut replay = Self::new(self.config.clone())?;
        for command in &self.state.journal {
            let outcome = replay.apply(command)?;
            let p = &command["payload"];
            if command["op"] == "TRADE" && p["trade"] == trade && outcome.status == Status::Applied
            {
                if p["schema_version"] != 3 {
                    return Err(err("POSITION_TRADE_EVIDENCE_PROFILE"));
                }
                let fact = outcome
                    .fact
                    .ok_or_else(|| err("POSITION_FUNDING_TRADE_FACT"))?;
                let allocation = replay.cluster(text(&p["cluster"])?, text(&p["instrument"])?)?;
                let notional = (positive(&p["quantity"])?
                    * positive(&p["price"])?
                    * &self.spec(text(&p["instrument"])?)?.multiplier)
                    .with_scale_round(
                        i64::from(self.currency.precision()),
                        bigdecimal::RoundingMode::HalfEven,
                    );
                return Ok(TradeEvidence {
                    notional,
                    configuration: hash(&self.config),
                    command: command.clone(),
                    account: hash(&fact["details"]["account"]),
                    allocation: hash(&allocation),
                });
            }
        }
        Err(err("POSITION_APPLIED_TRADE_EVIDENCE_MISSING"))
    }
}
