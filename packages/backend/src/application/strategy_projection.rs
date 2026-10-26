//! Rebuild only catalog/audit projections from fresh verified immutable history.
use crate::application::frozen_strategy::{
    Error as HistoryError, FreezeRelation, FrozenStore, Inventory,
};
use crate::bootstrap::deployment::{self, SemanticStoreId};
use crate::persistence::authority_session::AuthoritySession;
use crate::persistence::postgres;
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::json;
use std::{
    collections::{BTreeMap, BTreeSet},
    fmt,
    time::{Duration, SystemTime},
};
use tokio_postgres::Transaction;
const ACTOR: &str = "onlyalpha-semantic-reconciler";
const COMMENT: &str = "reconstructed from verified immutable Freeze relation";
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ReconciliationError {
    History(HistoryError),
    Namespace(deployment::Error),
    Conflict,
    Unavailable,
    Authority,
    AuditInvalid,
    OutcomeUnknown,
}
impl ReconciliationError {
    pub fn code(self) -> &'static str {
        match self {
            Self::History(e) => e.code(),
            Self::Namespace(e) => e.code(),
            Self::Conflict => "STRATEGY_PROJECTION_CONFLICT",
            Self::Unavailable => "STRATEGY_PROJECTION_UNAVAILABLE",
            Self::Authority => "STRATEGY_AUTHORITY_UNAVAILABLE",
            Self::AuditInvalid => "STRATEGY_PROJECTION_AUDIT_INVALID",
            Self::OutcomeUnknown => "STRATEGY_PROJECTION_OUTCOME_UNKNOWN",
        }
    }
}
impl fmt::Display for ReconciliationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.code())
    }
}
impl std::error::Error for ReconciliationError {}
type Result<T> = std::result::Result<T, ReconciliationError>;
impl FrozenStore {
    /// A controlled startup/upgrade operation, not Node READY or new Freeze admission.
    /// Any failed/cancelled operation revokes the original physical session. Only a
    /// fresh startup may re-observe an uncertain committed projection.
    pub async fn reconcile(
        &self,
        session: &mut AuthoritySession,
        namespace: &SemanticStoreId,
        audit_at: &str,
        max_rows: usize,
        max_work: usize,
    ) -> Result<()> {
        let mut owned = session.take_ownership();
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            self.reconcile_owned(&mut owned, namespace, audit_at, max_rows, max_work),
        )
        .await
        .map_err(|_| ReconciliationError::Unavailable)
        .and_then(|r| r);
        if result.is_ok() {
            session.restore_ownership(owned);
        }
        result
    }
    async fn reconcile_owned(
        &self,
        owned: &mut AuthoritySession,
        namespace: &SemanticStoreId,
        audit_at: &str,
        max_rows: usize,
        max_work: usize,
    ) -> Result<()> {
        let at: OnlyUtcDateTime = audit_at
            .parse()
            .map_err(|_| ReconciliationError::AuditInvalid)?;
        let selected = self.namespace().map_err(ReconciliationError::Namespace)?;
        if &selected != namespace {
            return Err(ReconciliationError::Namespace(deployment::Error::Mismatch));
        }
        let inventory = self
            .inventory(owned, max_work)
            .await
            .map_err(ReconciliationError::History)?;
        let targets = targets(&inventory)?;
        let client = owned
            .client_mut()
            .await
            .map_err(|_| ReconciliationError::Authority)?;
        let tx = client
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::Serializable)
            .start()
            .await
            .map_err(|_| ReconciliationError::Unavailable)?;
        // pg_temp is explicit and after pg_catalog, including type resolution.
        tx.batch_execute("SET LOCAL search_path=pg_catalog,pg_temp")
            .await
            .map_err(|_| ReconciliationError::Unavailable)?;
        postgres::bounds(&tx)
            .await
            .map_err(|_| ReconciliationError::Unavailable)?;
        deployment::verify_binding_in_transaction(&tx, namespace)
            .await
            .map_err(ReconciliationError::Namespace)?;
        let mut budget = Budget {
            rows: max_rows,
            bytes: max_work,
        };
        let mut expected = load(&tx, &mut budget).await?;
        validate(&expected, &inventory, namespace)?;
        let timestamp = postgres::system_time(at).map_err(|_| ReconciliationError::AuditInvalid)?;
        for id in inventory.revisions().keys() {
            if !expected.catalogs.contains_key(id) {
                tx.execute("INSERT INTO public.strategy_catalog(strategy_fingerprint,semantic_namespace_id,schema_version,created_at) VALUES($1,$2::pg_catalog.text::pg_catalog.uuid,1,$3) ON CONFLICT(strategy_fingerprint) DO NOTHING",&[id,&namespace.value(),&timestamp]).await.map_err(|_|ReconciliationError::Unavailable)?;
                expected.catalogs.insert(
                    id.clone(),
                    Catalog {
                        namespace: namespace.value().into(),
                        at,
                        display: None,
                        family: None,
                    },
                );
            }
        }
        for relation in targets {
            if !expected.audits.contains_key(relation.fingerprint()) {
                let v = relation.to_record();
                let provenance = strings(&v["research_execution_evidence_fingerprints"])?;
                let equivalence = strings(&v["equivalence_evidence_fingerprints"])?;
                let candidate = text(&v["candidate_fingerprint"])?;
                let result = text(&v["research_result_fingerprint"])?;
                let admission = text(&v["admission_evidence_fingerprint"])?;
                tx.execute("INSERT INTO public.strategy_freeze_record(freeze_record_fingerprint,candidate_fingerprint,research_result_fingerprint,research_execution_evidence_fingerprints,strategy_fingerprint,admission_evidence_fingerprint,equivalence_evidence_fingerprints,actor,created_at,comment,schema_version) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,4) ON CONFLICT(candidate_fingerprint,research_result_fingerprint,strategy_fingerprint) DO NOTHING",&[&relation.fingerprint(),&candidate,&result,&provenance,&relation.strategy_fingerprint(),&admission,&equivalence,&ACTOR,&timestamp,&COMMENT]).await.map_err(|_|ReconciliationError::Unavailable)?;
                expected.audits.insert(
                    relation.fingerprint().into(),
                    Audit {
                        relation: (*relation).clone(),
                        actor: ACTOR.into(),
                        at,
                        comment: Some(COMMENT.into()),
                    },
                );
            }
        }
        // Drain deferred mutations before the final proof; no business writes follow.
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
            .await
            .map_err(|_| ReconciliationError::Unavailable)?;
        let actual = load(&tx, &mut budget).await?;
        validate(&actual, &inventory, namespace)?;
        if actual != expected {
            return Err(ReconciliationError::Conflict);
        }
        deployment::verify_binding_in_transaction(&tx, namespace)
            .await
            .map_err(ReconciliationError::Namespace)?;
        tx.commit()
            .await
            .map_err(|_| ReconciliationError::OutcomeUnknown)?;
        owned
            .verify()
            .await
            .map_err(|_| ReconciliationError::Authority)?;
        Ok(())
    }
}
fn targets(inventory: &Inventory) -> Result<Vec<&FreezeRelation>> {
    let mut triples = BTreeSet::new();
    let mut result = Vec::new();
    for relation in inventory.relations().values() {
        let v = relation.to_record();
        let triple = (
            text(&v["candidate_fingerprint"])?.to_owned(),
            text(&v["research_result_fingerprint"])?.to_owned(),
            relation.strategy_fingerprint().to_owned(),
        );
        if !triples.insert(triple) {
            return Err(ReconciliationError::Conflict);
        }
        if inventory
            .revisions()
            .contains_key(relation.strategy_fingerprint())
        {
            result.push(relation);
        }
    }
    Ok(result)
}
#[derive(Clone, Debug, PartialEq, Eq)]
struct Catalog {
    namespace: String,
    at: OnlyUtcDateTime,
    display: Option<String>,
    family: Option<String>,
}
#[derive(Clone, Debug, PartialEq, Eq)]
struct Audit {
    relation: FreezeRelation,
    actor: String,
    at: OnlyUtcDateTime,
    comment: Option<String>,
}
#[derive(Debug, PartialEq, Eq)]
struct Projection {
    catalogs: BTreeMap<String, Catalog>,
    audits: BTreeMap<String, Audit>,
}
struct Budget {
    rows: usize,
    bytes: usize,
}
impl Budget {
    fn limit(&self) -> Result<i64> {
        i64::try_from(
            self.rows
                .checked_add(1)
                .ok_or(ReconciliationError::Unavailable)?,
        )
        .map_err(|_| ReconciliationError::Unavailable)
    }
    fn take(&mut self, rows: usize, bytes: usize) -> Result<()> {
        self.rows = self
            .rows
            .checked_sub(rows)
            .ok_or(ReconciliationError::Unavailable)?;
        self.bytes = self
            .bytes
            .checked_sub(bytes)
            .ok_or(ReconciliationError::Unavailable)?;
        Ok(())
    }
    fn string(
        &mut self,
        row: &tokio_postgres::Row,
        name: &str,
        optional: bool,
    ) -> Result<Option<String>> {
        let len: Option<i32> = row
            .try_get(format!("{name}_len").as_str())
            .map_err(|_| ReconciliationError::Conflict)?;
        let value: Option<String> = row
            .try_get(name)
            .map_err(|_| ReconciliationError::Conflict)?;
        match (len, value) {
            (None, None) if optional => Ok(None),
            (Some(n), Some(s)) if n >= 0 && n as usize == s.len() => {
                self.take(0, s.len())?;
                Ok(Some(s))
            }
            (Some(n), _) if n >= 0 && n as usize > self.bytes => {
                Err(ReconciliationError::Unavailable)
            }
            _ => Err(ReconciliationError::Conflict),
        }
    }
}
fn required(v: Option<String>) -> Result<String> {
    v.ok_or(ReconciliationError::Conflict)
}
fn time(row: &tokio_postgres::Row) -> Result<OnlyUtcDateTime> {
    let at: SystemTime = row
        .try_get("created_at")
        .map_err(|_| ReconciliationError::Conflict)?;
    postgres::datetime(at).map_err(|_| ReconciliationError::Conflict)
}
fn text(v: &serde_json::Value) -> Result<&str> {
    v.as_str().ok_or(ReconciliationError::Conflict)
}
fn strings(v: &serde_json::Value) -> Result<Vec<String>> {
    v.as_array()
        .ok_or(ReconciliationError::Conflict)?
        .iter()
        .map(|v| text(v).map(str::to_owned))
        .collect()
}
async fn load(tx: &Transaction<'_>, budget: &mut Budget) -> Result<Projection> {
    let limit = budget.limit()?;
    let bytes = i64::try_from(budget.bytes).map_err(|_| ReconciliationError::Unavailable)?;
    preflight(tx,budget,"SELECT pg_catalog.count(*) AS rows, COALESCE(pg_catalog.sum(COALESCE(pg_catalog.octet_length(selected.strategy_fingerprint::pg_catalog.text),0)::pg_catalog.int8 + COALESCE(pg_catalog.octet_length(selected.semantic_namespace_id::pg_catalog.text),0)::pg_catalog.int8 + COALESCE(pg_catalog.octet_length(selected.display_name::pg_catalog.text),0)::pg_catalog.int8 + COALESCE(pg_catalog.octet_length(selected.catalog_family::pg_catalog.text),0)::pg_catalog.int8),0)::pg_catalog.text AS bytes FROM (SELECT * FROM public.strategy_catalog ORDER BY strategy_fingerprint COLLATE pg_catalog.\"C\" LIMIT $1) AS selected").await?;
    let rows=tx.query("SELECT pg_catalog.octet_length(strategy_fingerprint::pg_catalog.text) AS id_len, CASE WHEN pg_catalog.octet_length(strategy_fingerprint::pg_catalog.text)=64 THEN strategy_fingerprint::pg_catalog.text END AS id, pg_catalog.octet_length(semantic_namespace_id::pg_catalog.text) AS namespace_len, CASE WHEN pg_catalog.octet_length(semantic_namespace_id::pg_catalog.text)=36 THEN semantic_namespace_id::pg_catalog.text END AS namespace, schema_version,created_at,pg_catalog.octet_length(display_name) AS display_len, CASE WHEN pg_catalog.octet_length(display_name)<=$2::pg_catalog.int8 THEN display_name END AS display, pg_catalog.octet_length(catalog_family) AS family_len, CASE WHEN pg_catalog.octet_length(catalog_family)<=$2::pg_catalog.int8 THEN catalog_family END AS family FROM public.strategy_catalog ORDER BY strategy_fingerprint COLLATE pg_catalog.\"C\" LIMIT $1",&[&limit,&bytes]).await.map_err(|_|ReconciliationError::Unavailable)?;
    budget.take(rows.len(), 0)?;
    let mut catalogs = BTreeMap::new();
    for row in rows {
        let id = required(budget.string(&row, "id", false)?)?;
        let namespace = required(budget.string(&row, "namespace", false)?)?;
        if !crate::is_sha256_hex(&id)
            || SemanticStoreId::new(&namespace).is_err()
            || row
                .try_get::<_, i32>("schema_version")
                .map_err(|_| ReconciliationError::Conflict)?
                != 1
        {
            return Err(ReconciliationError::Conflict);
        }
        let catalog = Catalog {
            namespace,
            at: time(&row)?,
            display: budget.string(&row, "display", true)?,
            family: budget.string(&row, "family", true)?,
        };
        if catalogs.insert(id, catalog).is_some() {
            return Err(ReconciliationError::Conflict);
        }
    }
    let limit = budget.limit()?;
    let bytes = i64::try_from(budget.bytes).map_err(|_| ReconciliationError::Unavailable)?;
    let refs = bytes / 64;
    preflight(tx,budget,"SELECT pg_catalog.count(*) AS rows, COALESCE(pg_catalog.sum(COALESCE(pg_catalog.octet_length(selected.freeze_record_fingerprint::pg_catalog.text),0)::pg_catalog.int8 + COALESCE(pg_catalog.octet_length(selected.candidate_fingerprint::pg_catalog.text),0)::pg_catalog.int8 + COALESCE(pg_catalog.octet_length(selected.research_result_fingerprint::pg_catalog.text),0)::pg_catalog.int8 + COALESCE(pg_catalog.octet_length(selected.strategy_fingerprint::pg_catalog.text),0)::pg_catalog.int8 + COALESCE(pg_catalog.octet_length(selected.admission_evidence_fingerprint::pg_catalog.text),0)::pg_catalog.int8 + COALESCE(pg_catalog.octet_length(selected.actor::pg_catalog.text),0)::pg_catalog.int8 + COALESCE(pg_catalog.octet_length(selected.comment::pg_catalog.text),0)::pg_catalog.int8 + (SELECT COALESCE(pg_catalog.sum(GREATEST(pg_catalog.octet_length(v),64)::pg_catalog.int8),0) FROM pg_catalog.unnest(selected.research_execution_evidence_fingerprints) AS v) + (SELECT COALESCE(pg_catalog.sum(GREATEST(pg_catalog.octet_length(v),64)::pg_catalog.int8),0) FROM pg_catalog.unnest(selected.equivalence_evidence_fingerprints) AS v)),0)::pg_catalog.text AS bytes FROM (SELECT * FROM public.strategy_freeze_record ORDER BY freeze_record_fingerprint COLLATE pg_catalog.\"C\" LIMIT $1) AS selected").await?;
    let rows=tx.query("SELECT pg_catalog.octet_length(freeze_record_fingerprint) AS id_len, CASE WHEN pg_catalog.octet_length(freeze_record_fingerprint)=64 THEN freeze_record_fingerprint END AS id, pg_catalog.octet_length(candidate_fingerprint) AS candidate_len, CASE WHEN pg_catalog.octet_length(candidate_fingerprint)=64 THEN candidate_fingerprint END AS candidate, pg_catalog.octet_length(research_result_fingerprint) AS result_len, CASE WHEN pg_catalog.octet_length(research_result_fingerprint)=64 THEN research_result_fingerprint END AS result, pg_catalog.octet_length(strategy_fingerprint) AS strategy_len, CASE WHEN pg_catalog.octet_length(strategy_fingerprint)=64 THEN strategy_fingerprint END AS strategy, pg_catalog.octet_length(admission_evidence_fingerprint) AS admission_len, CASE WHEN pg_catalog.octet_length(admission_evidence_fingerprint)=64 THEN admission_evidence_fingerprint END AS admission, pg_catalog.cardinality(research_execution_evidence_fingerprints) AS provenance_count, CASE WHEN pg_catalog.cardinality(research_execution_evidence_fingerprints)<=$3::pg_catalog.int8 AND NOT EXISTS(SELECT 1 FROM pg_catalog.unnest(research_execution_evidence_fingerprints) AS v WHERE v IS NULL OR pg_catalog.octet_length(v)<>64) THEN research_execution_evidence_fingerprints END AS provenance, pg_catalog.cardinality(equivalence_evidence_fingerprints) AS equivalence_count, CASE WHEN pg_catalog.cardinality(equivalence_evidence_fingerprints)<=$3::pg_catalog.int8 AND NOT EXISTS(SELECT 1 FROM pg_catalog.unnest(equivalence_evidence_fingerprints) AS v WHERE v IS NULL OR pg_catalog.octet_length(v)<>64) THEN equivalence_evidence_fingerprints END AS equivalence, pg_catalog.octet_length(actor) AS actor_len, CASE WHEN pg_catalog.octet_length(actor)<=$2::pg_catalog.int8 THEN actor END AS actor,created_at,pg_catalog.octet_length(comment) AS comment_len, CASE WHEN pg_catalog.octet_length(comment)<=$2::pg_catalog.int8 THEN comment END AS comment,schema_version FROM public.strategy_freeze_record ORDER BY freeze_record_fingerprint COLLATE pg_catalog.\"C\" LIMIT $1",&[&limit,&bytes,&refs]).await.map_err(|_|ReconciliationError::Unavailable)?;
    budget.take(rows.len(), 0)?;
    let mut audits = BTreeMap::new();
    let mut triples = BTreeSet::new();
    for row in rows {
        if row
            .try_get::<_, i32>("schema_version")
            .map_err(|_| ReconciliationError::Conflict)?
            != 4
        {
            return Err(ReconciliationError::Conflict);
        }
        let id = required(budget.string(&row, "id", false)?)?;
        let candidate = required(budget.string(&row, "candidate", false)?)?;
        let result = required(budget.string(&row, "result", false)?)?;
        let strategy = required(budget.string(&row, "strategy", false)?)?;
        let admission = required(budget.string(&row, "admission", false)?)?;
        let provenance = evidence(&row, "provenance", budget)?;
        let equivalence = evidence(&row, "equivalence", budget)?;
        let relation=FreezeRelation::from_json(&json!({"schema_version":1,"relation_fingerprint":id,"candidate_fingerprint":candidate,"research_result_fingerprint":result,"strategy_fingerprint":strategy,"admission_evidence_fingerprint":admission,"research_execution_evidence_fingerprints":provenance,"equivalence_evidence_fingerprints":equivalence}).to_string(),8*1024*1024).map_err(|_|ReconciliationError::Conflict)?;
        if !triples.insert((candidate, result, strategy)) {
            return Err(ReconciliationError::Conflict);
        }
        let actor = required(budget.string(&row, "actor", false)?)?;
        if !actor
            .chars()
            .any(|c| !(c.is_whitespace() || matches!(c, '\u{1c}'..='\u{1f}')))
        {
            return Err(ReconciliationError::Conflict);
        }
        let audit = Audit {
            relation,
            actor,
            at: time(&row)?,
            comment: budget.string(&row, "comment", true)?,
        };
        if audits.insert(id, audit).is_some() {
            return Err(ReconciliationError::Conflict);
        }
    }
    Ok(Projection { catalogs, audits })
}
fn evidence(row: &tokio_postgres::Row, name: &str, budget: &mut Budget) -> Result<Vec<String>> {
    let count: i32 = row
        .try_get(format!("{name}_count").as_str())
        .map_err(|_| ReconciliationError::Conflict)?;
    if count < 0 {
        return Err(ReconciliationError::Conflict);
    }
    budget.take(
        0,
        (count as usize)
            .checked_mul(64)
            .ok_or(ReconciliationError::Unavailable)?,
    )?;
    let values: Vec<String> = row
        .try_get(name)
        .map_err(|_| ReconciliationError::Conflict)?;
    if values.len() != count as usize {
        return Err(ReconciliationError::Conflict);
    }
    Ok(values)
}
fn validate(
    projection: &Projection,
    inventory: &Inventory,
    namespace: &SemanticStoreId,
) -> Result<()> {
    for (id, catalog) in &projection.catalogs {
        if catalog.namespace != namespace.value() || !inventory.revisions().contains_key(id) {
            return Err(ReconciliationError::Conflict);
        }
    }
    for (id, audit) in &projection.audits {
        if inventory.relations().get(id) != Some(&audit.relation)
            || !inventory
                .revisions()
                .contains_key(audit.relation.strategy_fingerprint())
            || !projection
                .catalogs
                .contains_key(audit.relation.strategy_fingerprint())
        {
            return Err(ReconciliationError::Conflict);
        }
    }
    Ok(())
}

/// Transfer only fixed-size count/length metadata before collecting payloads.
/// Serializable snapshot + no writes between this proof and SELECT preserve it.
async fn preflight(tx: &Transaction<'_>, budget: &Budget, sql: &str) -> Result<()> {
    let limit = budget.limit()?;
    let row = tx
        .query_one(sql, &[&limit])
        .await
        .map_err(|_| ReconciliationError::Unavailable)?;
    let rows: i64 = row
        .try_get("rows")
        .map_err(|_| ReconciliationError::Conflict)?;
    let bytes: String = row
        .try_get("bytes")
        .map_err(|_| ReconciliationError::Conflict)?;
    let used: usize = bytes
        .parse()
        .map_err(|_| ReconciliationError::Unavailable)?;
    if rows < 0
        || usize::try_from(rows).map_err(|_| ReconciliationError::Unavailable)? > budget.rows
        || used > budget.bytes
    {
        return Err(ReconciliationError::Unavailable);
    }
    Ok(())
}
