use super::{authority_session::AuthoritySession, node_access, postgres};
use onlyalpha_execution::Record;
use onlyalpha_runtime::durability::{
    DurabilityError, DurableCommitReceipt, DurableFactPort, PreparedTradingFacts, RecoveryFacts,
    TradingBinding,
};
use serde_json::{Value, json};
use tokio_postgres::{IsolationLevel, Row, Transaction};

type Result<T> = std::result::Result<T, DurabilityError>;

fn rejected(code: &str) -> DurabilityError {
    DurabilityError::Rejected(code.to_owned())
}

fn database(error: tokio_postgres::Error) -> DurabilityError {
    match error.code().map(|code| code.code()) {
        Some(code) if code.starts_with("23") || code.starts_with("22") => {
            rejected("TRADING_FACT_INTEGRITY")
        }
        _ => DurabilityError::Unavailable,
    }
}

const FACT_ROWS: &str = "SELECT f.sequence, f.transaction_id, f.input_id, f.payload_fingerprint,
    f.prepared, r.result_hashes FROM public.trading_fact f
    LEFT JOIN public.trading_fact_ready r USING (scope_key, sequence)";

fn decode(row: &Row) -> Result<Record> {
    let sequence: i64 = row.try_get(0).map_err(database)?;
    let transaction: &str = row.try_get(1).map_err(database)?;
    let input: &str = row.try_get(2).map_err(database)?;
    let fingerprint: &str = row.try_get(3).map_err(database)?;
    let raw: &str = row.try_get(4).map_err(database)?;
    let installed: Option<Vec<String>> = row.try_get(5).map_err(database)?;
    let ready = installed.is_some();
    let prepared: Value = serde_json::from_str(raw).map_err(|_| rejected("TRADING_FACT_BODY"))?;
    if prepared.to_string() != raw {
        return Err(rejected("TRADING_FACT_BODY"));
    }
    let record = Record::decode(&json!({"schema_version": 1, "prepared": prepared, "ready": ready, "delivered": false}))
        .map_err(|_| rejected("TRADING_FACT_BODY"))?;
    let plan = record.prepared();
    if let Some(hashes) = installed
        && hashes.iter().ne(plan.projection_hashes().iter().map(|(_, result)| result))
    {
        return Err(rejected("TRADING_FACT_PROJECTION_CONFLICT"));
    }
    if i64::try_from(plan.sequence()).ok() != Some(sequence)
        || plan.id() != transaction
        || plan.input()["input_id"].as_str() != Some(input)
        || plan.payload_fingerprint() != fingerprint
    {
        return Err(rejected("TRADING_FACT_ASSOCIATION"));
    }
    Ok(record)
}

async fn record_at(tx: &Transaction<'_>, key: &str, sequence: i64) -> Result<Option<Record>> {
    let query = format!("{FACT_ROWS} WHERE f.scope_key=$1 AND f.sequence=$2");
    tx.query_opt(&query, &[&key, &sequence]).await.map_err(database)?
        .as_ref().map(decode).transpose()
}

async fn head(tx: &Transaction<'_>, binding: &TradingBinding) -> Result<u64> {
    let row = tx.query_opt("SELECT binding_fingerprint,kernel_artifact,configuration,head
        FROM public.trading_fact_stream WHERE scope_key=$1", &[&binding.key()])
        .await.map_err(database)?.ok_or_else(|| rejected("TRADING_FACT_BINDING_MISSING"))?;
    if row.try_get::<_, &str>(0).map_err(database)? != binding.fingerprint()
        || row.try_get::<_, &str>(1).map_err(database)? != binding.kernel_artifact()
        || row.try_get::<_, &str>(2).map_err(database)? != binding.configuration().record().to_string()
    {
        return Err(rejected("TRADING_FACT_BINDING_CONFLICT"));
    }
    u64::try_from(row.try_get::<_, i64>(3).map_err(database)?)
        .map_err(|_| rejected("TRADING_FACT_HEAD_INVALID"))
}

async fn lock_stream(tx: &Transaction<'_>, binding: &TradingBinding) -> Result<()> {
    tx.query_one("SELECT pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended($1, 8187))",
        &[&binding.key()]).await.map_err(database)?;
    Ok(())
}

pub(super) async fn register_in_transaction(tx: &Transaction<'_>, binding: &TradingBinding) -> Result<bool> {
    lock_stream(tx, binding).await?;
    let inserted = tx.execute("INSERT INTO public.trading_fact_stream
        (scope_key,binding_fingerprint,kernel_artifact,configuration,configuration_fingerprint)
        VALUES ($1,$2,$3,$4,$5) ON CONFLICT (scope_key) DO NOTHING", &[
            &binding.key(), &binding.fingerprint(), &binding.kernel_artifact(),
            &binding.configuration().record().to_string(), &binding.configuration().fingerprint(),
        ]).await.map_err(database)?;
    head(tx, binding).await?;
    Ok(inserted == 1)
}

async fn observe(tx: &Transaction<'_>, binding: &TradingBinding) -> Result<RecoveryFacts> {
    let head = head(tx, binding).await?;
    let query = format!("{FACT_ROWS} WHERE f.scope_key=$1 ORDER BY f.sequence");
    let rows = tx.query(&query, &[&binding.key()]).await.map_err(database)?;
    let records = rows.iter().map(decode).collect::<Result<Vec<_>>>()?;
    RecoveryFacts::from_records(binding, binding.fingerprint(), head, records)
}

async fn finish_mutation(tx: Transaction<'_>) -> Result<()> {
    postgres::ensure_commit_durability(&tx).await.map_err(|_| DurabilityError::Unavailable)?;
    AuthoritySession::verify_transaction(&tx).await.map_err(|_| DurabilityError::Unavailable)?;
    tx.commit().await.map_err(|_| DurabilityError::UnknownCommit)
}

pub struct TradingFactRepository<'a> {
    authority: &'a mut AuthoritySession,
}

impl<'a> TradingFactRepository<'a> {
    pub async fn new(authority: &'a mut AuthoritySession) -> Result<Self> {
        let client = authority.client_mut().await.map_err(|_| DurabilityError::Unavailable)?;
        let login = client.query_one("SELECT session_user::pg_catalog.text", &[])
            .await.map_err(|_| DurabilityError::Unavailable)?;
        let authenticated: &str = login.try_get(0).map_err(|_| DurabilityError::Unavailable)?;
        node_access::verify(client, authenticated).await.map_err(|code| {
            tracing::error!(%code, "节点数据库登录校验失败");
            DurabilityError::Unavailable
        })?;
        Ok(Self { authority })
    }

    async fn begin(&mut self) -> Result<Transaction<'_>> {
        let client = self.authority.client_mut().await.map_err(|_| DurabilityError::Unavailable)?;
        let tx = client.build_transaction().isolation_level(IsolationLevel::ReadCommitted)
            .start().await.map_err(database)?;
        postgres::bounds(&tx).await.map_err(|_| DurabilityError::Unavailable)?;
        tx.batch_execute("SET LOCAL search_path = pg_catalog, pg_temp")
            .await.map_err(database)?;
        AuthoritySession::verify_transaction(&tx).await.map_err(|_| DurabilityError::Unavailable)?;
        Ok(tx)
    }

    async fn begin_locked(&mut self, binding: &TradingBinding) -> Result<Transaction<'_>> {
        let tx = self.begin().await?;
        lock_stream(&tx, binding).await?;
        Ok(tx)
    }

    pub async fn register(&mut self, binding: &TradingBinding) -> Result<()> {
        let tx = self.begin().await?;
        register_in_transaction(&tx, binding).await?;
        finish_mutation(tx).await
    }

    /// 从原计划安装可读回的六项投影摘要；每次恢复仍由内核重建并核对内存状态。
    pub async fn mark_projected(&mut self, recovery: &RecoveryFacts) -> Result<()> {
        let binding = recovery.binding();
        let original = recovery.unprojected().ok_or_else(|| rejected("TRADING_FACT_UNPROJECTED_REQUIRED"))?;
        let tx = self.begin_locked(binding).await?;
        let current = observe(&tx, binding).await?;
        let (last, prefix) = current.records().split_last().ok_or_else(|| rejected("TRADING_FACT_MISSING"))?;
        if last.prepared() != original.prepared() || recovery.records().split_last().map(|(_, rows)| rows) != Some(prefix) {
            return Err(rejected("TRADING_FACT_PROJECTION_CONFLICT"));
        }
        if !last.ready() {
            let sequence = i64::try_from(last.prepared().sequence()).map_err(|_| rejected("TRADING_FACT_SEQUENCE"))?;
            tx.query_one("SELECT public.trading_fact_install_projection($1,$2)",
                &[&binding.key(), &sequence]).await.map_err(database)?;
        }
        finish_mutation(tx).await
    }
}

impl DurableFactPort for TradingFactRepository<'_> {
    async fn load_recovery(&mut self, binding: &TradingBinding) -> Result<RecoveryFacts> {
        let tx = self.begin_locked(binding).await?;
        let recovery = observe(&tx, binding).await?;
        AuthoritySession::verify_transaction(&tx).await.map_err(|_| DurabilityError::Unavailable)?;
        tx.commit().await.map_err(|_| DurabilityError::Unavailable)?;
        Ok(recovery)
    }

    async fn commit(&mut self, facts: &PreparedTradingFacts) -> Result<DurableCommitReceipt> {
        let binding = facts.binding();
        let plan = facts.prepared();
        let seq = i64::try_from(plan.sequence()).map_err(|_| rejected("TRADING_FACT_SEQUENCE"))?;
        let tx = self.begin_locked(binding).await?;
        let head = head(&tx, binding).await?;
        let prior = if seq > 1 { record_at(&tx, binding.key(), seq - 1).await? } else { None };
        if prior.as_ref().map(|r| (r.prepared().id(), r.prepared().payload_fingerprint())) != facts.predecessor()
            || prior.as_ref().is_some_and(|r| !r.ready())
        {
            return Err(rejected("TRADING_FACT_PREDECESSOR_CONFLICT"));
        }
        let existing = record_at(&tx, binding.key(), seq).await?;
        let record = match existing {
            Some(row) if row.prepared() == plan && head >= plan.sequence() => row,
            Some(_) => return Err(rejected("TRADING_FACT_CONFLICT")),
            None => {
                if plan.predecessor_sequence() != head || (head != 0 && prior.is_none()) {
                    return Err(rejected("TRADING_FACT_PREDECESSOR_CONFLICT"));
                }
                let raw = String::from_utf8(plan.encode().map_err(|_| rejected("TRADING_FACT_BODY"))?)
                    .map_err(|_| rejected("TRADING_FACT_BODY"))?;
                let input = plan.input()["input_id"].as_str().ok_or_else(|| rejected("TRADING_FACT_IDENTITY"))?;
                tx.execute("INSERT INTO public.trading_fact (scope_key,sequence,transaction_id,input_id,
                    configuration_fingerprint,payload_fingerprint,prepared) VALUES ($1,$2,$3,$4,$5,$6,$7)",
                    &[&binding.key(), &seq, &plan.id(), &input, &plan.configuration_fingerprint(),
                    &plan.payload_fingerprint(), &raw]).await.map_err(database)?;
                record_at(&tx, binding.key(), seq).await?.ok_or_else(|| rejected("TRADING_FACT_MISSING"))?
            }
        };
        let receipt = DurableCommitReceipt::from_record(facts, binding.fingerprint(), &record)?;
        finish_mutation(tx).await?;
        Ok(receipt)
    }
}
