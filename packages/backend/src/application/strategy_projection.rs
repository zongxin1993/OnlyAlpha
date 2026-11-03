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
        let mut expected = load(&tx, &mut budget, &inventory).await?;
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
                insert_audit(&tx,relation,ACTOR,at,Some(COMMENT)).await?;
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
        let actual = load(&tx, &mut budget, &inventory).await?;
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
        let triple=if v["schema_version"]==2 {
            ("MANUAL_BACKTEST".to_owned(),text(&v["origin"]["preparation_command_id"])?.to_owned(),text(&v["origin"]["strategy_validation_fingerprint"])?.to_owned(),relation.strategy_fingerprint().to_owned())
        }else {
            ("RESEARCH".to_owned(),text(&v["candidate_fingerprint"])?.to_owned(),text(&v["research_result_fingerprint"])?.to_owned(),relation.strategy_fingerprint().to_owned())
        };
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
async fn load(tx: &Transaction<'_>, budget: &mut Budget, inventory:&Inventory) -> Result<Projection> {
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
    let limit=budget.limit()?;
    let bytes=i64::try_from(budget.bytes).map_err(|_|ReconciliationError::Unavailable)?;
    preflight(tx,budget,"SELECT pg_catalog.count(*) AS rows,COALESCE(pg_catalog.sum(pg_catalog.octet_length(pg_catalog.to_jsonb(selected)::pg_catalog.text)),0)::pg_catalog.text AS bytes FROM (SELECT * FROM public.strategy_freeze_record ORDER BY freeze_record_fingerprint COLLATE pg_catalog.\"C\" LIMIT $1) AS selected").await?;
    let rows=tx.query("SELECT CASE WHEN pg_catalog.octet_length(pg_catalog.to_jsonb(f)::pg_catalog.text)<=$2::pg_catalog.int8 THEN pg_catalog.to_jsonb(f)::pg_catalog.text END AS record,f.created_at FROM public.strategy_freeze_record f ORDER BY freeze_record_fingerprint COLLATE pg_catalog.\"C\" LIMIT $1",&[&limit,&bytes]).await.map_err(|_|ReconciliationError::Unavailable)?;
    budget.take(rows.len(),0)?;
    let mut audits=BTreeMap::new();let mut triples=BTreeSet::new();
    for row in rows {
        let raw:String=row.try_get("record").map_err(|_|ReconciliationError::Conflict)?;
        budget.take(0,raw.len())?;
        let value:serde_json::Value=serde_json::from_str(&raw).map_err(|_|ReconciliationError::Conflict)?;
        let id=text(&value["freeze_record_fingerprint"])?;let strategy=text(&value["strategy_fingerprint"])?;
        if !crate::is_sha256_hex(id)||!crate::is_sha256_hex(strategy){return Err(ReconciliationError::Conflict);}
        let (relation,triple)=match value["schema_version"].as_u64() {
            Some(4)=>{
                if value["origin_kind"]!="RESEARCH"||!value["preparation_command_id"].is_null()||!value["strategy_validation_fingerprint"].is_null(){return Err(ReconciliationError::Conflict);}
                let candidate=text(&value["candidate_fingerprint"])?;let result=text(&value["research_result_fingerprint"])?;
                let relation=FreezeRelation::from_json(&json!({"schema_version":1,"relation_fingerprint":id,"candidate_fingerprint":candidate,"research_result_fingerprint":result,"strategy_fingerprint":strategy,
                    "admission_evidence_fingerprint":value["admission_evidence_fingerprint"],"research_execution_evidence_fingerprints":value["research_execution_evidence_fingerprints"],"equivalence_evidence_fingerprints":value["equivalence_evidence_fingerprints"]}).to_string(),8*1024*1024).map_err(|_|ReconciliationError::Conflict)?;
                (relation,("RESEARCH".to_owned(),candidate.to_owned(),result.to_owned(),strategy.to_owned()))
            },
            Some(5)=>{
                if value["origin_kind"]!="MANUAL_BACKTEST"{return Err(ReconciliationError::Conflict);}
                for key in ["candidate_fingerprint","research_result_fingerprint","admission_evidence_fingerprint","research_execution_evidence_fingerprints","equivalence_evidence_fingerprints"] {if !value[key].is_null(){return Err(ReconciliationError::Conflict);}}
                let relation=inventory.relations().get(id).ok_or(ReconciliationError::Conflict)?;
                let original=relation.to_record();
                if original["schema_version"]!=2||original["origin"]["kind"]!="MANUAL_BACKTEST"||relation.strategy_fingerprint()!=strategy
                    ||original["origin"]["preparation_command_id"]!=value["preparation_command_id"]||original["origin"]["strategy_validation_fingerprint"]!=value["strategy_validation_fingerprint"] {return Err(ReconciliationError::Conflict);}
                (relation.clone(),("MANUAL_BACKTEST".to_owned(),text(&value["preparation_command_id"])?.to_owned(),text(&value["strategy_validation_fingerprint"])?.to_owned(),strategy.to_owned()))
            },
            _=>return Err(ReconciliationError::Conflict),
        };
        if !triples.insert(triple){return Err(ReconciliationError::Conflict);}
        let actor=text(&value["actor"])?;
        if !actor.chars().any(|c|!(c.is_whitespace()||matches!(c,'\u{1c}'..='\u{1f}'))){return Err(ReconciliationError::Conflict);}
        let comment=if value["comment"].is_null(){None}else{Some(text(&value["comment"])?.to_owned())};
        let at=time(&row)?;
        let audit=Audit{relation,actor:actor.to_owned(),at,comment};
        if audits.insert(id.to_owned(),audit).is_some(){return Err(ReconciliationError::Conflict);}
    }
    Ok(Projection { catalogs, audits })
}
async fn insert_audit(tx:&Transaction<'_>,relation:&FreezeRelation,actor:&str,at:OnlyUtcDateTime,comment:Option<&str>)->Result<()> {
    let value=relation.to_record();let timestamp=postgres::system_time(at).map_err(|_|ReconciliationError::AuditInvalid)?;
    if value["schema_version"]==2 {
        let origin=&value["origin"];
        tx.execute("INSERT INTO public.strategy_freeze_record(freeze_record_fingerprint,strategy_fingerprint,actor,created_at,comment,schema_version,origin_kind,preparation_command_id,strategy_validation_fingerprint) VALUES($1,$2,$3,$4,$5,5,'MANUAL_BACKTEST',$6::pg_catalog.text::pg_catalog.uuid,$7) ON CONFLICT DO NOTHING",&[&relation.fingerprint(),&relation.strategy_fingerprint(),&actor,&timestamp,&comment,&text(&origin["preparation_command_id"])?,&text(&origin["strategy_validation_fingerprint"])?]).await.map_err(|_|ReconciliationError::Unavailable)?;
    }else {
        let provenance=strings(&value["research_execution_evidence_fingerprints"])?;let equivalence=strings(&value["equivalence_evidence_fingerprints"])?;
        tx.execute("INSERT INTO public.strategy_freeze_record(freeze_record_fingerprint,candidate_fingerprint,research_result_fingerprint,research_execution_evidence_fingerprints,strategy_fingerprint,admission_evidence_fingerprint,equivalence_evidence_fingerprints,actor,created_at,comment,schema_version) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,4) ON CONFLICT DO NOTHING",&[&relation.fingerprint(),&text(&value["candidate_fingerprint"])?,&text(&value["research_result_fingerprint"])?,&provenance,&relation.strategy_fingerprint(),&text(&value["admission_evidence_fingerprint"])?,&equivalence,&actor,&timestamp,&comment]).await.map_err(|_|ReconciliationError::Unavailable)?;
    }Ok(())
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

// Durable Freeze commands reuse this owner for their complete catalog/audit cut.
use crate::application::command::{
    Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Receipt,
};
use crate::application::factor_content::hash;
use crate::application::frozen_strategy::FrozenPlan;
use crate::persistence::postgres::Commands as GlobalCommands;
use crate::persistence::research_evidence::VerifiedStrategyResearch;
use crate::security::human_access;
use serde_json::Value;
type FreezeResult<T> = std::result::Result<T, &'static str>;
const FREEZE_INVALID: &str = "STRATEGY_FREEZE_INVALID";
const FREEZE_CORRUPT: &str = "STRATEGY_FREEZE_ADMISSION_CORRUPT";
const FREEZE_UNAVAILABLE: &str = "STRATEGY_FREEZE_AUTHORITY_UNAVAILABLE";
const FREEZE_UNKNOWN: &str = "STRATEGY_FREEZE_COMMAND_UNKNOWN";
const FREEZE_CONFLICT: &str = "PRODUCT_COMMAND_CONFLICT";
const FREEZE_DENIED: &str = "STRATEGY_FREEZE_ACCESS_DENIED";
fn freeze_db(_: impl fmt::Debug) -> &'static str {
    FREEZE_UNAVAILABLE
}
fn freeze_command(error: crate::application::command::Error) -> &'static str {
    match error {
        crate::application::command::Error::Conflict => FREEZE_CONFLICT,
        crate::application::command::Error::Unavailable => FREEZE_UNAVAILABLE,
        _ => FREEZE_CORRUPT,
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
enum FreezeOrigin {
    Research{run:String,candidate:String},
    Manual{preparation:String,validation:String},
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct FreezeRequest {command:CommandId,origin:FreezeOrigin,comment:Option<String>}
impl FreezeRequest {
    pub(crate) fn new(command:CommandId,run:&str,candidate:&str,comment:Option<&str>)->FreezeResult<Self> {
        if !crate::application::command::uuid4(run)||!crate::is_sha256_hex(candidate)||comment.is_some_and(|v|v.len()>4096||v.contains('\0')){return Err(FREEZE_INVALID);}
        Ok(Self{command,origin:FreezeOrigin::Research{run:run.into(),candidate:candidate.into()},comment:comment.map(str::to_owned)})
    }
    fn manual(command:CommandId,preparation:&str,validation:&str,comment:Option<&str>)->FreezeResult<Self> {
        if !crate::application::command::uuid4(preparation)||!crate::is_sha256_hex(validation)||comment.is_some_and(|v|v.len()>4096||v.contains('\0')){return Err(FREEZE_INVALID);}
        Ok(Self{command,origin:FreezeOrigin::Manual{preparation:preparation.into(),validation:validation.into()},comment:comment.map(str::to_owned)})
    }
    pub(crate) fn run_id(&self)->FreezeResult<&str> {match &self.origin {FreezeOrigin::Research{run,..}=>Ok(run),_=>Err(FREEZE_INVALID)}}
    fn view(&self)->Value {match &self.origin {
        FreezeOrigin::Research{run,candidate}=>json!({"research_run_id":run,"candidate_fingerprint":candidate,"comment":self.comment}),
        FreezeOrigin::Manual{preparation,validation}=>json!({"origin":{"kind":"MANUAL_BACKTEST","preparation_command_id":preparation,"strategy_validation_fingerprint":validation},"comment":self.comment}),
    }}
    fn fingerprint(&self,actor:&str)->FreezeResult<String> {
        let mut record=self.view();record["actor"]=json!(actor);hash(&record)
    }
    fn admission(&self,actor:&str)->FreezeResult<Admission> {Admission::new(self.command.clone(),CommandKind::FreezeStrategy,&self.fingerprint(actor)?).map_err(freeze_command)}
    fn matches(&self,plan:&FrozenPlan<'_>)->bool {match &self.origin {
        FreezeOrigin::Research{run,candidate}=>plan.research_evidence().is_some_and(|e|run==e.run_id()&&candidate==e.candidate_fingerprint()),
        FreezeOrigin::Manual{preparation,validation}=>plan.manual_evidence().is_some_and(|e|preparation==e.preparation_command_id()&&validation==e.fingerprint()),
    }}
}
#[derive(Clone, Debug, PartialEq, Eq)]
struct FreezeCompletion {
    strategy: String,
    relation: String,
    published: OnlyUtcDateTime,
    completed: OnlyUtcDateTime,
}
/// No constructor, deserializer or mutable fields outside the Command owner.
/// Only an exact committed PREPARED row can grant physical publication.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct PreparedFreeze {
    request: FreezeRequest,
    actor: String,
    admission: Admission,
    prepared_at: OnlyUtcDateTime,
    completion: Option<FreezeCompletion>,
    namespace: SemanticStoreId,
}
impl PreparedFreeze {
    pub(crate) fn matches(&self, plan: &FrozenPlan<'_>) -> bool {
        self.completion.is_none() && self.request.matches(plan)
    }
    pub(crate) fn namespace(&self) -> &SemanticStoreId {
        &self.namespace
    }
}
/// Human policy and the Host's current write admission precede construction.
/// This retains the exact physical mutation session; no alternate DB connection.
pub(crate) struct Freezes<'a> {
    session: &'a mut AuthoritySession,
    store: &'a FrozenStore,
    namespace: &'a SemanticStoreId,
    human: &'a human_access::Session,
    #[cfg(test)]
    stop: Option<FreezeBoundary>,
}
impl<'a> Freezes<'a> {
    pub(crate) fn new(
        session: &'a mut AuthoritySession,
        store: &'a FrozenStore,
        namespace: &'a SemanticStoreId,
        human: &'a human_access::Session,
    ) -> Self {
        Self {
            session,
            store,
            namespace,
            human,
            #[cfg(test)]
            stop: None,
        }
    }
    /// Return the stored request for original-Command recovery; this value grants
    /// no publication right. The owning reader must re-verify its exact Run.
    #[cfg(test)]
    pub(crate) async fn original_request(
        &mut self,
        id: &CommandId,
    ) -> FreezeResult<Option<FreezeRequest>> {
        let actor = self.human.subject_id().map_err(|_| FREEZE_DENIED)?;
        let client = self.session.client_mut().await.map_err(freeze_db)?;
        let tx = client.transaction().await.map_err(freeze_db)?;
        freeze_transaction(&tx, self.namespace).await?;
        GlobalCommands::lock_command(&tx, id)
            .await
            .map_err(freeze_command)?;
        let original = freeze_bound(&tx, id, actor, self.namespace).await?;
        self.human.subject_id().map_err(|_| FREEZE_DENIED)?;
        tx.commit().await.map_err(freeze_db)?;
        Ok(original.map(|v| v.request))
    }
    pub(crate) async fn execute(
        &mut self,
        request: &FreezeRequest,
        evidence: &VerifiedStrategyResearch,
        audit_at: &str,
        max_rows: usize,
        max_work: usize,
    ) -> FreezeResult<Value> {
        let plan=FrozenPlan::from_verified(evidence).map_err(|e|e.code())?;
        self.execute_plan(request,&plan,audit_at,max_rows,max_work).await
    }
    pub(crate) async fn execute_manual(&mut self,evidence:&crate::persistence::strategy_validation::VerifiedValidation,original:&crate::persistence::research_preparation::Operation,audit_at:&str,max_rows:usize,max_work:usize)->FreezeResult<Value> {
        let origin=crate::application::strategy_validation::Origin::from_operation(original)?;
        if origin.record()!=evidence.record()["prepared_inputs"]["origin"] || self.human.subject_id().map_err(|_|FREEZE_DENIED)?!=original.owner{return Err(FREEZE_INVALID);}
        let command=crate::persistence::research_preparation::child_command(&original.command,"manual-backtest-freeze")?;
        let request=FreezeRequest::manual(command,evidence.preparation_command_id(),evidence.fingerprint(),None)?;
        let plan=FrozenPlan::from_validation(evidence).map_err(|e|e.code())?;
        self.execute_plan(&request,&plan,audit_at,max_rows,max_work).await
    }
    async fn execute_plan(&mut self,request:&FreezeRequest,plan:&FrozenPlan<'_>,audit_at:&str,max_rows:usize,max_work:usize)->FreezeResult<Value> {
        let actor=self.human.subject_id().map_err(|_|FREEZE_DENIED)?.to_owned();
        if !request.matches(plan){return Err(FREEZE_INVALID);}
        let at: OnlyUtcDateTime = audit_at.parse().map_err(|_| FREEZE_INVALID)?;
        if &self.store.namespace().map_err(|e| e.code())? != self.namespace {
            return Err("RESEARCH_SEMANTIC_STORE_MISMATCH");
        }
        let mut owned = self.session.take_ownership();
        let result = tokio::time::timeout(
            Duration::from_secs(5),
            self.execute_owned(&mut owned, request, &actor, plan, at, max_rows, max_work),
        )
        .await
        .map_err(|_| FREEZE_UNKNOWN)
        .and_then(|r| r);
        if result.is_ok() {
            self.session.restore_ownership(owned);
        } else {
            let _ = owned.close().await;
        }
        result
    }
    #[allow(clippy::too_many_arguments)]
    async fn execute_owned(
        &self,
        owned: &mut AuthoritySession,
        request: &FreezeRequest,
        actor: &str,
        plan: &FrozenPlan<'_>,
        at: OnlyUtcDateTime,
        max_rows: usize,
        max_work: usize,
    ) -> FreezeResult<Value> {
        let prepared = {
            let client = owned.client_mut().await.map_err(freeze_db)?;
            let tx = client
                .build_transaction()
                .isolation_level(tokio_postgres::IsolationLevel::Serializable)
                .start()
                .await
                .map_err(freeze_db)?;
            freeze_transaction(&tx, self.namespace).await?;
            GlobalCommands::lock_command(&tx, &request.command)
                .await
                .map_err(freeze_command)?;
            let found = freeze_bound(&tx, &request.command, actor, self.namespace).await?;
            let new_admission=found.is_none();
            let value = match found {
                Some(value) => {
                    if value.request != *request || value.admission != request.admission(actor)? {
                        return Err(FREEZE_CONFLICT);
                    }
                    value
                }
                None => {
                    verify_freeze_plan(&tx,self.namespace,plan).await?;
                    require_new_manual_parent(&tx,plan).await?;
                    let admission = request.admission(actor)?;
                    GlobalCommands::admit_exact_in_transaction(&tx, &admission)
                        .await
                        .map_err(freeze_command)?;
                    let timestamp = postgres::system_time(at).map_err(freeze_command)?;
                    match &request.origin {
                        FreezeOrigin::Research{run,candidate}=>{tx.execute("INSERT INTO public.strategy_freeze_command_admission(command_id,command_fingerprint,research_run_id,candidate_fingerprint,actor,comment,state,prepared_at,schema_version) VALUES($1::pg_catalog.text::pg_catalog.uuid,$2,$3::pg_catalog.text::pg_catalog.uuid,$4,$5,$6,'PREPARED',$7,1)",&[&request.command.value(),&admission.fingerprint(),run,candidate,&actor,&request.comment,&timestamp]).await.map_err(freeze_db)?;},
                        FreezeOrigin::Manual{preparation,validation}=>{tx.execute("INSERT INTO public.strategy_freeze_command_admission(command_id,command_fingerprint,actor,comment,state,prepared_at,schema_version,origin_kind,preparation_command_id,strategy_validation_fingerprint) VALUES($1::pg_catalog.text::pg_catalog.uuid,$2,$3,$4,'PREPARED',$5,2,'MANUAL_BACKTEST',$6::pg_catalog.text::pg_catalog.uuid,$7)",&[&request.command.value(),&admission.fingerprint(),&actor,&request.comment,&timestamp,preparation,validation]).await.map_err(freeze_db)?;},
                    }
                    freeze_bound(&tx, &request.command, actor, self.namespace)
                        .await?
                        .ok_or(FREEZE_CORRUPT)?
                }
            };
            // Deferred effects must run before the final proof of the exact
            // durable capability; no business writes follow this readback.
            tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
                .await
                .map_err(freeze_db)?;
            if freeze_bound(&tx, &request.command, actor, self.namespace).await?
                != Some(value.clone())
            {
                return Err(FREEZE_CORRUPT);
            }
            verify_freeze_plan(&tx,self.namespace,plan).await?;
            if new_admission {require_new_manual_parent(&tx,plan).await?;}
            deployment::verify_binding_in_transaction(&tx, self.namespace)
                .await
                .map_err(|e| e.code())?;
            self.human.subject_id().map_err(|_| FREEZE_DENIED)?;
            plan.verify_cut().map_err(|e| e.code())?;
            AuthoritySession::verify_transaction(&tx).await.map_err(freeze_db)?;
            // An uncertain acknowledgement must return before any filesystem write.
            tx.commit().await.map_err(|_| FREEZE_UNKNOWN)?;
            value
        };
        #[cfg(test)]
        self.checkpoint(FreezeBoundary::Prepared)?;
        owned.verify().await.map_err(freeze_db)?;
        plan.verify_cut().map_err(|e| e.code())?;
        self.human.subject_id().map_err(|_| FREEZE_DENIED)?;
        if prepared.completion.is_none() {
            self.store
                .publish_relation(&prepared, plan, max_work)
                .map_err(|e| e.code())?;
            #[cfg(test)]
            self.checkpoint(FreezeBoundary::Relation)?;
            owned.verify().await.map_err(freeze_db)?;
            self.human.subject_id().map_err(|_| FREEZE_DENIED)?;
            self.store
                .publish_revision(&prepared, plan, max_work)
                .map_err(|e| e.code())?;
            #[cfg(test)]
            self.checkpoint(FreezeBoundary::Revision)?;
        }
        // Completed replay verifies physical history and projections; it never
        // repairs deleted/corrupt immutable bytes by re-publication.
        let inventory = self
            .store
            .inventory(owned, max_work)
            .await
            .map_err(|e| e.code())?;
        // The verified inventory owns the first immutable Source representation.
        // Later scientific occurrences may use different presentation aliases
        // for the same recomputed Strategy identity.
        if !inventory.revisions().contains_key(plan.revision().fingerprint())
            || inventory.relations().get(plan.relation().fingerprint()) != Some(plan.relation())
        {
            return Err("STRATEGY_CORRUPT");
        }
        targets(&inventory).map_err(|e| e.code())?;
        let manual_cut=plan.manual_evidence().map(|e|self.store.read_verified_manual(std::sync::Arc::new(e.clone()),plan.relation().fingerprint(),max_work)).transpose().map_err(|e|e.code())?;
        let client = owned.client_mut().await.map_err(freeze_db)?;
        let tx = client
            .build_transaction()
            .isolation_level(tokio_postgres::IsolationLevel::Serializable)
            .start()
            .await
            .map_err(freeze_db)?;
        freeze_transaction(&tx, self.namespace).await?;
        GlobalCommands::lock_command(&tx, &request.command)
            .await
            .map_err(freeze_command)?;
        let current = freeze_bound(&tx, &request.command, actor, self.namespace)
            .await?
            .ok_or(FREEZE_CORRUPT)?;
        if current != prepared {
            return Err(FREEZE_CORRUPT);
        }
        verify_freeze_plan(&tx,self.namespace,plan).await?;
        let mut budget = Budget {
            rows: max_rows,
            bytes: max_work,
        };
        let mut expected = load(&tx, &mut budget, &inventory).await.map_err(|e| e.code())?;
        validate(&expected, &inventory, self.namespace).map_err(|e| e.code())?;
        let id = plan.revision().fingerprint();
        let relation_id = plan.relation().fingerprint();
        let replayed = current.completion.is_some();
        let receipt = if let Some(complete) = &current.completion {
            if complete.strategy != id
                || complete.relation != relation_id
                || !expected.catalogs.contains_key(id)
                || !expected.audits.contains_key(relation_id)
            {
                return Err(FREEZE_CORRUPT);
            }
            GlobalCommands::load_verified_receipt_in_transaction(&tx, &request.command)
                .await
                .map_err(freeze_command)?
                .ok_or(FREEZE_CORRUPT)?
        } else {
            if at < current.prepared_at {
                return Err(FREEZE_INVALID);
            }
            let timestamp = postgres::system_time(at).map_err(freeze_command)?;
            if !expected.catalogs.contains_key(id) {
                tx.execute("INSERT INTO public.strategy_catalog(strategy_fingerprint,semantic_namespace_id,schema_version,created_at) VALUES($1,$2::pg_catalog.text::pg_catalog.uuid,1,$3)",&[&id,&self.namespace.value(),&timestamp]).await.map_err(freeze_db)?;
                expected.catalogs.insert(
                    id.into(),
                    Catalog {
                        namespace: self.namespace.value().into(),
                        at,
                        display: None,
                        family: None,
                    },
                );
            }
            if !expected.audits.contains_key(relation_id) {
                insert_audit(&tx,plan.relation(),actor,at,request.comment.as_deref()).await.map_err(|e|e.code())?;
                expected.audits.insert(
                    relation_id.into(),
                    Audit {
                        relation: plan.relation().clone(),
                        actor: actor.into(),
                        at,
                        comment: request.comment.clone(),
                    },
                );
            }
            let n=tx.execute("UPDATE public.strategy_freeze_command_admission SET state='COMPLETED',strategy_fingerprint=$2,freeze_relation_fingerprint=$3,published_at=$4,completed_at=$4 WHERE command_id=$1::pg_catalog.text::pg_catalog.uuid AND state='PREPARED'",&[&request.command.value(),&id,&relation_id,&timestamp]).await.map_err(freeze_db)?;
            if n != 1 {
                return Err(FREEZE_CORRUPT);
            }
            let receipt = Receipt::new(
                current.admission.clone(),
                Outcome::new(OutcomeKind::Strategy, id).map_err(freeze_command)?,
                &at.to_string(),
            )
            .map_err(freeze_command)?;
            GlobalCommands::put_verified_receipt_in_transaction(&tx, &receipt)
                .await
                .map_err(freeze_command)?;
            receipt
        };
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE")
            .await
            .map_err(freeze_db)?;
        let actual = load(&tx, &mut budget, &inventory).await.map_err(|e| e.code())?;
        validate(&actual, &inventory, self.namespace).map_err(|e| e.code())?;
        if actual != expected {
            return Err("STRATEGY_PROJECTION_CONFLICT");
        }
        let final_state = freeze_bound(&tx, &request.command, actor, self.namespace)
            .await?
            .ok_or(FREEZE_CORRUPT)?;
        let Some(complete) = &final_state.completion else {
            return Err(FREEZE_CORRUPT);
        };
        if final_state.request != *request
            || final_state.admission != current.admission
            || final_state.prepared_at != current.prepared_at
            || complete.strategy != id
            || complete.relation != relation_id
            || receipt.accepted_at() != complete.completed
        {
            return Err(FREEZE_CORRUPT);
        }
        verify_freeze_plan(&tx,self.namespace,plan).await?;
        if let Some(cut)=&manual_cut {cut.verify_in_transaction(&tx,self.namespace).await?;}
        // Re-read the original physical Frozen records after deferred effects.
        // This exact comparison is against the already selected Source record,
        // not against a later research run's presentation aliases.
        let frozen_source = self.store.load_verified(id, max_work).map_err(|e| e.code())?;
        if inventory.revisions().get(id) != Some(&frozen_source)
            || self.store.load_relation_verified(relation_id, max_work).map_err(|e| e.code())?
                != *plan.relation()
        {
            return Err("STRATEGY_CORRUPT");
        }
        deployment::verify_binding_in_transaction(&tx, self.namespace)
            .await
            .map_err(|e| e.code())?;
        self.human.subject_id().map_err(|_| FREEZE_DENIED)?;
        plan.verify_cut().map_err(|e| e.code())?;
        AuthoritySession::verify_transaction(&tx).await.map_err(freeze_db)?;
        #[cfg(test)]
        self.checkpoint(FreezeBoundary::BeforeCommit)?;
        tx.commit().await.map_err(|_| FREEZE_UNKNOWN)?;
        #[cfg(test)]
        self.checkpoint(FreezeBoundary::AfterCommit)?;
        owned.verify().await.map_err(freeze_db)?;
        plan.verify_cut().map_err(|e| e.code())?;
        if let Some(cut)=&manual_cut {cut.verify_cut()?;}
        self.human.subject_id().map_err(|_| FREEZE_DENIED)?;
        Ok(
            json!({"schema_version":1,"command_id":request.command.value(),"strategy_fingerprint":id,
            "freeze_relation_fingerprint":relation_id,"accepted_at":receipt.accepted_at().to_string(),"replayed":replayed}),
        )
    }
    #[cfg(test)]
    pub(crate) fn stop_at(&mut self, boundary: &str) -> FreezeResult<()> {
        self.stop = Some(match boundary {
            "prepared" => FreezeBoundary::Prepared,
            "relation" => FreezeBoundary::Relation,
            "revision" => FreezeBoundary::Revision,
            "before_commit" => FreezeBoundary::BeforeCommit,
            "after_commit" => FreezeBoundary::AfterCommit,
            _ => return Err(FREEZE_INVALID),
        });
        Ok(())
    }
    #[cfg(test)]
    fn checkpoint(&self, boundary: FreezeBoundary) -> FreezeResult<()> {
        if self.stop == Some(boundary) {
            Err(FREEZE_UNKNOWN)
        } else {
            Ok(())
        }
    }
}
#[cfg(test)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum FreezeBoundary {
    Prepared,
    Relation,
    Revision,
    BeforeCommit,
    AfterCommit,
}
async fn freeze_transaction(tx: &Transaction<'_>, namespace: &SemanticStoreId) -> FreezeResult<()> {
    tx.batch_execute("SET LOCAL search_path=pg_catalog,public,pg_temp")
        .await
        .map_err(freeze_db)?;
    postgres::bounds(tx).await.map_err(freeze_command)?;
    deployment::verify_binding_in_transaction(tx, namespace)
        .await
        .map_err(|e| e.code())
}
async fn verify_freeze_plan(tx:&Transaction<'_>,namespace:&SemanticStoreId,plan:&FrozenPlan<'_>)->FreezeResult<()> {
    if let Some(e)=plan.manual_evidence(){return e.verify_in_transaction(tx,namespace).await;}
    let e=plan.research_evidence().ok_or(FREEZE_CORRUPT)?;
    let row=tx.query_opt("SELECT state,origin_kind,strategy_research_composition_fingerprint,specification_fingerprint,research_result_fingerprint,calculation_execution_evidence_fingerprints FROM public.research_run WHERE run_id=$1::pg_catalog.text::pg_catalog.uuid FOR SHARE",&[&e.run_id()]).await.map_err(freeze_db)?.ok_or(FREEZE_CORRUPT)?;
    let origin: String = row.try_get("origin_kind").map_err(|_| FREEZE_CORRUPT)?;
    let state: String = row.try_get("state").map_err(|_| FREEZE_CORRUPT)?;
    let composition: Option<String> = row
        .try_get("strategy_research_composition_fingerprint")
        .map_err(|_| FREEZE_CORRUPT)?;
    let spec: String = row
        .try_get("specification_fingerprint")
        .map_err(|_| FREEZE_CORRUPT)?;
    let result: Option<String> = row
        .try_get("research_result_fingerprint")
        .map_err(|_| FREEZE_CORRUPT)?;
    let producers: Option<Vec<String>> = row
        .try_get("calculation_execution_evidence_fingerprints")
        .map_err(|_| FREEZE_CORRUPT)?;
    if origin != "PRIVATE_STRATEGY"
        || state != "COMPLETED"
        || !composition.as_deref().is_some_and(crate::is_sha256_hex)
        || spec != e.specification_fingerprint()
        || result.as_deref() != Some(e.research_result_fingerprint())
        || producers.as_deref() != Some(e.research_execution_evidence_fingerprints())
    {
        return Err(FREEZE_CORRUPT);
    }
    Ok(())
}
/// New admission is distinct from recovery of an already accepted Freeze.
/// Lock and reread the actual original parent, never a stale UI/worker snapshot.
async fn require_new_manual_parent(tx:&Transaction<'_>,plan:&FrozenPlan<'_>)->FreezeResult<()> {
    let Some(evidence)=plan.manual_evidence() else{return Ok(());};
    let command=CommandId::new(evidence.preparation_command_id()).map_err(|_|FREEZE_CORRUPT)?;
    let owner=evidence.record()["prepared_inputs"]["origin"]["owner"].as_str().ok_or(FREEZE_CORRUPT)?;
    tx.query_opt("SELECT command_id FROM public.research_preparation WHERE command_id=$1::pg_catalog.text::pg_catalog.uuid FOR SHARE",&[&command.value()]).await.map_err(freeze_db)?.ok_or(FREEZE_CORRUPT)?;
    let parent=crate::persistence::research_preparation::load(tx,&command,owner).await?;
    if parent.state!=crate::persistence::research_preparation::State::Running{return Err("STRATEGY_FREEZE_PREPARATION_NOT_RUNNING");}
    if crate::application::strategy_validation::Origin::from_operation(&parent)?.record()!=evidence.record()["prepared_inputs"]["origin"]{return Err(FREEZE_CORRUPT);}
    Ok(())
}
/// Observe the original durable Command. This cannot publish files or grant a
/// FrozenPlan; a pending command is resumed only by the separate Human command.
pub(crate) async fn freeze_outcome(
    client:&mut tokio_postgres::Client, namespace:&SemanticStoreId, actor:&str, command:&CommandId,
) -> FreezeResult<Value> {
    let tx=client.build_transaction().isolation_level(tokio_postgres::IsolationLevel::RepeatableRead).read_only(true).start().await.map_err(freeze_db)?;
    freeze_transaction(&tx,namespace).await?;
    let original=freeze_bound_read(&tx,command,actor,namespace,false).await?;
    let value=if let Some(original)=original {
        let request=original.request.view();
        let result=original.completion.as_ref().map(|completed|json!({"schema_version":1,"command_id":command.value(),"strategy_fingerprint":completed.strategy,"freeze_relation_fingerprint":completed.relation,"accepted_at":completed.completed.to_string(),"replayed":true}));
        json!({"state":if result.is_some(){"COMPLETED"}else{"PENDING"},"request":request,"result":result})
    }else{json!({"state":"NOT_SUBMITTED","request":null,"result":null})};
    tx.commit().await.map_err(freeze_db)?;
    Ok(value)
}
async fn freeze_bound(
    tx: &Transaction<'_>,
    id: &CommandId,
    actor: &str,
    namespace: &SemanticStoreId,
) -> FreezeResult<Option<PreparedFreeze>> {
    freeze_bound_read(tx,id,actor,namespace,true).await
}
async fn freeze_bound_read(
    tx: &Transaction<'_>, id:&CommandId, actor:&str, namespace:&SemanticStoreId, lock:bool,
) -> FreezeResult<Option<PreparedFreeze>> {
    let binding = GlobalCommands::verify_binding_in_transaction(tx, id)
        .await
        .map_err(freeze_command)?;
    let sql=format!("SELECT command_fingerprint,research_run_id::pg_catalog.text AS run,candidate_fingerprint,CASE WHEN pg_catalog.octet_length(actor)<=512 THEN actor END AS actor,pg_catalog.octet_length(comment) AS comment_bytes,CASE WHEN pg_catalog.octet_length(comment)<=4096 THEN comment END AS comment,state,strategy_fingerprint,freeze_relation_fingerprint,prepared_at,published_at,completed_at,schema_version,origin_kind,preparation_command_id::pg_catalog.text AS preparation,strategy_validation_fingerprint FROM public.strategy_freeze_command_admission WHERE command_id=$1::pg_catalog.text::pg_catalog.uuid{}",if lock{" FOR UPDATE"}else{""});
    let row=tx.query_opt(&sql,&[&id.value()]).await.map_err(freeze_db)?;
    let bound = match &binding {
        Binding::None => None,
        Binding::Admitted(a) => Some(a),
        Binding::Accepted(r) => Some(r.admission()),
    };
    if bound.is_some_and(|a| a.kind() != CommandKind::FreezeStrategy) {
        return Err(FREEZE_CONFLICT);
    }
    let Some(row) = row else {
        return if bound.is_none() {
            Ok(None)
        } else {
            Err(FREEZE_CORRUPT)
        };
    };
    let bound = bound.ok_or(FREEZE_CORRUPT)?;
    let owner: String = row.try_get("actor").map_err(|_| FREEZE_CORRUPT)?;
    let comment_bytes: Option<i32> = row.try_get("comment_bytes").map_err(|_| FREEZE_CORRUPT)?;
    let comment: Option<String> = row.try_get("comment").map_err(|_| FREEZE_CORRUPT)?;
    if owner.is_empty()
        || owner.trim() != owner
        || owner.chars().any(char::is_control)
        || comment_bytes.is_some_and(|n| n < 0 || n > 4096)
        || comment.as_ref().map(|s| s.len()) != comment_bytes.map(|n| n as usize)
    {
        return Err(FREEZE_CORRUPT);
    }
    let version:i16=row.try_get("schema_version").map_err(|_|FREEZE_CORRUPT)?;
    let origin:String=row.try_get("origin_kind").map_err(|_|FREEZE_CORRUPT)?;
    let run:Option<String>=row.try_get("run").map_err(|_|FREEZE_CORRUPT)?;
    let candidate:Option<String>=row.try_get("candidate_fingerprint").map_err(|_|FREEZE_CORRUPT)?;
    let preparation:Option<String>=row.try_get("preparation").map_err(|_|FREEZE_CORRUPT)?;
    let validation:Option<String>=row.try_get("strategy_validation_fingerprint").map_err(|_|FREEZE_CORRUPT)?;
    let request=match (version,origin.as_str(),run,candidate,preparation,validation) {
        (1,"RESEARCH",Some(run),Some(candidate),None,None)=>FreezeRequest::new(id.clone(),&run,&candidate,comment.as_deref()),
        (2,"MANUAL_BACKTEST",None,None,Some(preparation),Some(validation))=>FreezeRequest::manual(id.clone(),&preparation,&validation,comment.as_deref()),
        _=>return Err(FREEZE_CORRUPT),
    }.map_err(|_|FREEZE_CORRUPT)?;
    let fingerprint: String = row
        .try_get("command_fingerprint")
        .map_err(|_| FREEZE_CORRUPT)?;
    if fingerprint != request.fingerprint(&owner)?
        || *bound != request.admission(&owner)?

    {
        return Err(FREEZE_CORRUPT);
    }
    if owner != actor {
        return Err(FREEZE_DENIED);
    }
    let prepared: SystemTime = row.try_get("prepared_at").map_err(|_| FREEZE_CORRUPT)?;
    let prepared_at = postgres::datetime(prepared).map_err(|_| FREEZE_CORRUPT)?;
    let state: String = row.try_get("state").map_err(|_| FREEZE_CORRUPT)?;
    let strategy: Option<String> = row
        .try_get("strategy_fingerprint")
        .map_err(|_| FREEZE_CORRUPT)?;
    let relation: Option<String> = row
        .try_get("freeze_relation_fingerprint")
        .map_err(|_| FREEZE_CORRUPT)?;
    let published: Option<SystemTime> = row.try_get("published_at").map_err(|_| FREEZE_CORRUPT)?;
    let completed: Option<SystemTime> = row.try_get("completed_at").map_err(|_| FREEZE_CORRUPT)?;
    let completion = match (
        state.as_str(),
        strategy,
        relation,
        published,
        completed,
        &binding,
    ) {
        ("PREPARED", None, None, None, None, Binding::Admitted(_)) => None,
        (
            "COMPLETED",
            Some(strategy),
            Some(relation),
            Some(published),
            Some(completed),
            Binding::Accepted(receipt),
        ) => {
            let published = postgres::datetime(published).map_err(|_| FREEZE_CORRUPT)?;
            let completed = postgres::datetime(completed).map_err(|_| FREEZE_CORRUPT)?;
            if !crate::is_sha256_hex(&strategy)
                || !crate::is_sha256_hex(&relation)
                || published < prepared_at
                || completed < published
                || receipt.outcome().kind() != OutcomeKind::Strategy
                || receipt.outcome().id() != strategy
                || receipt.accepted_at() != completed
            {
                return Err(FREEZE_CORRUPT);
            }
            Some(FreezeCompletion {
                strategy,
                relation,
                published,
                completed,
            })
        }
        _ => return Err(FREEZE_CORRUPT),
    };
    Ok(Some(PreparedFreeze {
        request,
        actor: owner,
        admission: bound.clone(),
        prepared_at,
        completion,
        namespace: namespace.clone(),
    }))
}

/// Exact original Freeze commands supply read locators, never a second relation
/// identity. A shared relation may have several scientifically identical Runs.
pub(crate) async fn freeze_run_locators_in_transaction(tx:&Transaction<'_>,namespace:&SemanticStoreId,actor:&str,subject:&str,relation:&str)->FreezeResult<Vec<String>> {
    if !crate::is_sha256_hex(subject)||!crate::is_sha256_hex(relation){return Err(FREEZE_INVALID);}
    freeze_transaction(tx,namespace).await?;
    let rows=tx.query("SELECT command_id::pg_catalog.text FROM public.strategy_freeze_command_admission WHERE strategy_fingerprint=$1 AND freeze_relation_fingerprint=$2 AND state='COMPLETED' ORDER BY command_id LIMIT 8193",&[&subject,&relation]).await.map_err(freeze_db)?;
    if rows.len()>8192{return Err(FREEZE_UNAVAILABLE);}
    let mut runs=std::collections::BTreeSet::new();
    for row in rows {
        let id=CommandId::new(&row.try_get::<_,String>(0).map_err(|_|FREEZE_CORRUPT)?).map_err(|_|FREEZE_CORRUPT)?;
        let original=freeze_bound_read(tx,&id,actor,namespace,false).await?.ok_or(FREEZE_CORRUPT)?;
        let completed=original.completion.as_ref().ok_or(FREEZE_CORRUPT)?;
        if completed.strategy!=subject || completed.relation!=relation{return Err(FREEZE_CORRUPT);}
        if let FreezeOrigin::Research{run,..}=original.request.origin {runs.insert(run);}
    }
    Ok(runs.into_iter().collect())
}
