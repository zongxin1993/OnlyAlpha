//! 运营方模拟账户修订的发布与精确查询应用层入口。
use super::{integration_configuration::IntegrationId, source_access};
use crate::{
    bootstrap::deployment::SemanticStoreId,
    persistence::{
        authority_session::AuthoritySession,
        postgres,
        sim_account::{self, InstrumentPolicy, SimAccountRevision, TradingPolicy},
    },
    security::human_access::{Access, Session},
};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::OnlyCurrencyType,
    identifiers::{OnlyAccountId, OnlyInstrumentId},
    value::{OnlyCurrency, OnlyMoney},
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::str::FromStr;
use tokio_postgres::{Client, IsolationLevel};

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub(crate) struct SimCurrencyWire {
    pub code: String,
    pub precision: u8,
    pub currency_type: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub(crate) struct SimOpeningCashWire {
    pub amount: String,
    pub currency: SimCurrencyWire,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub(crate) struct SimInstrumentPolicyWire {
    pub id: String,
    pub price_precision: u8,
    pub quantity_precision: u8,
    pub multiplier: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub(crate) struct SimRiskRuleWire {
    pub schema_version: u8,
    pub id: String,
    pub scope: String,
    pub order: u64,
    pub mode: String,
    pub kind: String,
    pub limit: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub(crate) struct SimAccountRevisionPublishInput {
    pub schema_version: u8,
    pub opening_cash: SimOpeningCashWire,
    pub broker_integration_id: String,
    pub instruments: Vec<SimInstrumentPolicyWire>,
    pub risk_rules: Vec<SimRiskRuleWire>,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize, utoipa::ToSchema)]
#[serde(deny_unknown_fields)]
pub(crate) struct SimAccountRevisionView {
    pub schema_version: u8,
    pub deployment_id: String,
    pub account_id: String,
    pub revision_fingerprint: String,
    pub broker_integration_id: String,
    pub opening_cash: SimOpeningCashWire,
    pub instruments: Vec<SimInstrumentPolicyWire>,
    pub risk_rules: Vec<SimRiskRuleWire>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum AccountError {
    Access(source_access::Error),
    OperatorRequired,
    Storage(sim_account::Error),
    UnknownCommit,
}

impl From<source_access::Error> for AccountError {
    fn from(error: source_access::Error) -> Self {
        Self::Access(error)
    }
}

impl From<sim_account::Error> for AccountError {
    fn from(error: sim_account::Error) -> Self {
        Self::Storage(error)
    }
}

fn require_operator(access: &Access, session: &Session) -> Result<(), AccountError> {
    access.check_session(session)?;
    if !access.local_operator(session.subject_id()?) {
        return Err(AccountError::OperatorRequired);
    }
    Ok(())
}

fn parse_account_id(raw: &str) -> Result<OnlyAccountId, AccountError> {
    if raw.is_empty() || raw.len() > 128 || raw.contains('\0') {
        return Err(sim_account::Error::Invalid.into());
    }
    let parsed = OnlyAccountId::new(raw).map_err(|_| sim_account::Error::Invalid)?;
    if parsed.value() != raw {
        return Err(sim_account::Error::Invalid.into());
    }
    Ok(parsed)
}

fn parse_publish_input(
    account_id: &str,
    input: SimAccountRevisionPublishInput,
) -> Result<(OnlyAccountId, OnlyMoney, IntegrationId, TradingPolicy), AccountError> {
    if input.schema_version != 1 {
        return Err(sim_account::Error::Invalid.into());
    }
    let account = parse_account_id(account_id)?;
    let wire_amount = input.opening_cash.amount.as_str();
    if wire_amount.is_empty()
        || wire_amount.len() > 160
        || !wire_amount.is_ascii()
        || wire_amount
            .split_once(['e', 'E'])
            .is_some_and(|(_, exponent)| !matches!(exponent.parse::<i8>(), Ok(-18..=-1)))
    {
        return Err(sim_account::Error::Invalid.into());
    }
    let currency_type = OnlyCurrencyType::from_str(&input.opening_cash.currency.currency_type)
        .map_err(|_| sim_account::Error::Invalid)?;
    let currency = OnlyCurrency::new(
        &input.opening_cash.currency.code,
        input.opening_cash.currency.precision,
        currency_type,
    )
    .map_err(|_| sim_account::Error::Invalid)?;
    let amount = wire_amount.parse().map_err(|_| sim_account::Error::Invalid)?;
    let opening_cash = OnlyMoney::new(amount, currency).map_err(|_| sim_account::Error::Invalid)?;
    let broker =
        IntegrationId::new(&input.broker_integration_id).map_err(|_| sim_account::Error::Invalid)?;
    let mut instruments = Vec::with_capacity(input.instruments.len());
    for item in input.instruments {
        let id: OnlyInstrumentId = item.id.parse().map_err(|_| sim_account::Error::Invalid)?;
        if id.to_string() != item.id {
            return Err(sim_account::Error::Invalid.into());
        }
        instruments.push(InstrumentPolicy::new(
            id,
            item.price_precision,
            item.quantity_precision,
            &item.multiplier,
        )?);
    }
    let mut rules = Vec::with_capacity(input.risk_rules.len());
    for rule in input.risk_rules {
        rules.push(json!({
            "schema_version": rule.schema_version,
            "id": rule.id,
            "scope": rule.scope,
            "order": rule.order,
            "mode": rule.mode,
            "kind": rule.kind,
            "limit": rule.limit,
        }));
    }
    let policy = TradingPolicy::new(instruments, rules)?;
    Ok((account, opening_cash, broker, policy))
}

impl SimAccountRevisionView {
    fn from_revision(revision: &SimAccountRevision) -> Result<Self, AccountError> {
        let cash = revision.opening_cash().to_record();
        let amount = cash["amount"]
            .as_str()
            .ok_or(sim_account::Error::Mismatch)?
            .to_owned();
        let currency = &cash["currency"];
        let code = currency["code"]
            .as_str()
            .ok_or(sim_account::Error::Mismatch)?
            .to_owned();
        let precision = currency["precision"]
            .as_u64()
            .and_then(|v| u8::try_from(v).ok())
            .ok_or(sim_account::Error::Mismatch)?;
        let currency_type = currency["currency_type"]
            .as_str()
            .ok_or(sim_account::Error::Mismatch)?
            .to_owned();
        let instruments = revision
            .instruments()
            .iter()
            .map(|item| SimInstrumentPolicyWire {
                id: item.id().to_string(),
                price_precision: item.price_precision(),
                quantity_precision: item.quantity_precision(),
                multiplier: item.multiplier().to_owned(),
            })
            .collect();
        let risk_rules = revision
            .risk_rules()
            .iter()
            .map(|rule| serde_json::from_value::<SimRiskRuleWire>(rule.clone()))
            .collect::<Result<Vec<_>, _>>()
            .map_err(|_| sim_account::Error::Mismatch)?;
        Ok(Self {
            schema_version: 1,
            deployment_id: revision.deployment_id().value().to_owned(),
            account_id: revision.account_id().value().to_owned(),
            revision_fingerprint: revision.revision_fingerprint().to_owned(),
            broker_integration_id: revision.broker_integration_id().value().to_owned(),
            opening_cash: SimOpeningCashWire {
                amount,
                currency: SimCurrencyWire {
                    code,
                    precision,
                    currency_type,
                },
            },
            instruments,
            risk_rules,
        })
    }
}

pub(crate) async fn publish_operator_revision(
    authority: &mut AuthoritySession,
    access: &Access,
    session: &Session,
    deployment: &SemanticStoreId,
    account_id: &str,
    input: SimAccountRevisionPublishInput,
) -> Result<SimAccountRevisionView, AccountError> {
    require_operator(access, session)?;
    let (account, opening_cash, broker, policy) = parse_publish_input(account_id, input)?;
    let client = authority
        .client_mut()
        .await
        .map_err(|_| sim_account::Error::Unavailable)?;
    let tx = client
        .build_transaction()
        .isolation_level(IsolationLevel::RepeatableRead)
        .start()
        .await
        .map_err(|_| sim_account::Error::Unavailable)?;
    postgres::bounds(&tx)
        .await
        .map_err(|_| sim_account::Error::Unavailable)?;
    let saved = sim_account::publish_sim_account_revision(
        &tx,
        deployment,
        &account,
        &opening_cash,
        &broker,
        &policy,
    )
    .await?;
    require_operator(access, session)?;
    tx.commit()
        .await
        .map_err(|_| AccountError::UnknownCommit)?;
    SimAccountRevisionView::from_revision(&saved)
}

pub(crate) async fn read_operator_revision(
    client: &mut Client,
    access: &Access,
    session: &Session,
    deployment: &SemanticStoreId,
    account_id: &str,
    revision_fingerprint: &str,
) -> Result<SimAccountRevisionView, AccountError> {
    require_operator(access, session)?;
    let account = parse_account_id(account_id)?;
    if !crate::is_sha256_hex(revision_fingerprint) {
        return Err(sim_account::Error::Invalid.into());
    }
    let tx = client
        .build_transaction()
        .isolation_level(IsolationLevel::RepeatableRead)
        .read_only(true)
        .start()
        .await
        .map_err(|_| sim_account::Error::Unavailable)?;
    postgres::bounds(&tx)
        .await
        .map_err(|_| sim_account::Error::Unavailable)?;
    let saved =
        sim_account::read_sim_account_revision(&tx, deployment, &account, revision_fingerprint)
            .await?;
    tx.commit()
        .await
        .map_err(|_| sim_account::Error::Unavailable)?;
    require_operator(access, session)?;
    SimAccountRevisionView::from_revision(&saved)
}
