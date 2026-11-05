#[cfg(test)]
mod tests {
    use super::*;
    fn input() -> PrepareInput {
        PrepareInput {
            schema_version: 1,
            study_proposal_fingerprint: "a".repeat(64),
            release_manifest_fingerprint: "b".repeat(64),
            expected_active_generation: None,
            initialize_fresh_runtime: false,
            research_command_id: "00000000-0000-4000-8000-000000000002".into(),
        }
    }
    #[test]
    fn preparation_cannot_reuse_its_future_research_command_identity() {
        let command = CommandId::new("00000000-0000-4000-8000-000000000001").unwrap();
        validate_input(&command, &input()).unwrap();
        let mut changed = input();
        changed.research_command_id = command.value().into();
        assert!(validate_input(&command, &changed).is_err());
        let publish = child_command(&command, "PUBLISH_CONFIRMED_FACTOR").unwrap();
        assert_ne!(publish, command);
        assert_eq!(
            publish,
            child_command(&command, "PUBLISH_CONFIRMED_FACTOR").unwrap()
        );
        assert_ne!(publish, child_command(&command, "ACQUIRE_INPUTS").unwrap());
    }
    #[test]
    fn preparation_terminal_and_uncertain_transitions_require_original_owner_drain() {
        use State::*;
        for state in [
            Accepted,
            Running,
            InputPending,
            Ready,
            Blocked,
            Unknown,
            CancelRequested,
            Cancelled,
        ] {
            assert!(!legal_transition(Cancelled, state, "VALIDATING"));
            assert!(!legal_transition(state, Accepted, "ACCEPTED"));
        }
        assert!(!legal_transition(
            CancelRequested,
            Cancelled,
            "CANCELLATION"
        ));
        assert!(!legal_transition(Unknown, Cancelled, "CANCELLATION"));
        assert!(legal_transition(
            CancelRequested,
            Cancelled,
            "OWNER_DRAINED"
        ));
        assert!(legal_transition(Unknown, CancelRequested, "CANCELLATION"));
        assert!(!legal_transition(Ready, Running, "VALIDATING"));
        assert!(legal_transition(Ready, Running, "CONFIRMING"));
        assert!(!legal_transition(Ready, Blocked, "STOPPED"));
    }
    #[test]
    fn preparation_checks_actual_warmup_window_and_block_budget_before_effects() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../tests/application/fixtures/research_factor.json"
        ))
        .unwrap();
        let confirmed = json!({"snapshot":{"preview":{"draft":fixture["draft"],"hypothesis":fixture["candidate"]["hypothesis"],"expression":fixture["candidate"]["expression"]}}});
        let mut advice = json!({"source":{"integration_id":"00000000-0000-4000-8000-000000000001","integration_revision_fingerprint":"a".repeat(64),"expected_type_id":"binance.spot.source","source_id":"spot","environment":"public","instrument_id":"BTCUSDT"},"timeframe_minutes":15,"start_at":"2020-01-01T00:00:00Z","development_end_at":"2020-01-02T00:00:00Z","end_at":"2020-01-03T00:00:00Z","protected_start_at":"2020-01-03T00:00:00Z","protected_end_at":"2020-01-04T00:00:00Z","horizon_bars":1,"expected_block_length":4,"replicates":4096,"confidence_bps":9500,"seed":"b".repeat(64),"rationale":"fixed intervals"});
        assert!(validated_inputs(&json!({"advice":advice}), &confirmed).is_ok());
        advice["expected_block_length"] = json!(12);
        assert_eq!(
            validated_inputs(&json!({"advice":advice}), &confirmed).err(),
            Some("RESEARCH_PREPARATION_INSUFFICIENT_BLOCK_SCOPE")
        );
        advice["expected_block_length"] = json!(4);
        advice["timeframe_minutes"] = json!(60);
        advice["development_end_at"] = json!("2020-01-05T00:00:00Z");
        advice["end_at"] = json!("2020-01-09T00:00:00Z");
        advice["protected_start_at"] = json!("2020-01-09T00:00:00Z");
        advice["protected_end_at"] = json!("2020-01-13T00:00:00Z");
        assert_eq!(
            validated_inputs(&json!({"advice":advice}), &confirmed).err(),
            Some("RESEARCH_PREPARATION_WINDOW_UNSUPPORTED")
        );
    }
    #[test]
    fn missing_runtime_with_original_durable_bindings_cannot_be_reinitialized() {
        assert_eq!(
            guard_fresh_runtime(true),
            Err("RESEARCH_RUNTIME_HISTORY_UNAVAILABLE")
        );
        guard_fresh_runtime(false).unwrap();
    }
    #[test]
    fn preparation_admission_separates_human_owner_and_exact_release() {
        let original = intent("owner", &input()).unwrap();
        assert_ne!(original, intent("other", &input()).unwrap());
        let mut changed = input();
        changed.release_manifest_fingerprint = "c".repeat(64);
        assert_ne!(original, intent("owner", &changed).unwrap());
    }
}
#[path="research_preparation/backtest.rs"]
mod backtest;
pub(crate) use backtest::{require_running_backtest_preparation,require_running_manual_backtest_parent,cancelled_backtest_cleanup_in_transaction,accept_backtest,cancel_backtest,manual_backtest_authoring,BacktestAcceptance,BacktestReady,publish_backtest_ready};
// Accepted Human preparation operations. This owner never substitutes for Research Run authority.
use crate::{
    application::{
        command::{Admission, Binding, CommandId, CommandKind, Outcome, OutcomeKind, Receipt},
        factor_content::hash,
        factor_studies::PrepareInput,
        backtest_preparation::{BacktestPrepareInput,BacktestOrigin},
        strategy_research::StrategyPrepareInput,
    },
    persistence::{
        factor_proposals, factor_studies,
        postgres::{Commands, bounds},
    },
};
use onlyalpha_domain::time::OnlyUtcDateTime;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use tokio_postgres::{Client, Transaction};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_PREPARATION_INVALID";
const CORRUPT: &str = "RESEARCH_PREPARATION_CORRUPT";
pub(crate) const BACKTEST_NOT_ACCEPTED:&str="BACKTEST_PREPARATION_NOT_ACCEPTED";
const UNAVAILABLE: &str = "RESEARCH_PREPARATION_UNAVAILABLE";
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum State {
    Accepted,
    Running,
    InputPending,
    Ready,
    Blocked,
    Unknown,
    CancelRequested,
    Cancelled,
}
impl State {
    pub(crate) fn as_str(self) -> &'static str {
        match self {
            Self::Accepted => "ACCEPTED",
            Self::Running => "RUNNING",
            Self::InputPending => "INPUT_PENDING",
            Self::Ready => "READY",
            Self::Blocked => "BLOCKED",
            Self::Unknown => "UNKNOWN",
            Self::CancelRequested => "CANCEL_REQUESTED",
            Self::Cancelled => "CANCELLED",
        }
    }
    fn parse(s: &str) -> Result<Self> {
        match s {
            "ACCEPTED" => Ok(Self::Accepted),
            "RUNNING" => Ok(Self::Running),
            "INPUT_PENDING" => Ok(Self::InputPending),
            "READY" => Ok(Self::Ready),
            "BLOCKED" => Ok(Self::Blocked),
            "UNKNOWN" => Ok(Self::Unknown),
            "CANCEL_REQUESTED" => Ok(Self::CancelRequested),
            "CANCELLED" => Ok(Self::Cancelled),
            _ => Err(CORRUPT),
        }
    }
}
#[derive(Clone, serde::Serialize, serde::Deserialize)]
#[serde(untagged)]
pub(crate) enum PreparationRequest { Factor(PrepareInput), Strategy(StrategyPrepareInput), Backtest(BacktestPrepareInput) }
impl PreparationRequest {
    pub(crate) fn factor(&self)->Result<&PrepareInput> {match self {Self::Factor(v)=>Ok(v),_=>Err(INVALID)}}
    pub(crate) fn strategy(&self)->Result<&StrategyPrepareInput> {match self {Self::Strategy(v)=>Ok(v),_=>Err(INVALID)}}
    pub(crate) fn is_strategy(&self)->bool {matches!(self,Self::Strategy(_))}
    pub(crate) fn is_backtest(&self)->bool {matches!(self,Self::Backtest(_))}
    pub(crate) fn backtest(&self)->Result<&BacktestPrepareInput> {match self {Self::Backtest(v)=>Ok(v),_=>Err(INVALID)}}
    pub(crate) fn future_command(&self)->&str {match self {Self::Factor(v)=>&v.research_command_id,Self::Strategy(v)=>&v.research_command_id,Self::Backtest(v)=>&v.backtest_command_id}}
    pub(crate) fn research_command(&self)->&str {self.future_command()}
    pub(crate) fn reserved_run_id(&self)->String {let command=CommandId::new(self.future_command()).expect("verified future Command");match self {Self::Backtest(_)=>crate::application::backtest_preparation::run_id(&command),Self::Factor(_)|Self::Strategy(_)=>crate::persistence::research_submission::run_id(&command)}}
    pub(crate) fn release(&self)->&str {match self {Self::Factor(v)=>&v.release_manifest_fingerprint,Self::Strategy(v)=>&v.release_manifest_fingerprint,Self::Backtest(v)=>&v.release_manifest_fingerprint}}
    pub(crate) fn expected_active(&self)->Option<&str> {match self {Self::Factor(v)=>v.expected_active_generation.as_deref(),Self::Strategy(v)=>v.expected_active_generation.as_deref(),Self::Backtest(v)=>v.expected_active_generation.as_deref()}}
    pub(crate) fn initialize(&self)->bool {match self {Self::Factor(v)=>v.initialize_fresh_runtime,Self::Strategy(v)=>v.initialize_fresh_runtime,Self::Backtest(v)=>v.initialize_fresh_runtime}}
    fn kind(&self)->&'static str {match self {Self::Factor(_)=>"FACTOR_RESEARCH",Self::Strategy(_)=>"STRATEGY_RESEARCH",Self::Backtest(_)=>"BACKTEST_PREPARATION"}}
    fn command_kind(&self)->CommandKind {match self {Self::Factor(_)=>CommandKind::PrepareFactorResearch,Self::Strategy(_)=>CommandKind::PrepareStrategyResearch,Self::Backtest(_)=>CommandKind::PrepareBacktest}}
    fn cancel_kind(&self)->CommandKind {match self {Self::Factor(_)=>CommandKind::CancelFactorResearchPreparation,Self::Strategy(_)=>CommandKind::CancelStrategyResearchPreparation,Self::Backtest(_)=>CommandKind::CancelBacktestPreparation}}
    fn validate(&self,command:&CommandId)->Result<()> {match self {Self::Factor(v)=>validate_input(command,v),Self::Strategy(v)=>v.validate(command).map(|_|()),Self::Backtest(v)=>v.validate(command)}}
    fn intent(&self,owner:&str)->Result<String> {match self {Self::Factor(v)=>intent(owner,v),Self::Strategy(v)=>hash(&json!({"contract":"ONLYALPHA_STRATEGY_RESEARCH_PREPARATION_V1","owner":owner,"input":v})),Self::Backtest(v)=>hash(&json!({"contract":"ONLYALPHA_BACKTEST_PREPARATION_V2","owner":owner,"input":v}))}}

}
/// Only this owning reader constructs an original accepted request handle.
#[derive(Clone)]
pub(crate) struct Operation {
    pub(crate) command: CommandId,
    pub(crate) owner: String,
    pub(crate) request: PreparationRequest,
    pub(crate) accepted: Value,
    pub(crate) revision: i64,
    pub(crate) state: State,
    pub(crate) phase: String,
    pub(crate) outputs: Value,
    pub(crate) detail: Value,
}
impl Operation {
    pub(crate) fn source(&self)->Result<crate::application::factor_studies::Source> {
        match &self.request {
            PreparationRequest::Strategy(v)=>Ok(v.source.clone()),
            PreparationRequest::Backtest(v)=>Ok(v.source.clone()),
            PreparationRequest::Factor(_)=>serde_json::from_value(self.accepted["study"]["advice"]["source"].clone()).map_err(|_|CORRUPT),
        }
    }
    pub(crate) fn view(&self) -> Value {
        if let PreparationRequest::Backtest(input)=&self.request {
            let derived=&self.outputs["ready"]["admission"];
            return json!({"schema_version":2,"command_id":self.command.value(),"profile":input.profile,"origin":input.origin,
                "strategy_fingerprint":derived["strategy_fingerprint"],"freeze_relation_fingerprint":derived["freeze_relation_fingerprint"],
                "qualification_decision_fingerprint":derived["qualification_decision_fingerprint"],"promotion_fingerprint":derived["promotion_fingerprint"],
                "validation_fingerprint":self.outputs["ready"]["validation_fingerprint"],"source":input.source,"revision":self.revision.to_string(),"state":self.state.as_str(),"phase":self.phase,
                "backtest_command_id":input.backtest_command_id,"reserved_run_id":self.request.reserved_run_id(),
                "preparation_fingerprint":self.outputs["ready"]["preparation_fingerprint"],"detail":self.detail,
                "backtest_outcome":"UNOBSERVED","readiness":{"state":"NOT_APPLICABLE","code":null},"run_id":null,"accepted_at":self.accepted["accepted_at"]});
        }
        let future=self.request.research_command();
        let mut view=json!({"schema_version":1,"command_id":self.command.value(),"revision":self.revision.to_string(),"state":self.state.as_str(),"phase":self.phase,"research_command_id":future,"reserved_run_id":crate::persistence::research_submission::run_id(&CommandId::new(future).expect("verified command")),"prepared_study_fingerprint":self.outputs["ready"]["prepared_study_fingerprint"],"detail":self.detail,"research_outcome":"UNOBSERVED","readiness":{"state":"NOT_APPLICABLE","code":null},"run_id":null,"accepted_at":self.accepted["accepted_at"]});
        match &self.request {
            PreparationRequest::Factor(v)=> {view["study_proposal_fingerprint"]=json!(v.study_proposal_fingerprint);view["advice"]=self.accepted["study"]["advice"].clone();},
            PreparationRequest::Strategy(v)=> {for key in ["profile","strategy_id","strategy_revision_fingerprint","definition_fingerprint","context","source"] {view[key]=self.accepted["input"][key].clone();}debug_assert_eq!(view["profile"],v.profile);},
            PreparationRequest::Backtest(_)=>unreachable!("handled typed view"),
        }
        view
    }
}
pub(crate) struct Preparations<'a> {
    client: &'a mut Client,
}
fn db(_: impl std::fmt::Debug) -> &'static str {
    UNAVAILABLE
}
fn text<'a>(v: &'a Value, k: &str) -> Result<&'a str> {
    v[k].as_str().ok_or(CORRUPT)
}
fn canonical(v: &Value) -> Result<String> {
    onlyalpha_metadata_json::canonical_json(&v.to_string(), 8 * 1024 * 1024).map_err(|_| INVALID)
}
fn intent(owner: &str, input: &PrepareInput) -> Result<String> {
    hash(
        &json!({"contract":"ONLYALPHA_FACTOR_RESEARCH_PREPARATION_V1","owner":owner,"input":input}),
    )
}
pub(crate) fn child_command(parent: &CommandId, role: &str) -> Result<CommandId> {
    let mut bytes=Sha256::digest(canonical(&json!({"contract":"ONLYALPHA_RESEARCH_PREPARATION_CHILD_V1","parent":parent.value(),"role":role}))?.as_bytes());
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    let s = bytes[..16]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    CommandId::new(&format!(
        "{}-{}-{}-{}-{}",
        &s[..8],
        &s[8..12],
        &s[12..16],
        &s[16..20],
        &s[20..]
    ))
    .map_err(db)
}
fn validate_input(command: &CommandId, input: &PrepareInput) -> Result<()> {
    if input.schema_version != 1
        || !crate::is_sha256_hex(&input.study_proposal_fingerprint)
        || !crate::is_sha256_hex(&input.release_manifest_fingerprint)
        || input
            .expected_active_generation
            .as_deref()
            .is_some_and(|s| !crate::is_sha256_hex(s))
        || input.research_command_id == command.value()
    {
        return Err(INVALID);
    }
    CommandId::new(&input.research_command_id).map_err(|_| INVALID)?;
    Ok(())
}
impl<'a> Preparations<'a> {
    pub(crate) fn new(client: &'a mut Client) -> Self {
        Self { client }
    }
    pub(crate) async fn existing(&mut self,command:&CommandId,owner:&str,input:&PrepareInput)->Result<Option<Operation>> {
        self.existing_request(command,owner,PreparationRequest::Factor(input.clone())).await
    }
    pub(crate) async fn existing_backtest(&mut self,command:&CommandId,owner:&str,input:&BacktestPrepareInput)->Result<Option<Operation>> {
        self.existing_request(command,owner,PreparationRequest::Backtest(input.clone())).await
    }
    /// Backtest's original-Command query observes Binding before resource rows.
    /// Its exclusive negative code is not shared with a generic resource 404.
    pub(crate) async fn query_backtest_command(&mut self,namespace:&crate::bootstrap::deployment::SemanticStoreId,command:&CommandId,owner:&str)->Result<Operation> {
        let tx=self.client.build_transaction().isolation_level(tokio_postgres::IsolationLevel::ReadCommitted).read_only(true).start().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let value=backtest_command_in_transaction(&tx,namespace,command,owner).await?;
        tx.commit().await.map_err(db)?;Ok(value)
    }
    /// Every durable state is returned, including UNKNOWN and cancellation.
    pub(crate) async fn for_backtest_origin(&mut self,origin:&BacktestOrigin,owner:&str)->Result<Vec<Operation>> {
        origin.validate()?;let origin=serde_json::to_string(origin).map_err(db)?;
        let tx=self.client.build_transaction().read_only(true).start().await.map_err(db)?;bounds(&tx).await.map_err(db)?;
        let rows=tx.query("SELECT command_id::text FROM research_preparation WHERE owner=$1 AND preparation_kind='BACKTEST_PREPARATION' AND accepted_payload::jsonb->'input'->'origin'=$2::text::jsonb ORDER BY command_id LIMIT 101",&[&owner,&origin]).await.map_err(db)?;
        let result=backtest_operations(&tx,rows,owner).await?;tx.commit().await.map_err(db)?;Ok(result)
    }
    /// Published Strategy authoring history keeps all revisions and task states.
    pub(crate) async fn for_strategy_backtests(&mut self,strategy_id:&str,owner:&str)->Result<Vec<Operation>> {
        crate::application::private_assets::id(strategy_id,"STRATEGY").map_err(|_|INVALID)?;
        let tx=self.client.build_transaction().read_only(true).start().await.map_err(db)?;bounds(&tx).await.map_err(db)?;
        let rows=tx.query("SELECT command_id::text FROM research_preparation WHERE owner=$1 AND preparation_kind='BACKTEST_PREPARATION' AND accepted_payload::jsonb->'input'->'origin'->>'kind'='MANUAL_STRATEGY' AND accepted_payload::jsonb->'input'->'origin'->>'strategy_id'=$2 ORDER BY command_id LIMIT 101",&[&owner,&strategy_id]).await.map_err(db)?;
        let result=backtest_operations(&tx,rows,owner).await?;tx.commit().await.map_err(db)?;Ok(result)
    }
    #[cfg(test)]
    pub(crate) async fn existing_strategy(&mut self,command:&CommandId,owner:&str,input:&StrategyPrepareInput)->Result<Option<Operation>> {
        self.existing_request(command,owner,PreparationRequest::Strategy(input.clone())).await
    }
    async fn existing_request(&mut self,command:&CommandId,owner:&str,input:PreparationRequest)->Result<Option<Operation>> {
        input.validate(command)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let result=existing_request_in_transaction(&tx,command,owner,&input).await?;
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    pub(crate) async fn for_factor(
        &mut self,
        factor_id: &str,
        owner: &str,
    ) -> Result<Vec<Operation>> {
        crate::application::private_assets::authoring::validate_id(factor_id)
            .map_err(|_| INVALID)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        if tx.query_opt("SELECT command_id FROM product_command_admission a WHERE command_kind='PREPARE_FACTOR_RESEARCH' AND NOT EXISTS(SELECT 1 FROM research_preparation p WHERE p.command_id=a.command_id) UNION SELECT command_id FROM product_command_receipt r WHERE command_kind='PREPARE_FACTOR_RESEARCH' AND NOT EXISTS(SELECT 1 FROM research_preparation p WHERE p.command_id=r.command_id) LIMIT 1",&[]).await.map_err(db)?.is_some(){return Err(CORRUPT);}
        let rows=tx.query("SELECT command_id::text FROM research_preparation WHERE owner=$1 AND accepted_payload::jsonb->'study'->>'factor_id'=$2 ORDER BY command_id LIMIT 101",&[&owner,&factor_id]).await.map_err(db)?;
        if rows.len() > 100 {
            return Err(UNAVAILABLE);
        }
        let mut result = Vec::new();
        for row in rows {
            let id = CommandId::new(&row.try_get::<_, String>(0).map_err(db)?).map_err(db)?;
            let o = load(&tx, &id, owner).await?;
            if o.accepted["study"]["factor_id"] != factor_id {
                return Err(CORRUPT);
            }
            result.push(o);
        }
        tx.commit().await.map_err(db)?;
        Ok(result)
    }
    pub(crate) async fn for_strategy(&mut self,id:&str,owner:&str)->Result<Vec<Operation>> {
        crate::application::private_assets::id(id,"STRATEGY").map_err(|_|INVALID)?;
        let tx=self.client.transaction().await.map_err(db)?;bounds(&tx).await.map_err(db)?;
        if tx.query_opt("SELECT a.command_id FROM product_command_admission a WHERE command_kind='PREPARE_STRATEGY_RESEARCH' AND NOT EXISTS(SELECT 1 FROM research_preparation p WHERE p.command_id=a.command_id) UNION SELECT r.command_id FROM product_command_receipt r WHERE command_kind='PREPARE_STRATEGY_RESEARCH' AND NOT EXISTS(SELECT 1 FROM research_preparation p WHERE p.command_id=r.command_id) LIMIT 1",&[]).await.map_err(db)?.is_some(){return Err(CORRUPT);}
        let rows=tx.query("SELECT command_id::text FROM research_preparation WHERE owner=$1 AND preparation_kind='STRATEGY_RESEARCH' AND accepted_payload::jsonb->'input'->>'strategy_id'=$2 ORDER BY command_id LIMIT 101",&[&owner,&id]).await.map_err(db)?;
        if rows.len()>100{return Err(UNAVAILABLE);}
        let mut result=Vec::new();for row in rows {let command=CommandId::new(&row.try_get::<_,String>(0).map_err(db)?).map_err(db)?;let operation=load(&tx,&command,owner).await?;if operation.request.strategy()?.strategy_id!=id{return Err(CORRUPT);}result.push(operation);}
        tx.commit().await.map_err(db)?;Ok(result)
    }
    pub(crate) async fn accept(&mut self,command:&CommandId,owner:&str,input:PrepareInput,at:OnlyUtcDateTime)->Result<Operation> {
        self.accept_request(command,owner,PreparationRequest::Factor(input),at).await
    }
    #[cfg(test)]
    pub(crate) async fn accept_strategy(&mut self,command:&CommandId,owner:&str,input:StrategyPrepareInput,at:OnlyUtcDateTime)->Result<Operation> {
        self.accept_request(command,owner,PreparationRequest::Strategy(input),at).await
    }
    async fn accept_request(&mut self,command:&CommandId,owner:&str,input:PreparationRequest,at:OnlyUtcDateTime)->Result<Operation> {
        input.validate(command)?;
        if input.is_backtest(){return Err(INVALID);}
        let admission = Admission::new(
            command.clone(),
            input.command_kind(),
            &input.intent(owner)?,
        )
        .map_err(db)?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        let binding = Commands::verify_binding_in_transaction(&tx, command)
            .await
            .map_err(db)?;
        match binding {
            Binding::Accepted(receipt) if receipt.admission() == &admission => {
                let original = load(&tx, command, owner).await?;
                tx.commit().await.map_err(db)?;
                return Ok(original);
            }
            Binding::None => {}
            Binding::Admitted(_) => return Err("RESEARCH_PREPARATION_OUTCOME_UNKNOWN"),
            _ => return Err("RESEARCH_PREPARATION_COMMAND_CONFLICT"),
        }
        if tx
            .query_opt(
                "SELECT 1 FROM research_preparation WHERE command_id=$1::text::uuid",
                &[&command.value()],
            )
            .await
            .map_err(db)?
            .is_some()
        {
            return Err(CORRUPT);
        }
        if input.is_strategy() {
            let future=CommandId::new(input.research_command()).map_err(|_|INVALID)?;
            Commands::lock_command(&tx,&future).await.map_err(db)?;
            if !matches!(Commands::verify_binding_in_transaction(&tx,&future).await.map_err(db)?,Binding::None)
                || tx.query_opt("SELECT 1 FROM research_run WHERE run_id=$1::text::uuid",&[&crate::persistence::research_submission::run_id(&future)]).await.map_err(db)?.is_some()
            {return Err("RESEARCH_PREPARATION_COMMAND_CONFLICT");}
        }
        if input.initialize() {
            guard_fresh_runtime(runtime_history_exists(&tx).await?)?;
        }
        let accepted=match &input {
            PreparationRequest::Factor(input)=> {
                let study=factor_studies::current(&tx,&input.study_proposal_fingerprint,owner).await?;
                let confirmed=factor_proposals::confirmed_research_input(&tx,text(&study,"factor_proposal_fingerprint")?,owner,true).await?;
                validated_inputs(&study,&confirmed)?;
                json!({"schema_version":1,"contract":"ONLYALPHA_ACCEPTED_RESEARCH_PREPARATION_V1","command_id":command.value(),"owner":owner,"input":input,"study":study,"factor_confirmation":confirmed,"accepted_at":at.to_string()})
            },
            PreparationRequest::Strategy(input)=> {
                let (strategy,confirmed)=strategy_anchors(&tx,command,input,owner,true).await?;
                json!({"schema_version":1,"contract":"ONLYALPHA_ACCEPTED_STRATEGY_RESEARCH_PREPARATION_V1","command_id":command.value(),"owner":owner,"input":input,"strategy_revision":strategy,"factor_confirmation":confirmed,"accepted_at":at.to_string()})
            },
            PreparationRequest::Backtest(_)=>return Err(INVALID),
        };
        let fingerprint = hash(&accepted)?;
        let payload = canonical(&accepted)?;
        Commands::admit_exact_in_transaction(&tx, &admission)
            .await
            .map_err(db)?;
        tx.execute("INSERT INTO research_preparation(command_id,owner,accepted_fingerprint,accepted_payload,revision,state,phase,outputs_payload,detail_payload,preparation_kind) VALUES($1::text::uuid,$2,$3,$4,0,'ACCEPTED','ACCEPTED','{}','null',$5)",&[&command.value(),&owner,&fingerprint,&payload,&input.kind()]).await.map_err(db)?;
        let receipt = Receipt::new(
            admission,
            Outcome::new(OutcomeKind::ResearchPreparationOperation, &fingerprint).map_err(db)?,
            &at.to_string(),
        )
        .map_err(db)?;
        Commands::put_verified_receipt_in_transaction(&tx, &receipt)
            .await
            .map_err(db)?;
        let operation = load(&tx, command, owner).await?;
        tx.commit().await.map_err(db)?;
        Ok(operation)
    }
    pub(crate) async fn query(&mut self, command: &CommandId, owner: &str) -> Result<Operation> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let o = load(&tx, command, owner).await?;
        tx.commit().await.map_err(db)?;
        Ok(o)
    }
    /// Explicit current-Human continuation of the original intent, never a new preparation.
    pub(crate) async fn resume(
        &mut self,
        command: &CommandId,
        owner: &str,
        expected: i64,
    ) -> Result<Operation> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        let original = load(&tx, command, owner).await?;
        if original.revision != expected {
            return Err("RESEARCH_PREPARATION_STALE");
        }
        if matches!(
            original.state,
            State::Ready | State::Cancelled | State::CancelRequested
        ) {
            return Ok(original);
        }
        require_current(&tx,&original).await?;
        let result = update(
            &tx,
            &original,
            State::Running,
            "VALIDATING",
            &original.outputs,
            &Value::Null,
        )
        .await?;
        commit_updated(tx,result).await
    }
    pub(crate) async fn progress(
        &mut self,
        original: &Operation,
        state: State,
        phase: &str,
        outputs: &Value,
        detail: &Value,
    ) -> Result<Operation> {
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        Commands::lock_command(&tx, &original.command)
            .await
            .map_err(db)?;
        let current = load(&tx, &original.command, &original.owner).await?;
        if current.revision != original.revision {
            return Err("RESEARCH_PREPARATION_STALE");
        }
        if current.state == State::Cancelled {
            return Err("RESEARCH_PREPARATION_FINISHED");
        }
        if current.state == State::CancelRequested
            && !matches!(state, State::Cancelled | State::Unknown)
        {
            return Err("RESEARCH_PREPARATION_CANCEL_REQUESTED");
        }
        if state==State::Ready&&current.request.is_backtest(){return Err("BACKTEST_READY_PROOF_REQUIRED");}
        if state == State::Ready {
            require_current(&tx,&current).await?;
            validate_ready(&current, outputs)?;
        }
        if !legal_transition(current.state, state, phase) {
            return Err("RESEARCH_PREPARATION_ILLEGAL_TRANSITION");
        }
        for (key, value) in current.outputs.as_object().ok_or(CORRUPT)? {
            if outputs.get(key) != Some(value) {
                return Err(CORRUPT);
            }
        }
        let result = update(&tx, &current, state, phase, outputs, detail).await?;
        commit_updated(tx,result).await
    }
    pub(crate) async fn cancel(
        &mut self,
        cancel: &CommandId,
        command: &CommandId,
        owner: &str,
        expected: i64,
        at: OnlyUtcDateTime,
    ) -> Result<Operation> {
        let body = json!({"preparation_command_id":command.value(),"expected_revision":expected});
        let fingerprint = hash(
            &json!({"contract":"ONLYALPHA_CANCEL_RESEARCH_PREPARATION_V1","owner":owner,"body":body}),
        )?;
        let tx = self.client.transaction().await.map_err(db)?;
        bounds(&tx).await.map_err(db)?;
        let original=load(&tx,command,owner).await?;
        let admission=Admission::new(cancel.clone(),original.request.cancel_kind(),&fingerprint).map_err(db)?;
        Commands::lock_command(&tx, cancel).await.map_err(db)?;
        let cancel_binding = Commands::verify_binding_in_transaction(&tx, cancel)
            .await
            .map_err(db)?;
        if matches!(cancel_binding, Binding::Admitted(_)) {
            return Err("RESEARCH_PREPARATION_OUTCOME_UNKNOWN");
        }
        if let Binding::Accepted(receipt) = cancel_binding {
            if receipt.admission() != &admission {
                return Err("RESEARCH_PREPARATION_COMMAND_CONFLICT");
            }
            let current = load(&tx, command, owner).await?;
            if receipt.outcome().kind() != OutcomeKind::ResearchPreparationOperation
                || receipt.outcome().id() != hash(&current.accepted)?
            {
                return Err(CORRUPT);
            }
            tx.commit().await.map_err(db)?;
            return Ok(current);
        }
        // The owning load verified the original accepted request, including its
        // exact future Command. Backtest and Research use different wire names.
        let future = CommandId::new(original.request.future_command()).map_err(db)?;
        Commands::lock_command(&tx, &future).await.map_err(db)?;
        Commands::lock_command(&tx, command).await.map_err(db)?;
        let current = load(&tx, command, owner).await?;
        if current.revision != expected {
            return Err("RESEARCH_PREPARATION_STALE");
        }
        if let Binding::Accepted(_) = Commands::verify_binding_in_transaction(&tx, &future)
            .await
            .map_err(db)?
        {
            return Err("RESEARCH_PREPARATION_ALREADY_SUBMITTED");
        }
        let mut outputs = current.outputs.clone();
        if outputs.get("cancellation").is_none() {
            outputs["cancellation"] = json!({"command_id":cancel.value(),"expected_revision":expected,"requested_at":at.to_string()});
        }
        Commands::admit_exact_in_transaction(&tx, &admission)
            .await
            .map_err(db)?;
        Commands::put_verified_receipt_in_transaction(
            &tx,
            &Receipt::new(
                admission,
                Outcome::new(
                    OutcomeKind::ResearchPreparationOperation,
                    &hash(&current.accepted)?,
                )
                .map_err(db)?,
                &at.to_string(),
            )
            .map_err(db)?,
        )
        .await
        .map_err(db)?;
        let target = if matches!(
            current.state,
            State::Running | State::Unknown | State::CancelRequested
        ) {
            State::CancelRequested
        } else {
            State::Cancelled
        };
        let next = if matches!(current.state, State::Cancelled | State::CancelRequested) {
            current
        } else {
            update(
                &tx,
                &current,
                target,
                "CANCELLATION",
                &outputs,
                &Value::Null,
            )
            .await?
        };
        commit_updated(tx,next).await
    }
}
enum PreparationExpectation<'a> { Exact(&'a PreparationRequest),BacktestCommand }
/// Shared owning primitive. Every original input path and the Backtest Command
/// query takes the same barrier and verifies the same canonical binding.
async fn observe_original_preparation(tx:&Transaction<'_>,command:&CommandId,owner:&str,expectation:PreparationExpectation<'_>)->Result<Option<Operation>> {
    Commands::lock_command(tx,command).await.map_err(db)?;
    let binding=Commands::verify_binding_in_transaction(tx,command).await.map_err(db)?;
    match binding {
        Binding::None=> {
            if tx.query_opt("SELECT 1 FROM research_preparation WHERE command_id=$1::text::uuid",&[&command.value()]).await.map_err(db)?.is_some(){return Err(CORRUPT);}
            Ok(None)
        },
        Binding::Admitted(admission)=> {
            if matches!(expectation,PreparationExpectation::BacktestCommand)&&admission.kind()!=CommandKind::PrepareBacktest{return Err("RESEARCH_PREPARATION_COMMAND_CONFLICT");}
            Err("RESEARCH_PREPARATION_OUTCOME_UNKNOWN")
        },
        Binding::Accepted(receipt)=> {
            match expectation {
                PreparationExpectation::Exact(input)=> {
                    let expected=Admission::new(command.clone(),input.command_kind(),&input.intent(owner)?).map_err(db)?;
                    if receipt.admission()!=&expected{return Err("RESEARCH_PREPARATION_COMMAND_CONFLICT");}
                    Ok(Some(load(tx,command,owner).await?))
                },
                PreparationExpectation::BacktestCommand=> {
                    if receipt.admission().kind()!=CommandKind::PrepareBacktest{return Err("RESEARCH_PREPARATION_COMMAND_CONFLICT");}
                    let operation=load(tx,command,owner).await.map_err(|code|if code=="RESEARCH_PREPARATION_NOT_FOUND"{"RESEARCH_PREPARATION_COMMAND_CONFLICT"}else{code})?;
                    if !operation.request.is_backtest(){return Err(CORRUPT);}Ok(Some(operation))
                },
            }
        },
    }
}
/// The exact-request entry used by acceptance and pre-accept feedback.
pub(crate) async fn existing_request_in_transaction(tx:&Transaction<'_>,command:&CommandId,owner:&str,input:&PreparationRequest)->Result<Option<Operation>> {
    input.validate(command)?;
    observe_original_preparation(tx,command,owner,PreparationExpectation::Exact(input)).await
}
/// A negative is possible only in this expected namespace after actual Binding
/// None and absent downstream operation. Driver loss and foreign facts fail closed.
pub(crate) async fn backtest_command_in_transaction(tx:&Transaction<'_>,namespace:&crate::bootstrap::deployment::SemanticStoreId,command:&CommandId,owner:&str)->Result<Operation> {
    let isolation:String=tx.query_one("SHOW transaction_isolation",&[]).await.map_err(db)?.try_get(0).map_err(db)?;
    if isolation!="read committed"{return Err(UNAVAILABLE);}
    crate::bootstrap::deployment::verify_binding_in_transaction(tx,namespace).await.map_err(|error|error.code())?;
    observe_original_preparation(tx,command,owner,PreparationExpectation::BacktestCommand).await?.ok_or(BACKTEST_NOT_ACCEPTED)
}
async fn backtest_operations(tx:&Transaction<'_>,rows:Vec<tokio_postgres::Row>,owner:&str)->Result<Vec<Operation>> {
    if rows.len()>100{return Err(UNAVAILABLE);}
    let mut result=Vec::new();for row in rows {let command=CommandId::new(&row.try_get::<_,String>(0).map_err(db)?).map_err(db)?;result.push(load(tx,&command,owner).await?);}Ok(result)
}
pub(crate) async fn load(tx: &Transaction<'_>, command: &CommandId, owner: &str) -> Result<Operation> {
    let row=tx.query_opt("SELECT owner,accepted_fingerprint,accepted_payload,revision,state,phase,outputs_payload,detail_payload,preparation_kind FROM research_preparation WHERE command_id=$1::text::uuid",&[&command.value()]).await.map_err(db)?.ok_or("RESEARCH_PREPARATION_NOT_FOUND")?;
    let actual:String=row.try_get(0).map_err(db)?;if actual!=owner{return Err("RESEARCH_PREPARATION_NOT_FOUND");}
    let accepted=parse(&row.try_get::<_,String>(2).map_err(db)?)?;
    let kind:String=row.try_get(8).map_err(db)?;
    if kind=="BACKTEST_PREPARATION"&&accepted["schema_version"]==1&&accepted["contract"]=="ONLYALPHA_ACCEPTED_BACKTEST_PREPARATION_V1" {
        if accepted["command_id"]!=command.value()||accepted["owner"]!=owner||hash(&accepted)?!=row.try_get::<_,String>(1).map_err(db)? {return Err(CORRUPT);}
        return Err("BACKTEST_PREPARATION_HISTORICAL_READER_UNAVAILABLE");
    }
    let request:PreparationRequest=serde_json::from_value(accepted["input"].clone()).map_err(|_|CORRUPT)?;
    request.validate(command)?;
    if request.kind()!=kind || accepted["schema_version"]!=(if request.is_backtest(){2}else{1}) || accepted["command_id"]!=command.value() || accepted["owner"]!=owner || hash(&accepted)?!=row.try_get::<_,String>(1).map_err(db)? {return Err(CORRUPT);}
    match &request {
        PreparationRequest::Factor(request)=> {
            exact_fields(&accepted,&["schema_version","contract","command_id","owner","input","study","factor_confirmation","accepted_at"])?;
            if accepted["contract"]!="ONLYALPHA_ACCEPTED_RESEARCH_PREPARATION_V1" {return Err(CORRUPT);}
            let study=&accepted["study"];let factor=&accepted["factor_confirmation"];
            if hash(study)?!=request.study_proposal_fingerprint || study["owner"]!=owner || study["factor_proposal_fingerprint"]!=hash(&factor["snapshot"])? || study["factor_id"]!=factor["snapshot"]["factor_id"] {return Err(CORRUPT);}
            if factor_studies::retained(tx,&request.study_proposal_fingerprint,owner).await?!=*study || factor_proposals::confirmed_research_input(tx,text(study,"factor_proposal_fingerprint")?,owner,false).await?!=*factor {return Err(CORRUPT);}
        },
        PreparationRequest::Strategy(request)=> {
            exact_fields(&accepted,&["schema_version","contract","command_id","owner","input","strategy_revision","factor_confirmation","accepted_at"])?;
            if accepted["contract"]!="ONLYALPHA_ACCEPTED_STRATEGY_RESEARCH_PREPARATION_V1" {return Err(CORRUPT);}
            let (strategy,confirmed)=strategy_anchors(tx,command,request,owner,false).await?;
            if strategy!=accepted["strategy_revision"] || confirmed!=accepted["factor_confirmation"] {return Err(CORRUPT);}
        },
        PreparationRequest::Backtest(input)=>backtest::validate_accepted(tx,command,owner,input,&accepted).await?,
    }
    let binding = Commands::verify_binding_in_transaction(tx, command)
        .await
        .map_err(db)?;
    let Binding::Accepted(receipt) = binding else {
        return Err(CORRUPT);
    };
    let expected=Admission::new(command.clone(),request.command_kind(),&request.intent(owner)?).map_err(db)?;
    if receipt.admission() != &expected
        || receipt.outcome().kind() != OutcomeKind::ResearchPreparationOperation
        || receipt.outcome().id() != hash(&accepted)?
        || text(&accepted, "accepted_at")?
            .parse::<OnlyUtcDateTime>()
            .map_err(|_| CORRUPT)?
            != receipt.accepted_at()
    {
        return Err(CORRUPT);
    }
    let revision: i64 = row.try_get(3).map_err(db)?;
    if revision < 0 {
        return Err(CORRUPT);
    }
    let o = Operation {
        command: command.clone(),
        owner: owner.into(),
        request,
        accepted,
        revision,
        state: State::parse(&row.try_get::<_, String>(4).map_err(db)?)?,
        phase: row.try_get(5).map_err(db)?,
        outputs: parse(&row.try_get::<_, String>(6).map_err(db)?)?,
        detail: parse(&row.try_get::<_, String>(7).map_err(db)?)?,
    };
    if o.phase.is_empty()
        || !o.phase.bytes().all(|b| b.is_ascii_uppercase() || b == b'_')
        || (o.revision == 0) != (o.state == State::Accepted)
        || (o.state == State::Accepted
            && (o.phase != "ACCEPTED" || o.outputs != json!({}) || !o.detail.is_null()))
        || (o.state == State::Ready
            && (o.outputs.get("ready").is_none() || o.phase != "READY_FOR_HUMAN_CONFIRMATION"))
        || (o.state == State::Running
            && o.phase == "CONFIRMING"
            && o.outputs.get("ready").is_none())
        || (matches!(o.state, State::CancelRequested | State::Cancelled)
            && o.outputs.get("cancellation").is_none())
        || (o.outputs.get("cancellation").is_some()
            && !matches!(
                o.state,
                State::CancelRequested | State::Cancelled | State::Unknown
            ))
        || (o.state == State::InputPending && o.outputs.get("environment").is_none())
    {
        return Err(CORRUPT);
    }
    if o.outputs.as_object().is_none_or(|m| {
        m.keys()
            .any(|k| !matches!(k.as_str(), "environment" | "ready" | "cancellation"))
    }) {
        return Err(CORRUPT);
    }
    if o.outputs.get("cancellation").is_some() {
        validate_cancellation(tx, &o).await?;
    }
    if o.outputs.get("ready").is_some() {
        validate_ready(&o, &o.outputs)?;
    }
    if o.outputs.get("environment").is_some() {
        validate_environment(tx, &o).await?;
    }
    Ok(o)
}
fn parse(raw: &str) -> Result<Value> {
    if raw.len() > 8 * 1024 * 1024 {
        return Err(UNAVAILABLE);
    }
    let v: Value = serde_json::from_str(raw).map_err(|_| CORRUPT)?;
    if canonical(&v)? != raw {
        return Err(CORRUPT);
    }
    Ok(v)
}
async fn update(
    tx: &Transaction<'_>,
    o: &Operation,
    state: State,
    phase: &str,
    outputs: &Value,
    detail: &Value,
) -> Result<Operation> {
    for (key, value) in o.outputs.as_object().ok_or(CORRUPT)? {
        if outputs.get(key) != Some(value) {
            return Err(CORRUPT);
        }
    }
    if !legal_transition(o.state, state, phase) {
        return Err("RESEARCH_PREPARATION_ILLEGAL_TRANSITION");
    }
    if state == State::Cancelled
        && matches!(o.state, State::Unknown | State::CancelRequested)
        && outputs.get("cancellation").is_none()
    {
        return Err("RESEARCH_PREPARATION_ILLEGAL_TRANSITION");
    }
    if phase.is_empty() || !phase.bytes().all(|b| b.is_ascii_uppercase() || b == b'_') {
        return Err(INVALID);
    }
    let revision = o.revision.checked_add(1).ok_or(CORRUPT)?;
    let out = canonical(outputs)?;
    let info = canonical(detail)?;
    let n=tx.execute("UPDATE research_preparation SET revision=$3,state=$4,phase=$5,outputs_payload=$6,detail_payload=$7 WHERE command_id=$1::text::uuid AND revision=$2",&[&o.command.value(),&o.revision,&revision,&state.as_str(),&phase,&out,&info]).await.map_err(db)?;
    if n != 1 {
        return Err("RESEARCH_PREPARATION_STALE");
    }
    load(tx, &o.command, &o.owner).await
}
fn exact_fields(value: &Value, fields: &[&str]) -> Result<()> {
    if value
        .as_object()
        .is_none_or(|m| m.len() != fields.len() || fields.iter().any(|k| !m.contains_key(*k)))
    {
        return Err(CORRUPT);
    }
    Ok(())
}
fn validate_ready(o: &Operation, outputs: &Value) -> Result<()> {
    if o.request.is_backtest(){return backtest::validate_ready(o,outputs);}
    if o.request.is_strategy(){return validate_strategy_ready(o,outputs);}
    let ready = &outputs["ready"];
    let record = &ready["prepared_study"];
    exact_fields(
        ready,
        &[
            "preparation_command_id",
            "study_proposal_fingerprint",
            "factor_confirmation_command_id",
            "revision_fingerprint",
            "runtime_generation_fingerprint",
            "installed_proof_fingerprint",
            "dataset_materialization_id",
            "source_selection",
            "prepared_study",
            "prepared_study_fingerprint",
            "prepared_inputs",
        ],
    )?;
    exact_fields(
        record,
        &[
            "schema_version",
            "command_id",
            "owner",
            "request",
            "decision_group_fingerprint",
        ],
    )?;
    let request: crate::persistence::research_submission::Request =
        serde_json::from_value(record["request"].clone()).map_err(|_| CORRUPT)?;
    let spec = &request.specification;
    crate::application::research_run::verify_native_spec_record(&spec.record()?)?;
    let original = validated_inputs(&o.accepted["study"], &o.accepted["factor_confirmation"])?;
    let preview = &o.accepted["factor_confirmation"]["snapshot"]["preview"];
    let future = CommandId::new(&o.request.research_command()).map_err(db)?;
    let environment = &outputs["environment"];
    let r = &ready["prepared_inputs"];
    let mut fields = Vec::from([
        "schema_version",
        "contract",
        "runtime_generation_fingerprint",
        "execution_binding",
        "runtime_work_binding",
        "factor_preparation_fingerprint",
        "factor_revision_fingerprint",
        "input_window",
        "dataset_snapshot_fingerprint",
        "dataset_materialization",
        "dataset_construction_fingerprint",
        "algorithm_resolution",
    ]);
    if spec.authoring_generation_fingerprint.is_some() {
        fields.push("authoring_generation_fingerprint");
    }
    exact_fields(r, &fields)?;
    if !spec.matches_prepared_authoring(r) {
        return Err(CORRUPT);
    }
    if record["schema_version"] != 1
        || record["command_id"] != future.value()
        || record["owner"] != o.owner
        || !text(record, "decision_group_fingerprint").is_ok_and(crate::is_sha256_hex)
        || ready["preparation_command_id"] != o.command.value()
        || ready["study_proposal_fingerprint"] != o.request.factor()?.study_proposal_fingerprint
        || ready["factor_confirmation_command_id"]
            != o.accepted["factor_confirmation"]["confirmation_command_id"]
        || ready["prepared_study_fingerprint"] != hash(record)?
        || request.schema_version != 1
        || request.parent_run_id.is_some()
        || request.policy_id != "onlyalpha.factor-research"
        || request.policy_version != "1"
        || request.factor_proposal_fingerprint
            != text(&o.accepted["study"], "factor_proposal_fingerprint")?
        || spec.draft != *original.draft.record()
        || spec.revision != original.revision
        || spec.candidate
            != json!({"hypothesis":preview["hypothesis"],"expression":preview["expression"]})
        || spec.record()?["study"] != o.accepted["study"]["study"]
        || ready["revision_fingerprint"] != spec.revision["revision_fingerprint"]
        || r["runtime_work_binding"] != environment["binding"]
        || r["runtime_work_binding"]["work_id"]
            != crate::persistence::research_submission::run_id(&future)
        || r["input_window"] != original.window.to_record()
        || r["factor_preparation_fingerprint"] != original.factor.fingerprint()
        || r["factor_revision_fingerprint"] != spec.revision["revision_fingerprint"]
        || r["execution_binding"] != spec.execution_binding
        || r["dataset_snapshot_fingerprint"] != spec.dataset_snapshot_fingerprint
        || r["runtime_generation_fingerprint"] != spec.runtime_generation_fingerprint
        || environment["installed_proof"]["algorithm_artifact"]
            != spec.algorithm_artifact_fingerprint
        || r["algorithm_resolution"]["algorithm_artifact"] != spec.algorithm_artifact_fingerprint
        || r["algorithm_resolution"]["factor_revision_fingerprint"]
            != spec.revision["revision_fingerprint"]
        || ready["runtime_generation_fingerprint"] != r["runtime_generation_fingerprint"]
        || ready["dataset_materialization_id"] != r["dataset_materialization"]["materialization_id"]
        || r["dataset_materialization"]["dataset_snapshot_fingerprint"]
            != spec.dataset_snapshot_fingerprint
        || ready["installed_proof_fingerprint"] != environment["installed_proof_fingerprint"]
        || ready["runtime_generation_fingerprint"] != environment["runtime_generation_fingerprint"]
    {
        return Err(CORRUPT);
    }
    let selection = &ready["source_selection"];
    exact_fields(
        selection,
        &[
            "preparation_command_id",
            "source",
            "acquisition",
            "scope",
            "revision",
            "seal",
        ],
    )?;
    if selection["preparation_command_id"] != o.command.value()
        || selection["source"] != o.accepted["study"]["advice"]["source"]
        || selection["scope"] != selection["revision"]["scope"]
        || selection["revision"]["revision_id"] != selection["seal"]["revision_id"]
        || selection["acquisition"]["status"] != "COMPLETE"
        || selection["acquisition"]["revision_id"] != selection["revision"]["revision_id"]
        || selection["acquisition"]["revision_fingerprint"] != selection["revision"]["fingerprint"]
        || selection["acquisition"]["seal_id"] != selection["seal"]["seal_id"]
    {
        return Err(CORRUPT);
    }
    Ok(())
}

/// Pure reconstruction and supported-profile bounds, before any authoring/runtime effect.
pub(crate) struct Inputs {
    pub(crate) advice: crate::application::factor_studies::Advice,
    pub(crate) draft: crate::application::private_assets::authoring::Draft,
    pub(crate) revision: Value,
    pub(crate) factor: crate::application::research_factor::CompiledFactor,
    pub(crate) window: crate::application::research_factor::InputWindow,
}
pub(crate) fn validated_inputs(study: &Value, confirmed: &Value) -> Result<Inputs> {
    let advice: crate::application::factor_studies::Advice =
        serde_json::from_value(study["advice"].clone()).map_err(|_| CORRUPT)?;
    let scientific = advice.study()?;
    let preview = &confirmed["snapshot"]["preview"];
    let draft = crate::application::private_assets::authoring::Draft::new(preview["draft"].clone())
        .map_err(|e| e.code())?;
    let revision = draft.revision().map_err(|e| e.code())?;
    let candidate = json!({"name":"Factor","purpose":"Research","hypothesis":preview["hypothesis"],"expression":preview["expression"]});
    let factor =
        crate::application::research_factor::compile(&candidate, draft.record(), &revision)?;
    let window = factor.window(crate::application::research_factor::Window {
        start_ns: scientific.samples[0].start_ns,
        end_ns: scientific.samples[1].end_ns,
        bar_ns: scientific.bar_ns,
        horizon_bars: scientific.horizon_bars,
    })?;
    let width = window
        .dataset_end_ns()
        .checked_sub(window.dataset_start_ns())
        .ok_or(INVALID)?;
    if width > 7 * 86400 * 1_000_000_000u64 {
        return Err("RESEARCH_PREPARATION_WINDOW_UNSUPPORTED");
    }
    for sample in &scientific.samples {
        if ((sample.end_ns - sample.start_ns) / scientific.bar_ns)
            .checked_sub(u64::from(scientific.horizon_bars))
            .is_none_or(|n| n < 10 * u64::from(scientific.expected_block_length))
        {
            return Err("RESEARCH_PREPARATION_INSUFFICIENT_BLOCK_SCOPE");
        }
    }
    Ok(Inputs {
        advice,
        draft,
        revision,
        factor,
        window,
    })
}

fn legal_transition(from: State, to: State, phase: &str) -> bool {
    use State::*;
    matches!(
        (from, to),
        (Accepted, Running | Cancelled | Blocked)
            | (
                Running,
                Running | InputPending | Ready | Blocked | Unknown | CancelRequested
            )
            | (InputPending, Running | Cancelled)
            | (Blocked, Running | Cancelled)
            | (Unknown, Running | CancelRequested)
            | (CancelRequested, Unknown | CancelRequested)
    ) || matches!(
        (from, to),
        (CancelRequested, Cancelled) | (Unknown, Cancelled)
    ) && phase == "OWNER_DRAINED"
        || from == Ready && to == Running && phase == "CONFIRMING"
        || from == Ready && to == Cancelled && phase == "CANCELLATION"
}
async fn validate_environment(tx: &Transaction<'_>, o: &Operation) -> Result<()> {
    if o.request.is_backtest(){return backtest::validate_environment(o);}
    let e = &o.outputs["environment"];
    let publication = &e["publication"];
    let (_,revision)=algorithm_inputs(o)?;
    let id=text(&revision,"factor_id")?;
    let command=CommandId::new(text(publication,"command_id")?).map_err(db)?;
    let actual=crate::persistence::private_factor_postgres::bound(tx,id,&command,None).await.map_err(|e|e.code())?.ok_or(CORRUPT)?;
    if actual!=*publication || actual["result"]["revision"]!=revision {return Err(CORRUPT);}
    let generation = text(e, "runtime_generation_fingerprint")?;
    let proof = &e["installed_proof"];
    let mut body = proof.clone();
    body.as_object_mut()
        .ok_or(CORRUPT)?
        .remove("installed_proof_fingerprint");
    if !crate::is_sha256_hex(generation)
        || proof["contract"] != "ONLYALPHA_INSTALLED_RESEARCH_ENVIRONMENT_V1"
        || proof["release_manifest_sha256"] != o.request.release()
        || proof["runtime_generation_fingerprint"] != generation
        || hash(&body)? != text(e, "installed_proof_fingerprint")?
        || proof["installed_proof_fingerprint"] != e["installed_proof_fingerprint"]
        || proof["algorithm_observation"]["factor_revision_fingerprint"]
            != revision["revision_fingerprint"]
    {
        return Err(CORRUPT);
    }
    let binding = &e["binding"];
    let future = CommandId::new(&o.request.research_command()).map_err(db)?;
    if binding["kind"] != "RuntimeWorkBound"
        || binding["work_id"] != crate::persistence::research_submission::run_id(&future)
        || binding["reason"] != "research"
        || binding["generation_fingerprint"] != generation
    {
        return Err(CORRUPT);
    }
    validate_activation(o, e)
}
/// A reused activation is an original lifecycle observation, not a new preparation command.
/// The controller proves current equality under the original Registry lock before binding work;
/// retained readers additionally reprove this exact event and binding in the original journal.
pub(crate) fn validate_activation(o: &Operation, e: &Value) -> Result<()> {
    let generation = text(e, "runtime_generation_fingerprint")?;
    let activation = &e["activation"];
    if activation["kind"] != "GenerationActivated"
        || activation["generation_fingerprint"] != generation
    {
        return Err(CORRUPT);
    }
    match text(e, "activation_disposition")? {
        "ACTIVATED" => {
            let reason: Value =
                serde_json::from_str(text(activation, "reason")?).map_err(|_| CORRUPT)?;
            if reason["contract"] != "ONLYALPHA_GENERATION_COMMAND_V1"
                || reason["command_id"] != o.command.value()
                || activation["actor"] != o.owner
                || activation["expected_current"] != json!(o.request.expected_active())
            {
                return Err(CORRUPT);
            }
        }
        "REUSED_CURRENT" => {
            if o.request.expected_active() != Some(generation) {
                return Err(CORRUPT);
            }
        }
        _ => return Err(CORRUPT),
    }
    Ok(())
}

/// Original durable facts in this semantic namespace forbid treating a lost Registry as fresh.
pub(crate) async fn runtime_history_exists(tx: &Transaction<'_>) -> Result<bool> {
    let row=tx.query_one("SELECT EXISTS(SELECT 1 FROM research_preparation WHERE outputs_payload::jsonb ? 'environment') OR EXISTS(SELECT 1 FROM research_factor_study_authorization) OR EXISTS(SELECT 1 FROM research_run WHERE specification_schema_version IN (4,5,6)) OR EXISTS(SELECT 1 FROM research_strategy_study_authorization) OR EXISTS(SELECT 1 FROM backtest_run)",&[]).await.map_err(db)?;
    row.try_get(0).map_err(db)
}
pub(crate) fn guard_fresh_runtime(has_history: bool) -> Result<()> {
    if has_history {
        Err("RESEARCH_RUNTIME_HISTORY_UNAVAILABLE")
    } else {
        Ok(())
    }
}

pub(crate) async fn guard_submission(
    tx: &Transaction<'_>,
    o: &Operation,
    expected: &str,
) -> Result<()> {
    Commands::lock_command(tx, &o.command).await.map_err(db)?;
    let current = load(tx, &o.command, &o.owner).await?;
    if current.outputs.get("cancellation").is_some()
        || !matches!(current.state, State::Ready | State::Running)
        || (if current.request.is_backtest(){&current.outputs["ready"]["preparation_fingerprint"]}else{&current.outputs["ready"]["prepared_study_fingerprint"]}) != expected
        || current.request.research_command() != o.request.research_command()
        || current.accepted != o.accepted
    {
        return Err("RESEARCH_PREPARATION_STALE");
    }
    require_current(tx,&current).await?;
    Ok(())
}

async fn validate_cancellation(tx: &Transaction<'_>, o: &Operation) -> Result<()> {
    let c = &o.outputs["cancellation"];
    let command = CommandId::new(text(c, "command_id")?).map_err(db)?;
    let revision = c["expected_revision"]
        .as_i64()
        .filter(|r| *r >= 0)
        .ok_or(CORRUPT)?;
    if c.as_object().is_none_or(|m| m.len() != 3) {
        return Err(CORRUPT);
    }
    let fp = hash(
        &json!({"contract":"ONLYALPHA_CANCEL_RESEARCH_PREPARATION_V1","owner":o.owner,"body":{"preparation_command_id":o.command.value(),"expected_revision":revision}}),
    )?;
    let expected = Admission::new(
        command.clone(),
        o.request.cancel_kind(),
        &fp,
    )
    .map_err(db)?;
    let Binding::Accepted(receipt) = Commands::verify_binding_in_transaction(tx, &command)
        .await
        .map_err(db)?
    else {
        return Err(CORRUPT);
    };
    if receipt.admission() != &expected
        || receipt.outcome().kind() != OutcomeKind::ResearchPreparationOperation
        || receipt.outcome().id() != hash(&o.accepted)?
        || text(c, "requested_at")?
            .parse::<OnlyUtcDateTime>()
            .map_err(|_| CORRUPT)?
            != receipt.accepted_at()
    {
        return Err(CORRUPT);
    }
    Ok(())
}

async fn strategy_anchors(tx:&Transaction<'_>,command:&CommandId,input:&StrategyPrepareInput,owner:&str,current:bool)->Result<(Value,Value)> {
    use crate::application::{private_assets,private_strategy::Definition};
    let context=input.validate(command)?;
    let strategy=private_assets::strategy_revision_in_transaction(tx,&input.strategy_id,&input.strategy_revision_fingerprint).await.map_err(|e|e.code())?;
    if strategy["definition_fingerprint"]!=input.definition_fingerprint {return Err("RESEARCH_PREPARATION_STRATEGY_MISMATCH");}
    let definition=Definition::from_record(&strategy["definition"])?;
    context.definition(&definition)?;
    let d=definition.to_record();
    let deps=d["factor_revision_dependencies"].as_array().filter(|v|v.len()==1).ok_or(INVALID)?;
    let dependency=&deps[0];let id=text(dependency,"factor_id")?;
    let factor=private_assets::factor_revision_in_transaction(tx,id,text(dependency,"revision_fingerprint")?).await.map_err(|e|e.code())?;
    let confirmed=factor_proposals::confirmed_strategy_research_input(tx,&input.factor_proposal_fingerprint,owner,current).await?;
    let draft=crate::application::private_assets::authoring::Draft::new(confirmed["snapshot"]["preview"]["draft"].clone()).map_err(|e|e.code())?;
    if draft.factor_id()!=id || draft.revision().map_err(|e|e.code())?!=factor
        || d["universe"]!=json!({"kind":"SINGLE_INSTRUMENT","instruments":[input.source.instrument_id]})
        || d["market_input"]["bar_semantic"]["formation"]!=json!({"schema_version":1,"kind":"FIXED_DURATION","window_minutes":1,"stride_minutes":1,"alignment":"SESSION_START"})
        || d["market_input"]["bar_semantic"]["price_type"]!="LAST"
        || d["market_input"]["bar_semantic"]["adjustment_policy"]!="RAW"
        || d["market_input"]["construction_requirement"]["kind"]!="EXACT_RECIPE"
        || d["market_input"]["construction_requirement"]["recipe"]["kind"]!="PROVIDER_NATIVE"
    {return Err("RESEARCH_PREPARATION_STRATEGY_MISMATCH");}
    let factors=d["calculations"].as_array().ok_or(INVALID)?.iter().filter(|v|v["type_reference"]["kind"]=="FACTOR").collect::<Vec<_>>();
    if factors.len()!=1 || factors[0]["type_reference"]["type_id"]!=id || factors[0]["type_reference"]["semantic_version"]!=factor["semantic_version"] {return Err(INVALID);}
    compile_confirmed(&confirmed,&factor)?;
    Ok((strategy,confirmed))
}
fn compile_confirmed(confirmed:&Value,revision:&Value)->Result<crate::application::research_factor::CompiledFactor> {
    let preview=&confirmed["snapshot"]["preview"];
    let candidate=json!({"name":"Factor","purpose":"Research","hypothesis":preview["hypothesis"],"expression":preview["expression"]});
    crate::application::research_factor::compile(&candidate,&preview["draft"],revision)
}
/// The actual installed preparer consumes one exact confirmed Factor in both profiles.
pub(crate) fn algorithm_inputs(o:&Operation)->Result<(crate::application::research_factor::CompiledFactor,Value)> {
    match &o.request {
        PreparationRequest::Backtest(_)=>Err(INVALID),
        PreparationRequest::Factor(_)=> {let v=validated_inputs(&o.accepted["study"],&o.accepted["factor_confirmation"])?;Ok((v.factor,v.revision))},
        PreparationRequest::Strategy(_)=> {
            let revision=crate::application::private_assets::authoring::Draft::new(o.accepted["factor_confirmation"]["snapshot"]["preview"]["draft"].clone()).map_err(|e|e.code())?.revision().map_err(|e|e.code())?;
            Ok((compile_confirmed(&o.accepted["factor_confirmation"],&revision)?,revision))
        },
    }
}
pub(crate) async fn require_current(tx:&Transaction<'_>,o:&Operation)->Result<()> {
    match &o.request {
        PreparationRequest::Backtest(v)=>backtest::validate_accepted(tx,&o.command,&o.owner,v,&o.accepted).await?,
        PreparationRequest::Factor(v)=> {if factor_studies::current(tx,&v.study_proposal_fingerprint,&o.owner).await?!=o.accepted["study"] {return Err("RESEARCH_PREPARATION_STUDY_STALE");}},
        PreparationRequest::Strategy(v)=> {let (strategy,confirmed)=strategy_anchors(tx,&o.command,v,&o.owner,true).await?;if strategy!=o.accepted["strategy_revision"] || confirmed!=o.accepted["factor_confirmation"] {return Err("RESEARCH_PREPARATION_STRATEGY_MISMATCH");}},
    }
    Ok(())
}
fn validate_strategy_ready(o:&Operation,outputs:&Value)->Result<()> {
    use crate::application::{private_strategy::Definition,strategy_research::{DecisionGraph,RunSpecification,Specification}};
    let input=o.request.strategy()?;let context=input.validate(&o.command)?;
    let ready=&outputs["ready"];let record=&ready["prepared_study"];let p=&ready["prepared_inputs"];let environment=&outputs["environment"];
    exact_fields(ready,&["preparation_command_id","strategy_revision_fingerprint","factor_confirmation_command_id","runtime_generation_fingerprint","installed_proof_fingerprint","dataset_materialization_id","source_selection","prepared_study","prepared_study_fingerprint","prepared_inputs"])?;
    exact_fields(record,&["schema_version","command_id","owner","request","composition_fingerprint","decision_group_fingerprint"])?;
    exact_fields(p,&["schema_version","contract","composition","runtime_generation_fingerprint","runtime_work_binding","execution_binding","input_window","dataset_snapshot_fingerprint","dataset_materialization","dataset_construction_fingerprint","run_specification_fingerprint","algorithm_resolution_request","algorithm_resolution","native_implementations"])?;
    let request=crate::persistence::research_submission::strategy::Request::from_record(&record["request"])?;
    let spec=RunSpecification::from_record(request.specification().record())?;let s=spec.record();
    let policy=crate::bootstrap::research_namespace::policy();
    let future=CommandId::new(o.request.research_command()).map_err(db)?;
    let definition=Definition::from_record(&o.accepted["strategy_revision"]["definition"])?;
    let declared=definition.to_record();
    let nodes=p["algorithm_resolution"]["nodes"].as_array().ok_or(CORRUPT)?;
    let project=|instances:&Value|->Result<Value>{let mut result=Vec::new();for instance in instances.as_array().ok_or(CORRUPT)? {let matches=nodes.iter().filter(|n|n["instance_key"]==instance["instance_key"]).collect::<Vec<_>>();if matches.len()!=1{return Err(CORRUPT);}let node=matches[0];result.push(json!({"instance_key":node["instance_key"],"definition":node["definition"],"definition_fingerprint":node["definition_fingerprint"],"type_declaration":node["type_declaration"]}));}Ok(json!(result))};
    let decision=DecisionGraph::derive(&definition,&project(&declared["calculations"])?)?;
    let targets=DecisionGraph::target_graph(&context,&project(&context.record()["targets"])?)?;
    let science=Specification::derive(&context.definition(&definition)?,&decision,&targets,text(p,"dataset_snapshot_fingerprint")?)?;
    let mut window=decision.input_window(&context,60_000_000_000)?;window.as_object_mut().ok_or(CORRUPT)?.remove("research_context_fingerprint");
    if record["schema_version"]!=1 || record["command_id"]!=future.value() || record["owner"]!=o.owner
        || ready["preparation_command_id"]!=o.command.value() || ready["strategy_revision_fingerprint"]!=input.strategy_revision_fingerprint
        || ready["factor_confirmation_command_id"]!=o.accepted["factor_confirmation"]["confirmation_command_id"]
        || ready["prepared_study_fingerprint"]!=hash(record)? || !text(record,"decision_group_fingerprint").is_ok_and(crate::is_sha256_hex)
        || request.parent_run_id().is_some() || request.policy()!=(text(&policy,"policy_id")?,text(&policy,"policy_version")?)
        || s["scientific_specification"]!=*science.record() || s["decision"]!=decision.record() || s["target_graph"]!=targets.to_record()
        || s["input_window"]!=window || p["input_window"]!=window || p["schema_version"]!=1 || p["contract"]!="ONLYALPHA_STRATEGY_RESEARCH_PREPARED_INPUTS_V1"
        || p["run_specification_fingerprint"]!=spec.fingerprint()? || p["runtime_work_binding"]!=environment["binding"]
        || p["runtime_work_binding"]["work_id"]!=crate::persistence::research_submission::run_id(&future)
        || p["composition"]["private_strategy_id"]!=input.strategy_id || p["composition"]["private_strategy_revision_fingerprint"]!=input.strategy_revision_fingerprint
        || p["composition"]["private_strategy_definition_fingerprint"]!=input.definition_fingerprint || p["composition"]["research_context_fingerprint"]!=context.fingerprint()?
        || p["composition"]["research_definition_fingerprint"]!=context.definition(&definition)?.fingerprint()?
        || record["composition_fingerprint"]!=p["composition"]["composition_fingerprint"]
        || p["execution_binding"]!=s["execution_binding"] || p["dataset_snapshot_fingerprint"]!=s["scientific_specification"]["dataset_snapshot_fingerprint"]
        || p["runtime_generation_fingerprint"]!=s["runtime_generation_fingerprint"] || p["composition"]["catalog_generation_fingerprint"]!=s["catalog_generation_fingerprint"]
        || environment["installed_proof"]["algorithm_artifact"]!=s["algorithm_artifact_fingerprint"] || p["algorithm_resolution"]["algorithm_artifact"]!=s["algorithm_artifact_fingerprint"]
        || ready["runtime_generation_fingerprint"]!=p["runtime_generation_fingerprint"] || ready["runtime_generation_fingerprint"]!=environment["runtime_generation_fingerprint"]
        || ready["installed_proof_fingerprint"]!=environment["installed_proof_fingerprint"] || ready["dataset_materialization_id"]!=p["dataset_materialization"]["materialization_id"]
        || p["dataset_materialization"]["dataset_snapshot_fingerprint"]!=p["dataset_snapshot_fingerprint"]
    {return Err(CORRUPT);}
    let selection=&ready["source_selection"];
    exact_fields(selection,&["preparation_command_id","source","acquisition","scope","revision","seal"])?;
    if selection["preparation_command_id"]!=o.command.value() || selection["source"]!=serde_json::to_value(&input.source).map_err(db)?
        || selection["scope"]!=selection["revision"]["scope"] || selection["revision"]["revision_id"]!=selection["seal"]["revision_id"]
        || selection["acquisition"]["status"]!="COMPLETE" || selection["acquisition"]["revision_id"]!=selection["revision"]["revision_id"]
        || selection["acquisition"]["revision_fingerprint"]!=selection["revision"]["fingerprint"] || selection["acquisition"]["seal_id"]!=selection["seal"]["seal_id"]
    {return Err(CORRUPT);}Ok(())
}

async fn commit_updated(tx:Transaction<'_>,expected:Operation)->Result<Operation> {
    if expected.request.is_backtest() {
        tx.batch_execute("SET CONSTRAINTS ALL IMMEDIATE").await.map_err(db)?;
        let actual=load(&tx,&expected.command,&expected.owner).await?;
        if actual.accepted!=expected.accepted || actual.revision!=expected.revision || actual.state!=expected.state
            || actual.phase!=expected.phase || actual.outputs!=expected.outputs || actual.detail!=expected.detail {return Err(CORRUPT);}
        crate::persistence::authority_session::AuthoritySession::verify_transaction(&tx).await.map_err(|_|UNAVAILABLE)?;
    }
    tx.commit().await.map_err(db)?;Ok(expected)
}
