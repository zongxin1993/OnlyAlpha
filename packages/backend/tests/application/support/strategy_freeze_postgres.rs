//! Isolated persistence test harness: actual backend owners, cfg(test) seals only.
//! The canonical Python lane provisions the guarded DB; no Shipping acceptance.
#![allow(dead_code)]
#[path = "../../../src/application/mod.rs"]
pub mod application;
#[path = "../../../src/bootstrap/mod.rs"]
pub mod bootstrap;
#[path = "../../../src/persistence/mod.rs"]
pub mod persistence;
#[path = "../../../src/security/mod.rs"]
pub mod security;
#[path = "../../../src/transport/mod.rs"]
pub mod transport;
#[path = "../../../src/workers/mod.rs"]
pub mod workers;
mod backtest_run_lifecycle;
mod runtime_registry_init;
mod strategy_preparation_queue;
mod backtest_preparation_queue;
mod qualification_lifecycle;
mod qualification_product;
mod strategy_evidence_owner;
mod strategy_alias_freeze;
mod manual_freeze_owner;
mod manual_validation_producer;
fn is_sha256_hex(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
use application::{
    command::CommandId,
    frozen_strategy::FrozenStore,
    strategy_projection::{FreezeRequest, Freezes},
};
use persistence::{
    authority_session::AuthoritySession, research_evidence::VerifiedStrategyResearch,
};
use security::{
    human_access::{Access, Admission as HumanAdmission},
    immutable_json::SourceLock,
    protected_files,
};
use serde_json::{Value, json};
use std::{os::fd::AsFd, path::PathBuf, sync::Arc};

#[tokio::test]
async fn actual_command_boundary() {
    let dsn = std::env::var("ONLYALPHA_POSTGRES_DSN").expect("canonical guarded test DB required");
    let root = PathBuf::from(
        std::env::var("ONLYALPHA_FREEZE_TEST_ROOT").expect("isolated use_test root required"),
    );
    let phase = std::env::var("ONLYALPHA_FREEZE_TEST_PHASE").unwrap();
    let (client, connection) = tokio_postgres::connect(&dsn, tokio_postgres::NoTls)
        .await
        .unwrap();
    let driver = tokio::spawn(connection);
    let name: String = client
        .query_one("SELECT pg_catalog.current_database()", &[])
        .await
        .unwrap()
        .get(0);
    assert!(name.ends_with("_test"), "guarded test database required");
    let backend_pid: i32 = client
        .query_one("SELECT pg_catalog.pg_backend_pid()", &[])
        .await
        .unwrap()
        .get(0);
    println!("FREEZE_TEST_BACKEND_PID {backend_pid}");
    std::io::Write::flush(&mut std::io::stdout()).unwrap();
    let mut session = AuthoritySession::acquire(client, driver).await.unwrap();
    if let Some(phase)=phase.strip_prefix("runtime-initialize:") {
        runtime_registry_init::run(&mut session,&root,phase).await;
        return;
    }

    if let Some(phase)=phase.strip_prefix("manual-producer:") {manual_validation_producer::run_phase(&mut session,&root,phase).await.unwrap();return;}
    if let Some(phase)=phase.strip_prefix("manual-freeze:") {manual_freeze_owner::run_phase(&mut session,&root,phase).await;return;}
    if let Some(phase)=phase.strip_prefix("backtest-preparation:") {
        backtest_preparation_queue::run_phase(&mut session,&root,phase).await;
        return;
    }
    if let Some(phase)=phase.strip_prefix("qualification-product:") {
        qualification_product::run_phase(&mut session,&root,phase).await;
        return;
    }
    if let Some(phase)=phase.strip_prefix("strategy-evidence:") {
        strategy_evidence_owner::run_phase(&mut session,&root,phase).await;
        return;
    }
    let fd = protected_files::open_directory(&root).unwrap();
    let store = FrozenStore::open(fd.as_fd()).unwrap();
    let namespace =
        bootstrap::deployment::SemanticStoreId::new("11111111-1111-4111-8111-111111111111")
            .unwrap();
    let token = "a".repeat(64);
    let access = Access::new(&token).unwrap();
    let request = http::Request::builder()
        .uri("/api/v2/integration-types")
        .header("host", "127.0.0.1:5173")
        .header("cookie", format!("onlyalpha_dev_session={token}"))
        .body(())
        .unwrap();
    let HumanAdmission::Owner(human) = access.admit(&request).unwrap() else {
        panic!("human identity");
    };
    if phase == "alias-equivalent-freeze" {
        strategy_alias_freeze::run(&mut session, &namespace, &human, &store, &root).await;
        return;
    }
    if let Some(expected)=phase.strip_prefix("observe-freeze:") {
        let command=CommandId::new("00000000-0000-4000-8000-000000000702").unwrap();
        let client=session.client_mut().await.unwrap();
        let observed=application::strategy_projection::freeze_outcome(client,&namespace,"local-developer",&command).await.unwrap();
        assert_eq!(observed["state"],expected);
        if expected=="NOT_SUBMITTED" {assert!(observed["request"].is_null()&&observed["result"].is_null());}
        else {
            assert_eq!(observed["request"]["research_run_id"],"00000000-0000-4000-8000-000000000701");
            assert_eq!(observed["request"]["comment"],"use_test original Freeze");
            if expected=="COMPLETED" {
                assert_eq!(observed["result"]["command_id"],command.value());
                assert_eq!(observed["result"]["replayed"],true);
            }else {assert!(observed["result"].is_null());}
            assert_eq!(application::strategy_projection::freeze_outcome(client,&namespace,"another-owner",&command).await.unwrap_err(),"STRATEGY_FREEZE_ACCESS_DENIED");
        }
        session.close().await.unwrap();
        return;
    }
    if let Some(phase)=phase.strip_prefix("backtest:") {
        backtest_run_lifecycle::run_phase(&mut session,&namespace,&access,&human,&root,phase).await;
        return;
    }
    if let Some(phase)=phase.strip_prefix("strategy-preparation:") {
        strategy_preparation_queue::run_phase(&mut session,phase).await;
        return;
    }
    if let Some(phase)=phase.strip_prefix("qualification:") {
        qualification_lifecycle::run_phase(&mut session,&namespace,&access,&human,&root,phase).await;
        return;
    }
    let fixture: Value =
        serde_json::from_str(include_str!("../fixtures/frozen_strategy.json")).unwrap();
    let relation = &fixture["relation"];
    let evidence = VerifiedStrategyResearch::for_value_test(
        "00000000-0000-4000-8000-000000000701".into(),
        "7".repeat(64),
        onlyalpha_strategy::SourceRevision::from_json(
            &fixture["source"].to_string(),
            8 * 1024 * 1024,
        )
        .unwrap(),
        relation["candidate_fingerprint"].as_str().unwrap().into(),
        relation["research_result_fingerprint"]
            .as_str()
            .unwrap()
            .into(),
        relation["research_execution_evidence_fingerprints"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().into())
            .collect(),
        relation["admission_evidence_fingerprint"]
            .as_str()
            .unwrap()
            .into(),
        relation["equivalence_evidence_fingerprints"]
            .as_array()
            .unwrap()
            .iter()
            .map(|v| v.as_str().unwrap().into())
            .collect(),
        vec![Arc::new(SourceLock::publication(&root).unwrap())],
    );
    let command = CommandId::new("00000000-0000-4000-8000-000000000702").unwrap();
    let input = FreezeRequest::new(
        command.clone(),
        evidence.run_id(),
        evidence.candidate_fingerprint(),
        Some("use_test original Freeze"),
    )
    .unwrap();
    if matches!(phase.as_str(), "deferred-prepared-guard" | "deferred-final-guard") {
        // The existing cfg(test) scientific seal above is an explicit technical
        // precondition. The fault runs on the original physical writer session;
        // it neither fabricates a mutation guard nor acquires a replacement.
        let event = if phase == "deferred-prepared-guard" {
            "AFTER INSERT"
        } else {
            "AFTER UPDATE"
        };
        let predicate = if phase == "deferred-final-guard" {
            "WHEN (NEW.state='COMPLETED' AND OLD.state IS DISTINCT FROM NEW.state)"
        } else {
            ""
        };
        session.client_mut().await.unwrap().batch_execute(&format!(
            "CREATE FUNCTION use_test_freeze_guard_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER use_test_freeze_guard_fault {event} ON strategy_freeze_command_admission DEFERRABLE INITIALLY DEFERRED FOR EACH ROW {predicate} EXECUTE FUNCTION use_test_freeze_guard_fault()"
        )).await.unwrap();
    }
    let mut commands = Freezes::new(&mut session, &store, &namespace, &human);
    if matches!(phase.as_str(), "deferred-prepared-guard" | "deferred-final-guard") {
        assert!(
            commands.execute(&input, &evidence, "2026-11-01T00:00:01Z", 1000, 64 * 1024 * 1024).await.is_err(),
            "Freeze must reject loss of its original physical authority"
        );
        drop(commands);
        assert!(session.verify().await.is_err(), "guard loss invalidates the original owner");
    } else if phase == "crash" {
        security::immutable_json::crash_publication_at_for_test(
            &std::env::var("ONLYALPHA_FREEZE_TEST_BOUNDARY").unwrap(),
        )
        .unwrap();
        let _ = commands
            .execute(
                &input,
                &evidence,
                "2026-11-01T00:00:01Z",
                1000,
                64 * 1024 * 1024,
            )
            .await;
        panic!("publication crash point was not reached");
    } else if phase == "stop" {
        commands
            .stop_at(&std::env::var("ONLYALPHA_FREEZE_TEST_BOUNDARY").unwrap())
            .unwrap();
        assert_eq!(
            commands
                .execute(
                    &input,
                    &evidence,
                    "2026-11-01T00:00:01Z",
                    1000,
                    64 * 1024 * 1024
                )
                .await
                .unwrap_err(),
            "STRATEGY_FREEZE_COMMAND_UNKNOWN"
        );
        drop(commands);
        assert!(session.verify().await.is_err());
    } else if phase == "resume" || phase == "submit" {
        let original = if phase == "submit" { input.clone() } else { commands.original_request(&command).await.unwrap().unwrap() };
        assert_eq!(original, input);
        let result = commands
            .execute(
                &original,
                &evidence,
                "2026-11-01T00:00:02Z",
                1000,
                64 * 1024 * 1024,
            )
            .await
            .unwrap();
        assert_eq!(
            result["strategy_fingerprint"],
            fixture["source"]["strategy_fingerprint"]
        );
        assert_eq!(
            result["freeze_relation_fingerprint"],
            relation["relation_fingerprint"]
        );
        let replay = commands
            .execute(
                &original,
                &evidence,
                "2030-01-01T00:00:00Z",
                1000,
                64 * 1024 * 1024,
            )
            .await
            .unwrap();
        assert_eq!(replay["accepted_at"], result["accepted_at"]);
        assert_eq!(replay["command_id"], command.value());
        assert_eq!(replay["replayed"], json!(true));
        drop(commands);
        session.close().await.unwrap();
    } else if phase == "corrupt" {
        let error = commands
            .execute(
                &input,
                &evidence,
                "2030-01-01T00:00:00Z",
                1000,
                64 * 1024 * 1024,
            )
            .await
            .unwrap_err();
        assert!(
            matches!(
                error,
                "STRATEGY_CORRUPT"
                    | "STRATEGY_STORE_UNAVAILABLE"
                    | "STRATEGY_FREEZE_ADMISSION_CORRUPT"
                    | "STRATEGY_PROJECTION_CONFLICT"
            ),
            "{error}"
        );
    } else if phase == "trigger" {
        assert_eq!(
            commands
                .execute(
                    &input,
                    &evidence,
                    "2026-11-01T00:00:02Z",
                    1000,
                    64 * 1024 * 1024
                )
                .await
                .unwrap_err(),
            "STRATEGY_PROJECTION_CONFLICT"
        );
    } else if phase == "conflict" {
        let changed = FreezeRequest::new(
            command,
            evidence.run_id(),
            evidence.candidate_fingerprint(),
            Some("changed comment"),
        )
        .unwrap();
        assert_eq!(
            commands
                .execute(
                    &changed,
                    &evidence,
                    "2030-01-01T00:00:00Z",
                    1000,
                    64 * 1024 * 1024
                )
                .await
                .unwrap_err(),
            "PRODUCT_COMMAND_CONFLICT"
        );
    } else {
        panic!("unsupported controlled test phase");
    }
}
