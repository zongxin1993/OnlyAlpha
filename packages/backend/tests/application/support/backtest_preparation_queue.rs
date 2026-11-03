//! Existing queue's third actual consumer, using a completed real Strategy Run.
//! Controlled scientific/market inputs are technical preconditions, never Shipping evidence.
use crate::{
    application::{backtest_preparation::{BacktestPrepareInput,run_id},command::CommandId,factor_content::hash,
        frozen_strategy::FrozenStore,qualification::Request as QualificationRequest,qualification_policy::{Policy,Store as Policies}},
    bootstrap::deployment,
    persistence::{authority_session::AuthoritySession,qualification_commands::Qualifications,
        qualification_decision::Store as Decisions,research_evidence::Store as Evidence,research_preparation::{self,BacktestAcceptance,Preparations,State},
        research_submission,strategy_promotion::{self,Promotions,Request as PromotionRequest}},
    security::{human_access::{Access,Admission},protected_files},
};
use serde_json::{Value,json};
use std::{os::fd::AsFd,path::Path,sync::Arc};
const OWNER:&str="local-developer";
const WORK:usize=64*1024*1024;
fn text<'a>(v:&'a Value,k:&str)->&'a str {v[k].as_str().unwrap()}
fn command(v:&Value,k:&str)->CommandId {CommandId::new(text(v,k)).unwrap()}
fn output(v:Value) {println!("BACKTEST_PREPARATION_VALUE {v}");std::io::Write::flush(&mut std::io::stdout()).unwrap();}
pub(super) async fn run_phase(session:&mut AuthoritySession,root:&Path,phase:&str) {
    let request:Value=serde_json::from_slice(&std::fs::read(std::env::var("ONLYALPHA_BACKTEST_PREPARATION_REQUEST").unwrap()).unwrap()).unwrap();
    let preparation=command(&request,"preparation_command");
    // Observation of an original accepted operation comes before reconstructing
    // any current qualification/runtime/filesystem grant.
    if phase=="replay-unavailable" {
        let input:BacktestPrepareInput=serde_json::from_value(request["input"].clone()).unwrap();
        let operation=Preparations::new(session.client_mut().await.unwrap()).existing_backtest(&preparation,OWNER,&input).await.unwrap().unwrap();
        assert_eq!(operation.accepted,request["accepted"]);assert_eq!(operation.revision,0);
        output(json!({"replayed":true,"view":operation.view()}));return;
    }
    let descriptor=protected_files::open_directory(root).unwrap();
    let namespace=deployment::load_semantic_store_id_at(&descriptor).unwrap();
    let frozen=Arc::new(FrozenStore::open(descriptor.as_fd()).unwrap());
    let access=Access::new(&"a".repeat(64)).unwrap();
    let http=http::Request::builder().uri("/api/v2/integration-types").header("host","127.0.0.1:5173")
        .header("cookie",format!("onlyalpha_dev_session={}","a".repeat(64))).body(()).unwrap();
    let Admission::Owner(human)=access.admit(&http).unwrap() else{panic!("actual Human identity")};
    let policies=Arc::new(Policies::open(descriptor.as_fd()).unwrap());
    let mut record=json!({"schema_version":1,"policy_id":"experimental-backtest","policy_version":"1","gate":"RESEARCH_TO_BACKTEST",
        "missing_evidence_behavior":"FAIL","aggregation":"ALL","criteria":[
        {"criterion_id":"calculation-count","evidence_kind":"RESEARCH_RESULT","metric":"research.calculation_result_count","comparison":"GE","threshold":"1"},
        {"criterion_id":"statistics-count","evidence_kind":"RESEARCH_RESULT","metric":"research.statistics_result_count","comparison":"GE","threshold":"2"}]});
    let mut identity=record.clone();identity["domain"]=json!("onlyalpha.strategy.qualification-policy");record["policy_fingerprint"]=json!(hash(&identity).unwrap());
    policies.admit(session,&namespace,&[Policy::from_json(&record.to_string(),WORK).unwrap()],WORK).await.unwrap();
    let run=research_submission::load(session.client_mut().await.unwrap(),text(&request,"run_id"),Some(OWNER)).await.unwrap();
    assert!(run.completed());assert_eq!(run.strategy_specification().unwrap().record()["schema_version"],5);
    let evidence=Evidence::open(root).unwrap().with_runtime_root(Path::new(text(&request,"runtime_root"))).unwrap();
    let counts=Arc::new(evidence.read_verified_counts(&run,&frozen,text(&request,"freeze_relation")).unwrap());
    let qualification=QualificationRequest::new(command(&request,"qualification_command"),counts.subject_strategy_fingerprint(),"experimental-backtest","1",
        &json!([{"kind":"RESEARCH_RESULT","evidence_fingerprint":counts.research_result_fingerprint(),
            "locator_fingerprint":counts.research_result_plan_fingerprint(),"subject_binding_fingerprint":counts.freeze_relation_fingerprint()}])).unwrap();
    let decisions=Arc::new(Decisions::open(root).unwrap());
    let at=text(&request,"at").parse().unwrap();
    let decision=Qualifications::new(session,&namespace,policies,decisions,frozen.clone(),&access,&human).execute(&qualification,counts.clone(),at).await.unwrap();
    let promotion=PromotionRequest::new(command(&request,"promotion_command"),counts.subject_strategy_fingerprint(),decision.fingerprint(),text(&record,"policy_fingerprint"),"Controlled current queue admission; experimental simulation only").unwrap();
    let promoted=Promotions::new(session,&namespace,frozen.clone(),&access,&human).promote(&promotion,decision.clone(),at).await.unwrap();
    let admission=strategy_promotion::read_verified_admission(session.client_mut().await.unwrap(),&namespace,frozen,decision,
        counts.subject_strategy_fingerprint(),counts.freeze_relation_fingerprint(),promoted.fingerprint(),WORK).await.unwrap();
    if phase=="native-qualification" {
        // Only observations of the actual count/Policy/Decision/Promotion owners
        // leave this process. Host must re-open admission for the normal API.
        output(json!({"strategy_fingerprint":admission.strategy_fingerprint(),
            "freeze_relation_fingerprint":admission.freeze_relation_fingerprint(),
            "qualification_decision_fingerprint":admission.qualification_decision_fingerprint(),
            "promotion_fingerprint":admission.promotion_fingerprint()}));
        return;
    }
    let input:BacktestPrepareInput=serde_json::from_value(json!({"schema_version":2,"profile":"BTC_SPOT_NEXT_OPEN_BACKTEST_V1",
        "origin":{"kind":"FROZEN_STRATEGY","strategy_fingerprint":admission.strategy_fingerprint(),
        "freeze_relation_fingerprint":admission.freeze_relation_fingerprint(),"qualification_decision_fingerprint":admission.qualification_decision_fingerprint(),
        "promotion_fingerprint":admission.promotion_fingerprint()},"source":request["selected_source"],
        "release_manifest_fingerprint":request["release_manifest_fingerprint"],"expected_active_generation":request["runtime_generation"],
        "initialize_fresh_runtime":false,"backtest_command_id":request["backtest_command"]})).unwrap();
    if phase=="reject-pins" {
        for (index,key) in ["strategy_fingerprint","freeze_relation_fingerprint","qualification_decision_fingerprint","promotion_fingerprint"].iter().enumerate() {
            let id=research_preparation::child_command(&preparation,&format!("BAD_{index}")).unwrap();
            let mut changed=serde_json::to_value(&input).unwrap();
            changed["origin"][*key]=json!("f".repeat(64));
            changed["backtest_command_id"]=json!(research_preparation::child_command(&preparation,&format!("FUTURE_{index}")).unwrap().value());
            assert!(research_preparation::accept_backtest(session,&namespace,(&access,&human),&id,serde_json::from_value(changed).unwrap(),BacktestAcceptance::Frozen(&admission),at).await.is_err(),"{key}");
            assert_eq!(session.client_mut().await.unwrap().query_one("SELECT count(*) FROM product_command_admission WHERE command_id=$1::text::uuid",&[&id.value()]).await.unwrap().get::<_,i64>(0),0);
        }
        let wrong=deployment::SemanticStoreId::new("22222222-2222-4222-8222-222222222222").unwrap();
        assert!(research_preparation::accept_backtest(session,&wrong,(&access,&human),&preparation,input,BacktestAcceptance::Frozen(&admission),at).await.is_err());
        output(json!({"rejected_pins":true}));return;
    }
    if matches!(phase,"deferred-guard"|"deferred-receipt") {
        let sql=if phase=="deferred-guard" {
            "CREATE FUNCTION use_test_backtest_prepare_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER use_test_backtest_prepare_fault AFTER INSERT ON research_preparation DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.preparation_kind='BACKTEST_PREPARATION') EXECUTE FUNCTION use_test_backtest_prepare_fault()"
        } else {
            "CREATE FUNCTION use_test_backtest_prepare_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE product_command_receipt SET outcome_id=repeat('f',64) WHERE command_id=NEW.command_id; RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER use_test_backtest_prepare_fault AFTER INSERT ON product_command_receipt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.command_kind='PREPARE_BACKTEST') EXECUTE FUNCTION use_test_backtest_prepare_fault()"
        };
        session.client_mut().await.unwrap().batch_execute(sql).await.unwrap();
        assert!(research_preparation::accept_backtest(session,&namespace,(&access,&human),&preparation,input,BacktestAcceptance::Frozen(&admission),at).await.is_err());
        assert!(session.verify().await.is_err(),"deferred guard/receipt corruption invalidates the physical owner");
        output(json!({"deferred_refused":true}));return;
    }
    if phase=="stale-evidence" {
        use std::os::unix::fs::PermissionsExt;
        let path=Path::new(text(&request,"tamper_path"));let bytes=std::fs::read(path).unwrap();let mode=std::fs::metadata(path).unwrap().permissions();
        std::fs::set_permissions(path,std::fs::Permissions::from_mode(mode.mode()|0o200)).unwrap();
        let mut changed=bytes.clone();let last=changed.len()-1;changed[last]^=1;std::fs::write(path,&changed).unwrap();
        let refused=research_preparation::accept_backtest(session,&namespace,(&access,&human),&preparation,input,BacktestAcceptance::Frozen(&admission),at).await.is_err();
        std::fs::write(path,&bytes).unwrap();std::fs::set_permissions(path,mode).unwrap();assert!(refused);
        output(json!({"stale_evidence_refused":true}));return;
    }
    if phase=="cancel" {
        let original=Preparations::new(session.client_mut().await.unwrap()).existing_backtest(&preparation,OWNER,&input).await.unwrap().unwrap();
        let cancel=command(&request,"cancel_command");
        let cancelled=Preparations::new(session.client_mut().await.unwrap()).cancel(&cancel,&preparation,OWNER,0,at).await.unwrap();
        assert_eq!(cancelled.state,State::Cancelled);
        assert_eq!(Preparations::new(session.client_mut().await.unwrap()).cancel(&cancel,&preparation,OWNER,0,at).await.unwrap().view(),cancelled.view());
        let tx=session.client_mut().await.unwrap().transaction().await.unwrap();
        assert!(research_preparation::guard_submission(&tx,&original,&"a".repeat(64)).await.is_err());tx.rollback().await.unwrap();
        output(json!({"cancelled":true,"view":cancelled.view()}));return;
    }
    let operation=research_preparation::accept_backtest(session,&namespace,(&access,&human),&preparation,input.clone(),BacktestAcceptance::Frozen(&admission),at).await.unwrap();
    assert_eq!(operation.state,State::Accepted);assert_eq!(operation.revision,0);
    assert_eq!(operation.accepted["contract"],"ONLYALPHA_ACCEPTED_BACKTEST_PREPARATION_V2");
    assert_eq!(operation.accepted["input"],serde_json::to_value(&input).unwrap());
    for key in ["study","factor_confirmation","prepared_study","run_permit"] {assert!(operation.accepted.get(key).is_none());}
    let view=operation.view();assert_eq!(view["backtest_command_id"],input.backtest_command_id);
    assert_eq!(view["reserved_run_id"],run_id(&CommandId::new(&input.backtest_command_id).unwrap()));
    assert_ne!(view["reserved_run_id"],research_submission::run_id(&CommandId::new(&input.backtest_command_id).unwrap()));
    for key in ["research_command_id","research_outcome","prepared_study_fingerprint"] {assert!(view.get(key).is_none());}
    assert_eq!(Preparations::new(session.client_mut().await.unwrap()).for_backtest_origin(&input.origin,OWNER).await.unwrap().len(),1);
    let duplicate=research_preparation::child_command(&preparation,"DUPLICATE_FUTURE").unwrap();
    assert!(research_preparation::accept_backtest(session,&namespace,(&access,&human),&duplicate,input.clone(),BacktestAcceptance::Frozen(&admission),at).await.is_err());
    let mut strategy=super::strategy_preparation_queue::setup(session).await;
    strategy.research_command_id=input.backtest_command_id.clone();
    assert!(Preparations::new(session.client_mut().await.unwrap()).accept_strategy(&research_preparation::child_command(&preparation,"CROSS_KIND_FUTURE").unwrap(),OWNER,strategy,at).await.is_err(),"the original future Command is unique across all preparation kinds");
    let count:i64=session.client_mut().await.unwrap().query_one("SELECT count(*) FROM backtest_run",&[]).await.unwrap().get(0);assert_eq!(count,0,"accepted queue intent is not a Backtest Run or READY grant");
    output(json!({"input":input,"accepted":operation.accepted,"view":view}));
    assert_eq!(phase,"accept-no-reply");std::process::exit(86);
}
