//! Formal declaration and typed metadata checks; no Shipping/READY authority claim.
use super::{declaration,operation,Operation};
use crate::{application::{backtest_preparation::BacktestPrepareInput,command::CommandId},
    persistence::research_preparation::{Operation as Preparation,PreparationRequest,State},
    transport::research_wire::{BacktestPreparationView,BacktestPreparationRevisionInput,BacktestConfirmationInput,BacktestConfirmationOutcome}};
use http::Method;
use serde_json::{Value,json};
const PREPARATION:&str="00000000-0000-4000-8000-000000008201";
const FUTURE:&str="00000000-0000-4000-8000-000000008202";
fn fixture()->Preparation {
    // Value projection only. This controlled metadata is never a portable
    // actual Dataset, QualifiedAdmission, Runtime hold or execution permit.
    let input:BacktestPrepareInput=serde_json::from_value(json!({"schema_version":2,"profile":"BTC_SPOT_NEXT_OPEN_BACKTEST_V1",
        "origin":{"kind":"FROZEN_STRATEGY","strategy_fingerprint":"a".repeat(64),
        "freeze_relation_fingerprint":"b".repeat(64),"qualification_decision_fingerprint":"c".repeat(64),"promotion_fingerprint":"d".repeat(64)},
        "source":{"integration_id":"00000000-0000-4000-8000-000000008204","integration_revision_fingerprint":"e".repeat(64),"expected_type_id":"binance.spot.market_data","source_id":"binance.spot.market_data.live","environment":"LIVE","instrument_id":"BTCUSDT.BINANCE"},
        "release_manifest_fingerprint":"f".repeat(64),"expected_active_generation":"1".repeat(64),"initialize_fresh_runtime":false,"backtest_command_id":FUTURE})).unwrap();
    Preparation{command:CommandId::new(PREPARATION).unwrap(),owner:"local-developer".into(),request:PreparationRequest::Backtest(input.clone()),
        accepted:json!({"accepted_at":"2026-11-02T00:00:00Z","input":input}),revision:0,state:State::Accepted,phase:"ACCEPTED".into(),outputs:json!({}),detail:Value::Null}
}
#[test]
fn six_backtest_preparation_routes_are_actual_human_operations_with_typed_original_outcomes() {
    let (_,document)=declaration();let doc=serde_json::to_value(document).unwrap();
    for (method,path,verb,response,body) in [
        (Method::POST,"/api/v2/backtest/preparations","post","BacktestPrepareReply",Some("BacktestPrepareInput")),
        (Method::GET,"/api/v2/backtest/preparations/commands/{command_id}","get","BacktestPreparationCommandReply",None),
        (Method::POST,"/api/v2/backtest/preparations/{command_id}/resume","post","BacktestPreparationViewV2",Some("BacktestPreparationRevisionInput")),
        (Method::POST,"/api/v2/backtest/preparations/{command_id}/cancellation","post","BacktestPreparationViewV2",Some("BacktestPreparationRevisionInput")),
        (Method::GET,"/api/v2/backtest/preparations/{command_id}/ready","get","BacktestPreparationCommandReply",None),
        (Method::POST,"/api/v2/backtest/preparations/{command_id}/submit","post","BacktestConfirmationOutcome",Some("BacktestConfirmationInput")),
    ] {
        assert_eq!(operation(&method,path),Some(Operation::Implemented),"{method} {path}");
        let actual=&doc["paths"][path][verb];
        assert_eq!(actual["security"],json!([{"LocalDeveloperCookie":[]}]));
        assert_eq!(actual["responses"]["200"]["content"]["application/json"]["schema"]["$ref"],format!("#/components/schemas/{response}"));
        assert!(actual["responses"].get("501").is_none());
        for status in ["400","401","403","409","503"] {assert_eq!(actual["responses"][status]["content"]["application/json"]["schema"]["$ref"],"#/components/schemas/NativeErrorEnvelope");}
        if let Some(body)=body {
            assert_eq!(actual["requestBody"]["content"]["application/json"]["schema"]["$ref"],format!("#/components/schemas/{body}"));
            assert!(actual["parameters"].as_array().unwrap().iter().any(|p|p["in"]=="header"&&p["name"]=="Idempotency-Key"&&p["required"]==true));
        }else {
            assert!(actual.get("requestBody").is_none());
            assert!(actual["parameters"].as_array().is_none_or(|p|p.iter().all(|p|p["in"]!="query")),"observing history must not require a replacement source/runtime");
        }
        assert_eq!(operation(&Method::PUT,path),None);
        assert_eq!(operation(&Method::DELETE,path),None);
    }
    let components=&doc["components"]["schemas"];
    for name in ["BacktestPreparationViewV2","BacktestPreparationRevisionInput","BacktestConfirmationInput","BacktestConfirmationOutcome"] {
        assert_eq!(components[name]["additionalProperties"],false,"{name}");
    }
    assert_eq!(components["BacktestPreparationViewV2"]["properties"]["revision"]["type"],"string");
    assert_eq!(components["BacktestPreparationRevisionInput"]["properties"]["expected_revision"]["type"],"string");
}
#[test]
fn backtest_preparation_dto_roundtrips_the_actual_operation_projection_without_research_aliases() {
    let mut original=fixture();
    for (state,revision,phase) in [(State::Accepted,0,"ACCEPTED"),(State::Ready,9007199254740993,"READY_FOR_HUMAN_CONFIRMATION"),(State::Cancelled,9007199254740994,"CANCELLATION")] {
        original.state=state;original.revision=revision;original.phase=phase.into();
        if state!=State::Accepted {original.outputs=json!({"ready":{"preparation_fingerprint":"2".repeat(64)}});}
        let value=original.view();
        let typed:BacktestPreparationView=serde_json::from_value(value.clone()).unwrap();
        assert_eq!(serde_json::to_value(typed).unwrap(),value);
        assert_eq!(value["backtest_command_id"],FUTURE);
        assert_eq!(value["reserved_run_id"],original.request.reserved_run_id());
        assert_eq!(value["revision"],revision.to_string());
        for key in ["research_run_id","research_command_id","research_outcome","prepared_study_fingerprint","run_permit","runtime_hold","backtest_admission","signals"] {assert!(value.get(key).is_none(),"{key}");}
    }
    let mut value=original.view();value["cleanup"]=json!({"state":"PENDING","work_id":original.request.reserved_run_id()});
    assert_eq!(serde_json::to_value(serde_json::from_value::<BacktestPreparationView>(value.clone()).unwrap()).unwrap(),value);
    for key in ["grant","execution_permit","factor_study","prepared_inputs"] {
        let mut bad=original.view();bad[key]=json!({});assert!(serde_json::from_value::<BacktestPreparationView>(bad).is_err(),"{key}");
    }
}
#[test]
fn backtest_preparation_revision_and_confirmation_use_the_original_command_and_exact_string_counter() {
    let id=CommandId::new(PREPARATION).unwrap();
    let original=json!({"schema_version":1,"preparation_command_id":PREPARATION,"expected_revision":"9007199254740993"});
    let input:BacktestPreparationRevisionInput=serde_json::from_value(original.clone()).unwrap();
    assert_eq!(input.validate(&id).unwrap(),9007199254740993);
    assert_eq!(serde_json::to_value(input).unwrap(),original);
    for value in [json!(9007199254740993_u64),json!("-1"),json!("01"),json!("+1"),json!("1.0"),json!("9223372036854775808")] {
        let mut changed=original.clone();changed["expected_revision"]=value;
        assert!(serde_json::from_value::<BacktestPreparationRevisionInput>(changed).map(|v|v.validate(&id).is_err()).unwrap_or(true));
    }
    let submit=json!({"schema_version":1,"preparation_command_id":PREPARATION,"preparation_fingerprint":"a".repeat(64)});
    serde_json::from_value::<BacktestConfirmationInput>(submit.clone()).unwrap().validate(&id).unwrap();
    for (key,value) in [("schema_version",json!(2)),("preparation_command_id",json!(FUTURE)),("preparation_fingerprint",json!("latest")),("prepared_study_fingerprint",json!("b".repeat(64))),("backtest_command_id",json!(FUTURE)),("run_permit",json!(true))] {
        let mut changed=submit.clone();changed[key]=value;
        assert!(serde_json::from_value::<BacktestConfirmationInput>(changed).map(|v|v.validate(&id).is_err()).unwrap_or(true),"{key}");
    }
}
#[test]
fn backtest_confirmation_unknown_keeps_the_same_future_command_and_never_invents_a_run() {
    let unknown=json!({"schema_version":1,"backtest_command_id":FUTURE,"state":"OUTCOME_UNKNOWN","run_id":null});
    assert_eq!(serde_json::to_value(serde_json::from_value::<BacktestConfirmationOutcome>(unknown.clone()).unwrap()).unwrap(),unknown);
    let mut grant=unknown;grant["backtest_admission"]=json!(true);
    assert!(serde_json::from_value::<BacktestConfirmationOutcome>(grant).is_err());
}

/// Complete cross-language wire fixtures are exported by the actual owning
/// projection, then checked by both serializers. No fixture here grants READY.
fn actual_preparation_wire_cases()->Value {
    use crate::application::backtest_preparation::BacktestOrigin;
    let mut cases=serde_json::Map::new();
    for manual in [false,true] {
        for ready in [false,true] {
            let mut original=fixture();
            let input=match &mut original.request {PreparationRequest::Backtest(input)=>input,_=>unreachable!()};
            if manual {input.origin=BacktestOrigin::ManualStrategy{strategy_id:"private.strategy.btc_momentum".into(),strategy_revision_fingerprint:"9".repeat(64)};}
            original.accepted["input"]=serde_json::to_value(input).unwrap();
            if ready {
                original.state=State::Ready;original.revision=3;original.phase="READY_FOR_HUMAN_CONFIRMATION".into();
                original.outputs=json!({"ready":{"admission":{"strategy_fingerprint":"a".repeat(64),"freeze_relation_fingerprint":"b".repeat(64),"qualification_decision_fingerprint":"c".repeat(64),"promotion_fingerprint":"d".repeat(64)},
                    "preparation_fingerprint":"2".repeat(64),"validation_fingerprint":if manual{json!("8".repeat(64))}else{Value::Null}}});
            }else{original.state=State::Running;original.revision=1;original.phase="VALIDATING".into();}
            let value=original.view();
            let typed:BacktestPreparationView=serde_json::from_value(value.clone()).unwrap();
            assert_eq!(serde_json::to_value(typed).unwrap(),value,"complete DTO must retain every actual projection field");
            assert_eq!(value["validation_fingerprint"],if manual&&ready{json!("8".repeat(64))}else{Value::Null});
            let name=format!("{}_{}",if manual{"manual"}else{"frozen"},if ready{"ready"}else{"progress"});
            cases.insert(name,value);
        }
    }Value::Object(cases)
}
#[test]
fn export_complete_backtest_preparation_wire_v2_from_actual_projection() {
    let value=actual_preparation_wire_cases();
    assert_eq!(value.as_object().unwrap().len(),4);
    println!("BACKTEST_PREPARATION_WIRE_V2_FIXTURE {value}");
    let golden:Value=serde_json::from_str(include_str!("../../../frontend/src/features/backtest/fixtures/preparation-wire-v2.json")).unwrap();
    assert_eq!(value,golden,"the frontend fixture must remain the complete owning Rust projection");
}

#[test]
fn prepare_refusal_echoes_only_the_original_typed_invocation_and_is_not_a_terminal_command() {
    use crate::transport::research_wire::{BacktestPrepareReply,BacktestPrepareRefusal,BacktestPrepareRefusalReason,BacktestPrepareRefusalState};
    let original=fixture();let input=original.request.backtest().unwrap();
    for reason in [BacktestPrepareRefusalReason::ConditionsChanged,BacktestPrepareRefusalReason::SourceUnavailable] {
        let reply=BacktestPrepareReply::NotAccepted(BacktestPrepareRefusal{schema_version:2,state:BacktestPrepareRefusalState::NotAccepted,command_id:original.command.value().into(),input:input.clone(),reason});
        let value=serde_json::to_value(reply).unwrap();
        assert_eq!(value.as_object().unwrap().len(),5);
        assert_eq!(value["command_id"],original.command.value());
        assert_eq!(value["input"],serde_json::to_value(input).unwrap());
        assert_eq!(value["state"],"NOT_ACCEPTED");
        assert_eq!(serde_json::to_value(serde_json::from_value::<BacktestPrepareReply>(value.clone()).unwrap()).unwrap(),value);
        for (key,replacement) in [("state",json!("CANCELLED")),("reason",json!("RESEARCH_PREPARATION_OUTCOME_UNKNOWN")),("permanent_revocation",json!(true)),("receipt",json!({})),("run_id",json!(FUTURE))] {
            let mut invalid=value.clone();invalid[key]=replacement;
            assert!(serde_json::from_value::<BacktestPrepareReply>(invalid).is_err(),"{key}");
        }
    }
    let accepted=original.view();
    assert_eq!(serde_json::to_value(serde_json::from_value::<BacktestPrepareReply>(accepted.clone()).unwrap()).unwrap(),accepted);
}
