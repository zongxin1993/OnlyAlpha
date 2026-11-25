use super::{authority_session::AuthoritySession, integration_postgres, postgres::{self, Commands}, sim_account, trading_facts};
use crate::application::integration_configuration::{Error as IntegrationError, Revision};
use crate::bootstrap::deployment::SemanticStoreId;
use onlyalpha_broker::Scope;
use onlyalpha_broker_virtual::{VirtualBroker, provider};
use onlyalpha_domain::{base::OnlyDomainModel, identifiers::OnlyAccountId, value::OnlyMoney};
use crate::application::{command::{self, Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Put, Receipt}, sim_run::VerifiedSimAdmission};
use onlyalpha_runtime::{RunConfiguration, durability::{DurabilityError, TradingBinding}};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tokio_postgres::{Row, Transaction};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum Error {
    Invalid,
    Missing,
    Mismatch,
    Conflict,
    Integrity,
    Unavailable,
    UnknownCommit,
}

type Result<T> = std::result::Result<T, Error>;

impl From<command::Error> for Error {
    fn from(error: command::Error) -> Self {
        match error {
            command::Error::Conflict => Self::Conflict,
            command::Error::Unavailable | command::Error::Denied => Self::Unavailable,
            _ => Self::Integrity,
        }
    }
}

fn db(error: tokio_postgres::Error) -> Error {
    match error.code().map(|state| state.code()) {
        Some("23505") => Error::Conflict,
        Some(code) if code.starts_with("23") || code.starts_with("22") => Error::Integrity,
        _ => Error::Unavailable,
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct StartIntent {
    pub(crate) deployment_id: String,
    pub(crate) subject_kind: String,
    pub(crate) subject_id: String,
    pub(crate) strategy_fingerprint: String,
    pub(crate) backtest_run_id: String,
    pub(crate) policy_fingerprint: String,
    pub(crate) decision_fingerprint: String,
    pub(crate) promotion_fingerprint: String,
    pub(crate) account_id: String,
    pub(crate) account_revision_fingerprint: String,
    pub(crate) broker_revision_fingerprint: String,
}

impl StartIntent {
    fn encoded(&self) -> Result<String> {
        if !matches!(self.subject_kind.as_str(), "HUMAN" | "AGENT")
            || [&self.subject_id, &self.deployment_id, &self.account_id].iter().any(|id| id.trim().is_empty())
            || !command::uuid4(&self.backtest_run_id)
            || [&self.strategy_fingerprint, &self.policy_fingerprint, &self.decision_fingerprint,
                &self.promotion_fingerprint, &self.account_revision_fingerprint, &self.broker_revision_fingerprint]
                .iter().any(|pin| !crate::is_sha256_hex(pin))
        {
            return Err(Error::Invalid);
        }
        serde_json::to_value(self).map(|value| value.to_string()).map_err(|_| Error::Invalid)
    }

    pub(crate) fn fingerprint(&self) -> Result<String> {
        Ok(onlyalpha_execution::digest(self.encoded()?.as_bytes()))
    }
}

#[derive(Debug)]
pub(crate) struct Accepted {
    pub(crate) receipt: Receipt,
    pub(crate) trading_binding: TradingBinding,
    pub(crate) broker_runtime_fingerprint: String,
}

#[derive(Debug)]
pub(crate) struct Reservation {
    pub(crate) command_id: CommandId,
    pub(crate) run_id: String,
    pub(crate) intent: StartIntent,
    pub(crate) intent_fingerprint: String,
    pub(crate) generation: String,
    pub(crate) kernel_artifact: String,
    pub(crate) accepted: Option<Accepted>,
}

impl Reservation {
    fn matches_stream(&self, binding: &TradingBinding) -> bool {
        let config = binding.configuration().record();
        binding.kernel_artifact() == self.kernel_artifact && config["runtime_kind"] == "SIM"
            && config["runtime"].as_str() == Some(self.run_id.as_str())
            && config["account"].as_str() == Some(self.intent.account_id.as_str())
            && config["generation"].as_str() == Some(self.generation.as_str())
    }
}

const READ: &str = "SELECT r.run_id, r.intent, r.command_fingerprint, r.generation, r.kernel_artifact,
    r.deployment_id, r.account_id, a.scope_key, a.binding_fingerprint, a.broker_runtime_fingerprint,
    s.configuration, s.configuration_fingerprint, s.binding_fingerprint AS stream_fingerprint, s.kernel_artifact AS stream_kernel
    FROM public.sim_run_reservation r LEFT JOIN public.sim_run_admission a USING (command_id)
    LEFT JOIN public.trading_fact_stream s ON s.scope_key=a.scope_key WHERE r.command_id=$1::text::uuid";

fn text<'a>(row: &'a Row, field: &str) -> Result<&'a str> {
    row.try_get(field).map_err(|_| Error::Integrity)
}

async fn load_locked(tx: &Transaction<'_>, id: &CommandId) -> Result<Option<Reservation>> {
    let command = Commands::verify_binding_in_transaction(tx, id).await?;
    let row = tx.query_opt(READ, &[&id.value()]).await.map_err(db)?;
    let admission = match &command {
        Binding::Admitted(a) => Some(a),
        Binding::Accepted(r) => Some(r.admission()),
        Binding::None => None,
    };
    let sim = admission.filter(|a| a.kind() == CommandKind::StartSimRun);
    let (row, admission) = match (row, sim) {
        (None, None) => return Ok(None),
        (Some(row), Some(admission)) => (row, admission),
        _ => return Err(Error::Integrity),
    };
    let raw = text(&row, "intent")?;
    let intent: StartIntent = serde_json::from_str(raw).map_err(|_| Error::Integrity)?;
    let pin = text(&row, "command_fingerprint")?;
    if intent.encoded().map_err(|_| Error::Integrity)? != raw || onlyalpha_execution::digest(raw.as_bytes()) != pin
        || admission.fingerprint() != pin || intent.deployment_id != text(&row, "deployment_id")?
        || intent.account_id != text(&row, "account_id")?
    {
        return Err(Error::Integrity);
    }
    let mut reservation = Reservation {
        command_id: id.clone(), run_id: text(&row, "run_id")?.into(), intent,
        intent_fingerprint: pin.into(), generation: text(&row, "generation")?.into(),
        kernel_artifact: text(&row, "kernel_artifact")?.into(), accepted: None,
    };
    if !command::uuid4(&reservation.run_id) || !crate::is_sha256_hex(&reservation.generation)
        || !crate::is_sha256_hex(&reservation.kernel_artifact) {
        return Err(Error::Integrity);
    }
    let scope: Option<&str> = row.try_get("scope_key").map_err(|_| Error::Integrity)?;
    match (scope, command) {
        (None, Binding::Admitted(_)) => {}
        (Some(key), Binding::Accepted(receipt)) => {
            let config_raw = text(&row, "configuration")?;
            let value: Value = serde_json::from_str(config_raw).map_err(|_| Error::Integrity)?;
            let config = RunConfiguration::from_record(value).map_err(|_| Error::Integrity)?;
            if config.record().to_string() != config_raw || config.fingerprint() != text(&row, "configuration_fingerprint")? {
                return Err(Error::Integrity);
            }
            let binding = TradingBinding::new(config, text(&row, "stream_kernel")?).map_err(|_| Error::Integrity)?;
            let broker = text(&row, "broker_runtime_fingerprint")?;
            if !reservation.matches_stream(&binding) || binding.key() != key
                || binding.fingerprint() != text(&row, "binding_fingerprint")?
                || binding.fingerprint() != text(&row, "stream_fingerprint")?
                || !crate::is_sha256_hex(broker) || receipt.outcome().kind() != OutcomeKind::SimRun
                || receipt.outcome().id() != reservation.run_id {
                return Err(Error::Integrity);
            }
            reservation.accepted = Some(Accepted { receipt, trading_binding: binding, broker_runtime_fingerprint: broker.into() });
        }
        _ => return Err(Error::Integrity),
    }
    Ok(Some(reservation))
}

pub(crate) async fn read_intent_resources(
    tx: &Transaction<'_>,
    intent: &StartIntent,
) -> Result<(sim_account::SimAccountRevision, Revision)> {
    let deployment = SemanticStoreId::new(&intent.deployment_id).map_err(|_| Error::Mismatch)?;
    let account_id = OnlyAccountId::new(intent.account_id.as_str()).map_err(|_| Error::Mismatch)?;
    let account = sim_account::read_sim_account_revision(tx, &deployment, &account_id, &intent.account_revision_fingerprint)
        .await.map_err(|error| match error {
            sim_account::Error::Missing => Error::Missing,
            sim_account::Error::Mismatch | sim_account::Error::Invalid => Error::Mismatch,
            sim_account::Error::Unavailable => Error::Unavailable,
        })?;
    let broker = integration_postgres::read_virtual_broker_revision(
        tx, account.broker_integration_id(), &intent.broker_revision_fingerprint,
    ).await.map_err(|error| match error {
        IntegrationError::Unavailable => Error::Unavailable,
        _ => Error::Mismatch,
    })?.ok_or(Error::Missing)?;
    Ok((account, broker))
}

pub(crate) async fn read_resources_in_transaction(
    tx: &Transaction<'_>,
    reservation: &Reservation,
) -> Result<(sim_account::SimAccountRevision, Revision)> {
    if reservation.intent.fingerprint().map_err(|_| Error::Mismatch)? != reservation.intent_fingerprint {
        return Err(Error::Mismatch);
    }
    let (account, broker) = read_intent_resources(tx, &reservation.intent).await?;
    if reservation.accepted.as_ref().is_some_and(|accepted|
        accepted.broker_runtime_fingerprint != broker.record().runtime_configuration_fingerprint) {
        return Err(Error::Mismatch);
    }
    Ok((account, broker))
}

pub(crate) struct VenueInputs {
    pub(crate) scope: Scope,
    pub(crate) artifact: String,
    pub(crate) cash: OnlyMoney,
    pub(crate) configuration: Value,
}

impl VenueInputs {
    fn open(&self) -> Result<VirtualBroker> {
        let venue = VirtualBroker::new(self.scope.clone(), &self.artifact, self.cash.clone(), &self.configuration)
            .map_err(|_| Error::Mismatch)?;
        let source = venue.source_binding();
        let normalized = provider::normalize_configuration(&self.configuration).map_err(|_| Error::Mismatch)?;
        if source["artifact_sha256"].as_str() != Some(self.artifact.as_str())
            || source["scope"] != self.scope.record() || source["initial_cash"] != self.cash.to_record()
            || source["configuration"] != normalized {
            return Err(Error::Mismatch);
        }
        Ok(venue)
    }
}

pub(crate) async fn read_venue_with_artifact(
    tx: &Transaction<'_>, reservation: &Reservation, binding: &TradingBinding, broker_fingerprint: &str,
    loaded_artifact: &str,
) -> Result<VenueInputs> {
    let (account, broker) = read_resources_in_transaction(tx, reservation).await?;
    let record = broker.record();
    let descriptor: Value = serde_json::from_str(record.type_descriptor_document.raw().get()).map_err(|_| Error::Integrity)?;
    let config = binding.configuration().record();
    let cash = OnlyMoney::from_record(&serde_json::json!({"schema_version":1,
        "amount":config["initial_cash"], "currency":config["currency"]})).map_err(|_| Error::Mismatch)?;
    if !reservation.matches_stream(binding)
        || record.runtime_configuration_fingerprint != broker_fingerprint
        || descriptor != provider::descriptor() || &cash != account.opening_cash() {
        return Err(Error::Mismatch);
    }
    let scope = serde_json::json!({"engine":config["engine"],"runtime":config["runtime"],"gateway":config["gateway"],
        "account":config["account"],"generation":config["generation"],"runtime_kind":config["runtime_kind"]});
    let scope = Scope::decode(&scope).map_err(|_| Error::Mismatch)?;
    let configuration = serde_json::from_str(record.configuration_document.raw().get()).map_err(|_| Error::Integrity)?;
    if !crate::is_sha256_hex(loaded_artifact) || loaded_artifact != binding.kernel_artifact() {
        return Err(Error::Mismatch);
    }
    Ok(VenueInputs { scope, artifact: loaded_artifact.to_owned(), cash: account.opening_cash().clone(), configuration })
}

pub(crate) async fn reserve_in_transaction(tx: &Transaction<'_>, command_id: &CommandId, intent: &StartIntent,
    generation: &str, kernel_artifact: &str) -> Result<Reservation> {
    let raw = intent.encoded()?;
    let pin = onlyalpha_execution::digest(raw.as_bytes());
    let admission = Admission::new(command_id.clone(), CommandKind::StartSimRun, &pin)?;
    AuthoritySession::verify_transaction(tx).await.map_err(|_| Error::Unavailable)?;
    tx.batch_execute("SET CONSTRAINTS public.sim_run_command_reserved DEFERRED").await.map_err(db)?;
    let created = Commands::admit_exact_in_transaction(tx, &admission).await? == Put::Created;
    if created {
        if !crate::is_sha256_hex(generation) || !crate::is_sha256_hex(kernel_artifact) { return Err(Error::Invalid); }
        tx.execute("INSERT INTO public.sim_run_reservation
            (command_id,command_fingerprint,intent,deployment_id,account_id,generation,kernel_artifact)
            VALUES ($1::text::uuid,$2,$3,$4,$5,$6,$7)", &[&command_id.value(), &pin, &raw, &intent.deployment_id,
                &intent.account_id, &generation, &kernel_artifact]).await.map_err(db)?;
    }
    let original = load_locked(tx, command_id).await?.ok_or(Error::Integrity)?;
    if original.intent != *intent { return Err(Error::Conflict); }
    postgres::ensure_commit_durability(tx).await?;
    tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await.map_err(db)?;
    AuthoritySession::verify_transaction(tx).await.map_err(|_| Error::Unavailable)?;
    Ok(original)
}

pub(crate) async fn accept_in_transaction_with_artifact(
    tx: &Transaction<'_>, proof: &VerifiedSimAdmission, at: &str, loaded_artifact: &str,
) -> Result<Receipt> {
    AuthoritySession::verify_transaction(tx).await.map_err(|_| Error::Unavailable)?;
    let id = CommandId::new(proof.command_id())?;
    Commands::lock_command(tx, &id).await?;
    let original = load_locked(tx, &id).await?.ok_or(Error::Integrity)?;
    let binding = proof.trading_binding();
    let broker = proof.broker_runtime_fingerprint();
    if original.run_id != proof.run_id() || original.intent_fingerprint != proof.intent_fingerprint()
        || original.generation != proof.generation() || !original.matches_stream(binding) || !crate::is_sha256_hex(broker) {
        return Err(Error::Conflict);
    }
    let venue = read_venue_with_artifact(tx, &original, binding, broker, loaded_artifact).await?.open()?;
    if let Some(accepted) = original.accepted {
        if accepted.trading_binding.fingerprint() != binding.fingerprint() || accepted.broker_runtime_fingerprint != broker {
            return Err(Error::Conflict);
        }
        super::sim_venue::verify_open_in_transaction(tx, binding, &venue).await?;
        return Ok(accepted.receipt);
    }
    postgres::ensure_commit_durability(tx).await?;
    let receipt = Receipt::new(Admission::new(id.clone(), CommandKind::StartSimRun, &original.intent_fingerprint)?,
        Outcome::new(OutcomeKind::SimRun, &original.run_id)?, at)?;
    if !trading_facts::register_in_transaction(tx, binding).await.map_err(|error| match error {
        DurabilityError::Rejected(_) => Error::Integrity,
        DurabilityError::Unavailable => Error::Unavailable,
        DurabilityError::UnknownCommit => Error::UnknownCommit,
    })? { return Err(Error::Conflict); }
    tx.batch_execute("SET CONSTRAINTS public.sim_run_receipt_admitted, public.sim_run_open_fk DEFERRED").await.map_err(db)?;
    Commands::put_verified_receipt_in_transaction(tx, &receipt).await?;
    tx.execute("INSERT INTO public.sim_run_admission
        (command_id,run_id,deployment_id,account_id,scope_key,binding_fingerprint,broker_runtime_fingerprint)
        VALUES ($1::text::uuid,$2,$3,$4,$5,$6,$7)", &[&id.value(), &original.run_id, &original.intent.deployment_id,
            &original.intent.account_id, &binding.key(), &binding.fingerprint(), &broker]).await.map_err(db)?;
    super::sim_venue::initialize_in_transaction(tx, binding, &venue).await?;
    tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await.map_err(db)?;
    AuthoritySession::verify_transaction(tx).await.map_err(|_| Error::Unavailable)?;
    Ok(receipt)
}

pub(crate) async fn lookup_in_transaction(tx: &Transaction<'_>, deployment_id: &str, subject_kind: &str,
    subject_id: &str, command_id: &CommandId) -> Result<Option<Reservation>> {
    Commands::lock_command(tx, command_id).await?;
    Ok(load_locked(tx, command_id).await?.filter(|row| row.intent.deployment_id == deployment_id
        && row.intent.subject_kind == subject_kind && row.intent.subject_id == subject_id))
}

pub(crate) async fn recovery_command_ids(tx: &Transaction<'_>, deployment_id: &str) -> Result<Vec<String>> {
    AuthoritySession::verify_transaction(tx).await.map_err(|_| Error::Unavailable)?;
    postgres::bounds(tx).await?;
    let rows = tx.query("SELECT command_id::text FROM public.sim_run_reservation WHERE deployment_id=$1 ORDER BY command_id",
        &[&deployment_id]).await.map_err(db)?;
    rows.iter().map(|row| row.try_get(0).map_err(|_| Error::Integrity)).collect()
}

pub(crate) async fn recovery_in_transaction(
    tx: &Transaction<'_>, deployment_id: &str, command_id: &str,
) -> Result<Reservation> {
    AuthoritySession::verify_transaction(tx).await.map_err(|_| Error::Unavailable)?;
    let id = CommandId::new(command_id)?;
    Commands::lock_command(tx, &id).await?;
    let reservation = load_locked(tx, &id).await?.ok_or(Error::Integrity)?;
    if reservation.intent.deployment_id != deployment_id { return Err(Error::Integrity); }
    Ok(reservation)
}
