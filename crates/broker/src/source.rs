//! 确定性模拟来源的原输入、经济钟和出生事实校验；不执行场所撮合。
use crate::{
    BrokerCommand, Error, Fact, Scope, digest,
    model::{err, integer},
};
use bigdecimal::num_bigint::BigInt;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar, time::OnlyTimestamp};
use serde_json::{Value, json};
use std::collections::BTreeMap;

/// 检查绑定来源介质保存的规范 JSON 原文，返回该原文的解析值。
pub fn decode_source_json(raw: &str) -> Result<Value, Error> {
    let parsed: Value = serde_json::from_str(raw)?;
    if raw.as_bytes() != serde_json::to_vec(&parsed)?.as_slice() {
        return Err(err("BROKER_SOURCE_NONCANONICAL_JSON"));
    }
    Ok(parsed)
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum QueryPhase {
    Discovery,
    Resolve,
}
impl QueryPhase {
    pub fn kind(self) -> &'static str {
        match self {
            Self::Discovery => "DISCOVERY",
            Self::Resolve => "RESOLVE",
        }
    }
    pub fn parse(kind: &str) -> Result<Self, Error> {
        match kind {
            "DISCOVERY" => Ok(Self::Discovery),
            "RESOLVE" => Ok(Self::Resolve),
            _ => Err(err("BROKER_SOURCE_QUERY_PHASE")),
        }
    }
}

/// 来源查询原 occurrence 同时绑定原场所前驱、协议前驱、阶段、结果及全部原事实。
pub fn source_query_id(
    phase: QueryPhase,
    source_head: &str,
    protocol_head: &str,
    d: &crate::Discovery,
) -> String {
    let mut facts = String::new();
    for fact in d.facts() {
        facts = digest(&json!([facts, fact.identity(), fact.fingerprint()]));
    }
    digest(&json!([
        "SIMULATION_QUERY_V2",
        phase.kind(),
        source_head,
        protocol_head,
        d.header(),
        facts
    ]))
}

/// 同一步按实际产生顺序累计原事实，避免将整组输出编码成单个 Broker record。
pub fn source_fact_link(previous: &str, fact: &Fact, stream_at: &Value) -> String {
    digest(&json!([
        previous,
        fact.identity(),
        fact.record(),
        stream_at
    ]))
}

pub fn source_step_digest(
    previous: &str,
    sequence: u64,
    input: &Value,
    facts: u64,
    outputs: &str,
    witness: Option<&str>,
) -> String {
    digest(&json!([
        "SIMULATION_SOURCE_STEP_V1",
        previous,
        sequence,
        input,
        facts,
        outputs,
        witness
    ]))
}

pub fn source_input_time(previous: &BigInt, scope: &Scope, input: &Value) -> Result<BigInt, Error> {
    let row = input.as_array().ok_or_else(|| err("BROKER_SOURCE_INPUT"))?;
    let at = match (row.first().and_then(Value::as_str), row.len()) {
        (Some("CLOCK"), 2) => integer(&row[1], false)?,
        (Some("BAR"), 3) => {
            if row[1].as_u64().is_none_or(|n| n == 0) {
                return Err(err("BROKER_SOURCE_BAR"));
            }
            let bar = OnlyBar::from_record(&row[2]).map_err(|_| err("BROKER_SOURCE_BAR"))?;
            if !bar.is_closed() {
                return Err(err("BROKER_SOURCE_BAR"));
            }
            OnlyTimestamp::from_datetime(*bar.ts_event()).to_unix_nanos()
        }
        (Some("COMMAND" | "NOT_READY"), 2) => {
            if BrokerCommand::decode(&row[1])?.scope() != scope {
                return Err(err("BROKER_SOURCE_SCOPE"));
            }
            previous.clone()
        }
        (Some("PUBLISHED"), 3) => {
            crate::model::id(&row[1])?;
            crate::model::fp(&row[2])?;
            previous.clone()
        }
        _ => return Err(err("BROKER_SOURCE_INPUT")),
    };
    if &at < previous {
        return Err(err("BROKER_SOURCE_TIME_REGRESSION"));
    }
    Ok(at)
}

pub fn check_admission_clock(
    scope: &Scope,
    latest_clock_input: &Value,
    admitted: &Value,
) -> Result<(), Error> {
    let now = source_input_time(&0.into(), scope, latest_clock_input)?;
    if now < integer(admitted, false)? {
        return Err(err("BROKER_SOURCE_CLOCK_BEFORE_ADMISSION"));
    }
    Ok(())
}
/// 连续来源步的纯校验数据。正式执行由持有原 Run 的 Runtime 重新读取原件确认。
pub struct SourceStep<'a> {
    pub sequence: u64,
    pub previous: &'a str,
    pub input: &'a Value,
    pub fact_count: u64,
    pub hash: &'a str,
    pub protocol_hash: Option<&'a str>,
}
pub struct SourceHistory {
    scope: Scope,
    binding: String,
    head: String,
    sequence: u64,
    now: BigInt,
    visible_at: BigInt,
    boundary: Option<(BigInt, BigInt)>,
    closure: Option<Value>,
    boundary_trades: BTreeMap<String, String>,
    first_observations: std::collections::BTreeSet<String>,
    observation_after_visibility: bool,
}

impl SourceHistory {
    pub fn new(
        scope: Scope,
        binding: &Value,
        expected: &str,
        boundary: Option<(u64, u64)>,
    ) -> Result<Self, Error> {
        let actual = digest(binding);
        if actual != expected
            || binding["scope"] != scope.record()
            || scope.record()["runtime_kind"] != "BACKTEST"
        {
            return Err(err("BROKER_SOURCE_GENESIS"));
        }
        Ok(Self {
            scope,
            binding: actual.clone(),
            head: actual,
            sequence: 0,
            now: 0.into(),
            visible_at: 0.into(),
            boundary: boundary.map(|(at, visible)| (at.into(), visible.into())),
            closure: None,
            boundary_trades: BTreeMap::new(),
            first_observations: Default::default(),
            observation_after_visibility: false,
        })
    }

    pub fn check_admission(&self, admitted: &Value) -> Result<(), Error> {
        if self.now < integer(admitted, false)? {
            return Err(err("BROKER_SOURCE_CLOCK_BEFORE_ADMISSION"));
        }
        Ok(())
    }
    pub fn accept_step<I>(&mut self, step: SourceStep<'_>, facts: I) -> Result<(), Error>
    where
        I: IntoIterator<Item = Result<(Fact, Value), Error>>,
    {
        let SourceStep {
            sequence,
            previous,
            input,
            fact_count: expected_count,
            hash: expected_hash,
            protocol_hash: witness,
        } = step;
        if self.sequence.checked_add(1) != Some(sequence) || previous != self.head {
            return Err(err("BROKER_SOURCE_PREDECESSOR"));
        }
        let now = source_input_time(&self.now, &self.scope, input)?;
        let birth_visibility = if input[0] == "BAR" {
            let bar = OnlyBar::from_record(&input[2]).map_err(|_| err("BROKER_SOURCE_BAR"))?;
            OnlyTimestamp::from_datetime(*bar.ts_init()).to_unix_nanos()
        } else {
            now.clone()
        };
        let visible_at = self.visible_at.clone().max(birth_visibility);
        let mut outputs = String::new();
        let mut count = 0u64;
        let mut born = Vec::new();
        for found in facts {
            let (fact, stream_at) = found?;
            let raw = fact.record();
            if fact.scope() != self.scope
                || integer(&raw["ts_event"], false)? != now
                || integer(&stream_at, false)? < now
            {
                return Err(err("BROKER_SOURCE_BIRTH"));
            }
            count = count
                .checked_add(1)
                .ok_or_else(|| err("BROKER_SOURCE_COUNT"))?;
            outputs = source_fact_link(&outputs, &fact, &stream_at);
            if raw["kind"] == "TRADE" && self.boundary.as_ref().is_some_and(|(at, _)| &now <= at) {
                born.push((fact.identity().to_owned(), digest(&raw)));
            }
        }
        let actual = source_step_digest(previous, sequence, input, count, &outputs, witness);
        if count != expected_count || actual != expected_hash {
            return Err(err("BROKER_SOURCE_STEP_DIGEST"));
        }
        for (id, fp) in born {
            if self.boundary_trades.insert(id, fp).is_some() {
                return Err(err("BROKER_SOURCE_DUPLICATE_BIRTH"));
            }
        }
        if let Some((boundary, visible)) = &self.boundary {
            let through = &now - BigInt::from(1);
            if self.closure.is_none() && &through >= boundary && &visible_at <= visible {
                self.closure = Some(
                    json!({"schema_version":1,"source_binding":self.binding,"sequence":sequence,"hash":actual,"visible_at_ns":serde_json::from_str::<Value>(&visible_at.to_string())?,"clock_ns":serde_json::from_str::<Value>(&now.to_string())?,"economic_through_ns":serde_json::from_str::<Value>(&through.to_string())?}),
                );
            }
        }
        self.sequence = sequence;
        self.head = actual;
        self.now = now;
        self.visible_at = visible_at;
        Ok(())
    }
    pub fn observe(&mut self, fact: &Fact) -> Result<(), Error> {
        if let Some(original) = self.boundary_trades.get(fact.identity()) {
            if *original != digest(&fact.record()) {
                return Err(err("BROKER_SOURCE_ORIGINAL_FACT_REQUIRED"));
            }
            if self.first_observations.insert(fact.identity().into())
                && self
                    .boundary
                    .as_ref()
                    .is_some_and(|(_, visible)| self.visible_at > *visible)
            {
                self.observation_after_visibility = true;
            }
        }
        Ok(())
    }
    pub fn funding_closure(
        &self,
        binding: &str,
        boundary: u64,
        visible: u64,
    ) -> Result<(&Value, &BTreeMap<String, String>), Error> {
        if binding != self.binding || self.boundary != Some((boundary.into(), visible.into())) {
            return Err(err("BROKER_SOURCE_BOUNDARY"));
        }
        if self.observation_after_visibility {
            return Err(err("BROKER_SOURCE_OBSERVATION_NOT_VISIBLE"));
        }
        Ok((
            self.closure
                .as_ref()
                .ok_or_else(|| err("BROKER_ECONOMIC_PREFIX_UNPROVEN"))?,
            &self.boundary_trades,
        ))
    }
}
