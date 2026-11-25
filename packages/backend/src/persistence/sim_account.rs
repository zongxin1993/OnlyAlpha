use crate::{
    application::{command, integration_configuration::IntegrationId},
    bootstrap::deployment::{self, SemanticStoreId},
    persistence::{authority_session::AuthoritySession, integration_postgres::VIRTUAL_BROKER_TYPE_ID, postgres},
};
use bigdecimal::BigDecimal;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    identifiers::{OnlyAccountId, OnlyIdentifier, OnlyInstrumentId},
    value::OnlyMoney,
};
use onlyalpha_execution::{Components, digest};
use onlyalpha_runtime::{RunConfiguration, durability::TradingBinding};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
use tokio_postgres::Transaction;

pub(crate) const SIM_ENGINE_ID: &str = "onlyalpha-sim";
pub(crate) const SIM_CLUSTER_ID: &str = "strategy";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Error {
    Invalid,
    Missing,
    Mismatch,
    Unavailable,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct InstrumentPolicy {
    id: OnlyInstrumentId,
    price_precision: u8,
    quantity_precision: u8,
    multiplier: String,
}

impl InstrumentPolicy {
    pub(crate) fn new(
        id: OnlyInstrumentId,
        price_precision: u8,
        quantity_precision: u8,
        multiplier: &str,
    ) -> Result<Self, Error> {
        let text = id.to_string();
        if text.contains('\0')
            || !matches!(OnlyIdentifier::new(&text), Ok(ref parsed) if parsed.value() == text)
            || !matches!(text.parse::<OnlyInstrumentId>(), Ok(ref parsed) if parsed.to_string() == text)
            || price_precision > 18
            || quantity_precision > 18
            || multiplier != "1"
        {
            return Err(Error::Invalid);
        }
        Ok(Self {
            id,
            price_precision,
            quantity_precision,
            multiplier: multiplier.to_owned(),
        })
    }

    pub(crate) fn id(&self) -> &OnlyInstrumentId {
        &self.id
    }

    pub(crate) fn price_precision(&self) -> u8 {
        self.price_precision
    }

    pub(crate) fn quantity_precision(&self) -> u8 {
        self.quantity_precision
    }

    pub(crate) fn multiplier(&self) -> &str {
        &self.multiplier
    }

    pub(crate) fn to_record(&self) -> Value {
        json!({
            "schema_version": 1,
            "id": self.id.to_string(),
            "price_precision": self.price_precision,
            "quantity_precision": self.quantity_precision,
            "multiplier": self.multiplier,
        })
    }

    fn from_record(value: &Value) -> Result<Self, Error> {
        let object = value.as_object().ok_or(Error::Invalid)?;
        if object.len() != 5 || object.get("schema_version").and_then(Value::as_u64) != Some(1) {
            return Err(Error::Invalid);
        }
        let raw_id = object.get("id").and_then(Value::as_str).ok_or(Error::Invalid)?;
        let id: OnlyInstrumentId = raw_id.parse().map_err(|_| Error::Invalid)?;
        if id.to_string() != raw_id {
            return Err(Error::Invalid);
        }
        let price_precision = object
            .get("price_precision")
            .and_then(Value::as_u64)
            .and_then(|v| u8::try_from(v).ok())
            .ok_or(Error::Invalid)?;
        let quantity_precision = object
            .get("quantity_precision")
            .and_then(Value::as_u64)
            .and_then(|v| u8::try_from(v).ok())
            .ok_or(Error::Invalid)?;
        let multiplier = object.get("multiplier").and_then(Value::as_str).ok_or(Error::Invalid)?;
        Self::new(id, price_precision, quantity_precision, multiplier)
    }
}

/// 显式 operator 交易配置：绑定允许标的、精度/multiplier 及非空风控规则（禁止默认空风控）。
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct TradingPolicy {
    instruments: Vec<InstrumentPolicy>,
    risk_rules: Vec<Value>,
}

impl TradingPolicy {
    pub(crate) fn new(
        instruments: Vec<InstrumentPolicy>,
        risk_rules: Vec<Value>,
    ) -> Result<Self, Error> {
        if instruments.is_empty()
            || instruments.len() > 32
            || risk_rules.is_empty()
            || risk_rules.len() > 64
        {
            return Err(Error::Invalid);
        }
        let mut by_id = BTreeMap::new();
        for instrument in instruments {
            let key = instrument.id.to_string();
            if by_id.insert(key, instrument).is_some() {
                return Err(Error::Invalid);
            }
        }
        for rule in &risk_rules {
            precheck_risk_rule(rule)?;
        }
        if !risk_rules
            .iter()
            .any(|rule| rule.get("mode").and_then(Value::as_str) == Some("ENFORCING"))
        {
            return Err(Error::Invalid);
        }
        Ok(Self {
            instruments: by_id.into_values().collect(),
            risk_rules,
        })
    }

    pub(crate) fn instruments(&self) -> &[InstrumentPolicy] {
        &self.instruments
    }

    pub(crate) fn risk_rules(&self) -> &[Value] {
        &self.risk_rules
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct SimAccountRevision {
    deployment_id: SemanticStoreId,
    account_id: OnlyAccountId,
    opening_cash: OnlyMoney,
    broker_integration_id: IntegrationId,
    policy: TradingPolicy,
    revision_fingerprint: String,
}

impl SimAccountRevision {
    pub(crate) fn deployment_id(&self) -> &SemanticStoreId {
        &self.deployment_id
    }
    pub(crate) fn account_id(&self) -> &OnlyAccountId {
        &self.account_id
    }
    pub(crate) fn opening_cash(&self) -> &OnlyMoney {
        &self.opening_cash
    }
    pub(crate) fn broker_integration_id(&self) -> &IntegrationId {
        &self.broker_integration_id
    }
    pub(crate) fn instruments(&self) -> &[InstrumentPolicy] {
        self.policy.instruments()
    }
    pub(crate) fn risk_rules(&self) -> &[Value] {
        self.policy.risk_rules()
    }
    pub(crate) fn policy(&self) -> &TradingPolicy {
        &self.policy
    }
    pub(crate) fn revision_fingerprint(&self) -> &str {
        &self.revision_fingerprint
    }

    /// 基于当前已核验模拟账户修订、原 Run/Generation/Kernel 及已核验冻结策略标的构造 SIM TradingBinding。
    /// 验证冻结策略全部标的均获本账户修订批准，且生成的 profile 与标的清单仅限这批冻结且获准的标的。
    pub(crate) fn trading_binding(
        &self,
        run_id: &str,
        generation: &str,
        kernel: &str,
        strategy: &str,
        universe: &[String],
    ) -> Result<TradingBinding, Error> {
        if !command::uuid4(run_id)
            || !crate::is_sha256_hex(generation)
            || !crate::is_sha256_hex(kernel)
            || !crate::is_sha256_hex(strategy)
            || universe.is_empty()
        {
            return Err(Error::Invalid);
        }
        let mut requested = BTreeSet::new();
        for raw_id in universe {
            if raw_id.contains('\0')
                || !matches!(OnlyIdentifier::new(raw_id), Ok(ref parsed) if parsed.value() == raw_id)
                || !matches!(raw_id.parse::<OnlyInstrumentId>(), Ok(ref parsed) if parsed.to_string() == *raw_id)
                || !requested.insert(raw_id.as_str())
            {
                return Err(Error::Invalid);
            }
        }
        let allowed: BTreeMap<String, &InstrumentPolicy> = self
            .policy
            .instruments()
            .iter()
            .map(|spec| (spec.id().to_string(), spec))
            .collect();
        let mut selected_ids = Vec::with_capacity(requested.len());
        let mut selected_specs = Vec::with_capacity(requested.len());
        for id in requested {
            let Some(spec) = allowed.get(id) else {
                return Err(Error::Mismatch);
            };
            selected_ids.push(id);
            selected_specs.push(spec.to_record());
        }
        let cash = plain_cash_amount(&self.opening_cash)?;
        let config = json!({
            "schema_version": 1,
            "engine": SIM_ENGINE_ID,
            "runtime": run_id,
            "account": self.account_id.value(),
            "gateway": self.broker_integration_id.value(),
            "generation": generation,
            "runtime_kind": "SIM",
            "currency": self.opening_cash.currency().to_record(),
            "initial_cash": cash,
            "capitals": { SIM_CLUSTER_ID: cash },
            "profiles": {
                SIM_CLUSTER_ID: {
                    "schema_version": 1,
                    "revision": strategy,
                    "instruments": selected_ids,
                    "rules": self.policy.risk_rules(),
                }
            },
            "instruments": selected_specs,
        });
        let configuration = RunConfiguration::from_record(config).map_err(|_| Error::Invalid)?;
        TradingBinding::new(configuration, kernel).map_err(|_| Error::Invalid)
    }
}

fn precheck_risk_rule(rule: &Value) -> Result<(), Error> {
    let object = rule.as_object().ok_or(Error::Invalid)?;
    if object.len() != 7 || object.get("schema_version").and_then(Value::as_u64) != Some(1) {
        return Err(Error::Invalid);
    }
    for field in ["id", "scope", "mode", "kind", "limit"] {
        let text = object.get(field).and_then(Value::as_str).ok_or(Error::Invalid)?;
        if text.is_empty() || text.len() > 256 || text.contains('\0') {
            return Err(Error::Invalid);
        }
    }
    if object.get("order").and_then(Value::as_u64).is_none() {
        return Err(Error::Invalid);
    }
    let limit = object["limit"].as_str().ok_or(Error::Invalid)?;
    if limit.len() > 160
        || !limit.is_ascii()
        || limit.split_once(['e', 'E']).is_some_and(|(_, exponent)| {
            !matches!(exponent.parse::<i8>(), Ok(-18..=64))
        })
    {
        return Err(Error::Invalid);
    }
    Ok(())
}

fn plain_cash_amount(cash: &OnlyMoney) -> Result<String, Error> {
    if cash.amount().is_negative() && !cash.amount().is_zero() {
        return Err(Error::Invalid);
    }
    let amount = if cash.amount().is_zero() {
        BigDecimal::from(0)
    } else {
        cash.amount().to_string().parse::<BigDecimal>().map_err(|_| Error::Invalid)?
    };
    let (coefficient, scale) = amount.as_bigint_and_exponent();
    let precision = i64::from(cash.currency().precision());
    // 先核对执行内核接受的定点系数位数，再展开科学计数法。
    let padding = precision.checked_sub(scale).filter(|n| (0..128).contains(n)).ok_or(Error::Invalid)?;
    if coefficient.to_str_radix(10).len() > (128 - padding) as usize {
        return Err(Error::Invalid);
    }
    Ok(amount.with_scale(precision).to_plain_string())
}

fn canonical_cash(cash: &OnlyMoney) -> Result<OnlyMoney, Error> {
    let plain = plain_cash_amount(cash)?;
    OnlyMoney::new(plain.parse().map_err(|_| Error::Invalid)?, cash.currency().clone())
        .map_err(|_| Error::Invalid)
}

fn canonicalize_policy(
    account_id: &OnlyAccountId,
    opening_cash: &OnlyMoney,
    broker_integration_id: &IntegrationId,
    policy: &TradingPolicy,
) -> Result<TradingPolicy, Error> {
    let validated = TradingPolicy::new(policy.instruments.clone(), policy.risk_rules.clone())?;
    let cash_plain = plain_cash_amount(opening_cash)?;
    let instrument_ids: Vec<String> = validated.instruments.iter().map(|i| i.id.to_string()).collect();
    let instrument_records: Vec<Value> = validated.instruments.iter().map(InstrumentPolicy::to_record).collect();
    let probe = json!({
        "schema_version": 1,
        "engine": SIM_ENGINE_ID,
        "runtime": "00000000-0000-4000-8000-000000000000",
        "account": account_id.value(),
        "gateway": broker_integration_id.value(),
        "generation": "0".repeat(64),
        "runtime_kind": "SIM",
        "currency": opening_cash.currency().to_record(),
        "initial_cash": cash_plain,
        "capitals": { SIM_CLUSTER_ID: cash_plain },
        "profiles": {
            SIM_CLUSTER_ID: {
                "schema_version": 1,
                "revision": "0".repeat(64),
                "instruments": instrument_ids,
                "rules": validated.risk_rules,
            }
        },
        "instruments": instrument_records,
    });
    let components = Components::new(probe).map_err(|_| Error::Invalid)?;
    let checkpoint = components.checkpoint().map_err(|_| Error::Invalid)?;
    let canonical_rules = checkpoint["components"][4]["config"]["clusters"][SIM_CLUSTER_ID]["rules"]
        .as_array()
        .cloned()
        .ok_or(Error::Invalid)?;
    TradingPolicy::new(validated.instruments, canonical_rules)
}

fn document(
    deployment: &SemanticStoreId,
    account: &OnlyAccountId,
    cash: &OnlyMoney,
    broker: &IntegrationId,
    policy: &TradingPolicy,
) -> String {
    let instruments: Vec<Value> = policy.instruments().iter().map(InstrumentPolicy::to_record).collect();
    json!({
        "schema_version": 1,
        "deployment_id": deployment.value(),
        "account_id": account.value(),
        "opening_cash": cash.to_record(),
        "broker_integration_id": broker.value(),
        "instruments": instruments,
        "risk_rules": policy.risk_rules(),
    })
    .to_string()
}

fn fingerprint(document: &str) -> String {
    digest(document.as_bytes())
}

fn verify_document(
    deployment_id: &SemanticStoreId,
    account_id: &OnlyAccountId,
    broker: IntegrationId,
    account_revision_fingerprint: &str,
    raw: &str,
) -> Result<SimAccountRevision, Error> {
    if raw.len() > 65_536 {
        return Err(Error::Mismatch);
    }
    let parsed: Value = serde_json::from_str(raw).map_err(|_| Error::Mismatch)?;
    let root = parsed.as_object().ok_or(Error::Mismatch)?;
    if root.len() != 7 {
        return Err(Error::Mismatch);
    }
    let wire = parsed["opening_cash"]["amount"].as_str().ok_or(Error::Mismatch)?;
    // 定点金额的领域记录仅可能对小数使用负指数；在领域解析做 scale 运算前检查原文。
    if wire.len() > 160 || !wire.is_ascii() || wire.split_once(['e', 'E']).is_some_and(|(_, exponent)| {
        !matches!(exponent.parse::<i8>(), Ok(-18..=-1))
    }) {
        return Err(Error::Mismatch);
    }
    let cash = OnlyMoney::from_record(&parsed["opening_cash"]).map_err(|_| Error::Mismatch)?;
    let cash = canonical_cash(&cash).map_err(|_| Error::Mismatch)?;
    let raw_instruments = parsed["instruments"].as_array().ok_or(Error::Mismatch)?;
    let mut instruments = Vec::with_capacity(raw_instruments.len());
    for item in raw_instruments {
        instruments.push(InstrumentPolicy::from_record(item).map_err(|_| Error::Mismatch)?);
    }
    let raw_rules = parsed["risk_rules"].as_array().ok_or(Error::Mismatch)?.clone();
    let policy = TradingPolicy::new(instruments, raw_rules).map_err(|_| Error::Mismatch)?;
    let policy = canonicalize_policy(account_id, &cash, &broker, &policy).map_err(|_| Error::Mismatch)?;
    if fingerprint(raw) != account_revision_fingerprint
        || raw != document(deployment_id, account_id, &cash, &broker, &policy)
    {
        return Err(Error::Mismatch);
    }
    Ok(SimAccountRevision {
        deployment_id: deployment_id.clone(),
        account_id: account_id.clone(),
        opening_cash: cash,
        broker_integration_id: broker,
        policy,
        revision_fingerprint: account_revision_fingerprint.to_owned(),
    })
}

#[cfg(test)]
pub(crate) fn encode_canonical_document_for_test(
    deployment_id: &SemanticStoreId,
    account_id: &OnlyAccountId,
    opening_cash: &OnlyMoney,
    broker_integration_id: &IntegrationId,
    policy: &TradingPolicy,
) -> Result<(String, String), Error> {
    if account_id.value().contains('\0') {
        return Err(Error::Invalid);
    }
    let cash = canonical_cash(opening_cash)?;
    let policy = canonicalize_policy(account_id, &cash, broker_integration_id, policy)?;
    let raw = document(deployment_id, account_id, &cash, broker_integration_id, &policy);
    let id = fingerprint(&raw);
    Ok((id, raw))
}

#[cfg(test)]
pub(crate) fn verify_document_for_test(
    deployment_id: &SemanticStoreId,
    account_id: &OnlyAccountId,
    broker_integration_id: IntegrationId,
    account_revision_fingerprint: &str,
    raw: &str,
) -> Result<SimAccountRevision, Error> {
    if !crate::is_sha256_hex(account_revision_fingerprint) || account_id.value().contains('\0') {
        return Err(Error::Invalid);
    }
    verify_document(
        deployment_id,
        account_id,
        broker_integration_id,
        account_revision_fingerprint,
        raw,
    )
}

async fn verify_deployment(tx: &Transaction<'_>, id: &SemanticStoreId) -> Result<(), Error> {
    deployment::verify_binding_in_transaction(tx, id).await.map_err(|error| match error {
        deployment::Error::Mismatch | deployment::Error::Corrupt => Error::Mismatch,
        _ => Error::Unavailable,
    })
}

pub(crate) async fn publish_sim_account_revision(
    tx: &Transaction<'_>,
    deployment_id: &SemanticStoreId,
    account_id: &OnlyAccountId,
    opening_cash: &OnlyMoney,
    broker_integration_id: &IntegrationId,
    policy: &TradingPolicy,
) -> Result<SimAccountRevision, Error> {
    if account_id.value().contains('\0') {
        return Err(Error::Invalid);
    }
    let cash = canonical_cash(opening_cash)?;
    let policy = canonicalize_policy(account_id, &cash, broker_integration_id, policy)?;
    verify_deployment(tx, deployment_id).await?;
    AuthoritySession::verify_transaction(tx).await.map_err(|_| Error::Unavailable)?;
    postgres::ensure_commit_durability(tx).await.map_err(|_| Error::Unavailable)?;
    let broker = tx.query_opt("SELECT type_id FROM public.integration WHERE integration_id=$1::text::uuid",
        &[&broker_integration_id.value()]).await.map_err(|_| Error::Unavailable)?.ok_or(Error::Missing)?;
    if broker.try_get::<_, &str>(0).map_err(|_| Error::Unavailable)? != VIRTUAL_BROKER_TYPE_ID {
        return Err(Error::Mismatch);
    }
    let raw = document(deployment_id, account_id, &cash, broker_integration_id, &policy);
    let id = fingerprint(&raw);
    tx.execute("INSERT INTO public.sim_account_revision (revision_fingerprint,document) VALUES ($1,$2)
        ON CONFLICT (revision_fingerprint) DO NOTHING", &[&id, &raw]).await.map_err(|_| Error::Unavailable)?;
    let saved = read_sim_account_revision(tx, deployment_id, account_id, &id).await?;
    if saved.broker_integration_id() != broker_integration_id
        || saved.opening_cash() != &cash
        || saved.policy() != &policy
    {
        return Err(Error::Mismatch);
    }
    Ok(saved)
}

pub(crate) async fn read_sim_account_revision(
    tx: &Transaction<'_>,
    deployment_id: &SemanticStoreId,
    account_id: &OnlyAccountId,
    account_revision_fingerprint: &str,
) -> Result<SimAccountRevision, Error> {
    if !crate::is_sha256_hex(account_revision_fingerprint) || account_id.value().contains('\0') {
        return Err(Error::Invalid);
    }
    verify_deployment(tx, deployment_id).await?;
    let row = tx.query_opt("SELECT a.document, a.broker_integration_id::text, i.type_id
        FROM public.sim_account_revision a LEFT JOIN public.integration i ON i.integration_id=a.broker_integration_id
        WHERE a.revision_fingerprint=$1", &[&account_revision_fingerprint]).await
        .map_err(|_| Error::Unavailable)?.ok_or(Error::Missing)?;
    if row.try_get::<_, Option<&str>>(2).map_err(|_| Error::Unavailable)? != Some(VIRTUAL_BROKER_TYPE_ID) {
        return Err(Error::Mismatch);
    }
    let broker = IntegrationId::new(row.try_get(1).map_err(|_| Error::Unavailable)?).map_err(|_| Error::Mismatch)?;
    let raw: &str = row.try_get(0).map_err(|_| Error::Unavailable)?;
    verify_document(deployment_id, account_id, broker, account_revision_fingerprint, raw)
}
