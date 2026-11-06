//! Real Command/PG/immutable Decision lifecycle; cfg(test) scientific inputs only.
//! Artificial counts establish engineering preconditions, never Shipping qualification.
use crate::{
    application::{
        command::{CommandId, OutcomeKind},
        factor_content::hash,
        frozen_strategy::FrozenStore,
        qualification::Request as QualificationRequest,
        qualification_policy::{Policy, Store as Policies},
        strategy_projection::{FreezeRequest, Freezes},
        strategy_promotion::PromotionRecord,
    },
    bootstrap::deployment::SemanticStoreId,
    persistence::{
        authority_session::AuthoritySession,
        postgres::Commands,
        qualification_commands::Qualifications,
        qualification_decision::{Store as Decisions, VerifiedDecision},
        research_evidence::{VerifiedResearchCounts, VerifiedStrategyResearch},
        strategy_promotion::{self, Promotions, Request as PromotionRequest},
    },
    security::{
        human_access::{Access, Session},
        immutable_json::SourceLock,
        protected_files,
    },
};
use serde_json::{Value, json};
use std::{
    os::{fd::AsFd, unix::fs::PermissionsExt},
    path::Path,
    sync::Arc,
};
const WORK: usize = 64 * 1024 * 1024;
fn command(n: u16) -> CommandId {
    CommandId::new(&format!("00000000-0000-4000-8000-{n:012}")).unwrap()
}
fn at(second: u8) -> onlyalpha_domain::time::OnlyUtcDateTime {
    format!("2026-11-02T00:00:{second:02}.123456Z")
        .parse()
        .unwrap()
}
async fn setup(
    session: &mut AuthoritySession,
    namespace: &SemanticStoreId,
    human: &Session,
    root: &Path,
) -> (
    Arc<FrozenStore>,
    Arc<Policies>,
    Arc<Decisions>,
    Arc<VerifiedResearchCounts>,
    String,
) {
    let fd = protected_files::open_directory(root).unwrap();
    let frozen = Arc::new(FrozenStore::open(fd.as_fd()).unwrap());
    let fixture: Value =
        serde_json::from_str(include_str!("../fixtures/frozen_strategy.json")).unwrap();
    let relation = &fixture["relation"];
    let evidence = VerifiedStrategyResearch::for_value_test(
        "00000000-0000-4000-8000-000000000701".into(),
        "7".repeat(64),
        onlyalpha_strategy::SourceRevision::from_json(&fixture["source"].to_string(), WORK)
            .unwrap(),
        relation["candidate_fingerprint"].as_str().unwrap().into(),
        relation["research_result_fingerprint"]
            .as_str()
            .unwrap()
            .into(),
        serde_json::from_value(relation["research_execution_evidence_fingerprints"].clone())
            .unwrap(),
        relation["admission_evidence_fingerprint"]
            .as_str()
            .unwrap()
            .into(),
        serde_json::from_value(relation["equivalence_evidence_fingerprints"].clone()).unwrap(),
        vec![Arc::new(SourceLock::publication(root).unwrap())],
    );
    let freeze = FreezeRequest::new(
        CommandId::new("00000000-0000-4000-8000-000000000702").unwrap(),
        evidence.run_id(),
        evidence.candidate_fingerprint(),
        Some("Controlled immutable preconditions"),
    )
    .unwrap();
    let output = Freezes::new(session, &frozen, namespace, human)
        .execute(&freeze, &evidence, "2026-11-01T00:00:00Z", 100, WORK)
        .await
        .unwrap();
    let subject = output["strategy_fingerprint"].as_str().unwrap().to_owned();
    let relation = output["freeze_relation_fingerprint"]
        .as_str()
        .unwrap()
        .to_owned();
    let mut value = json!({"schema_version":1,"policy_id":"experimental-backtest","policy_version":"1","gate":"RESEARCH_TO_BACKTEST","missing_evidence_behavior":"FAIL","aggregation":"ALL","criteria":[
        {"criterion_id":"calculation-count","evidence_kind":"RESEARCH_RESULT","metric":"research.calculation_result_count","comparison":"GE","threshold":"1"},
        {"criterion_id":"statistics-count","evidence_kind":"RESEARCH_RESULT","metric":"research.statistics_result_count","comparison":"GE","threshold":"2"}]});
    let mut body = value.clone();
    body["domain"] = json!("onlyalpha.strategy.qualification-policy");
    value["policy_fingerprint"] = json!(hash(&body).unwrap());
    let policy = Policy::from_json(&value.to_string(), WORK).unwrap();
    let policy_fp = value["policy_fingerprint"].as_str().unwrap().into();
    let policies = Arc::new(Policies::open(fd.as_fd()).unwrap());
    policies
        .admit(session, namespace, &[policy], WORK)
        .await
        .unwrap();
    let path = root.join("strategy/qualification-decisions");
    std::fs::create_dir_all(path.join("sha256")).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
    if !path.join(".source-cut.lock").exists() {
        std::fs::write(path.join(".source-cut.lock"), b"").unwrap();
        std::fs::set_permissions(
            path.join(".source-cut.lock"),
            std::fs::Permissions::from_mode(0o600),
        )
        .unwrap();
    }
    let decisions = Arc::new(Decisions::open(root).unwrap());
    let counts = Arc::new(VerifiedResearchCounts::for_persistence_test(
        subject,
        evidence.research_result_fingerprint().into(),
        "e".repeat(64),
        relation,
        2,
        2,
        Arc::new(SourceLock::publication(root).unwrap()),
    ));
    (frozen, policies, decisions, counts, policy_fp)
}
fn qualification(counts: &VerifiedResearchCounts) -> QualificationRequest {
    QualificationRequest::new(command(7101),counts.subject_strategy_fingerprint(),"experimental-backtest","1",&json!([{"kind":"RESEARCH_RESULT","evidence_fingerprint":counts.research_result_fingerprint(),"locator_fingerprint":counts.research_result_plan_fingerprint(),"subject_binding_fingerprint":counts.freeze_relation_fingerprint()}])).unwrap()
}
struct QualificationAssets {
    frozen: Arc<FrozenStore>,
    policies: Arc<Policies>,
    decisions: Arc<Decisions>,
    counts: Arc<VerifiedResearchCounts>,
}
async fn qualify(
    session: &mut AuthoritySession,
    namespace: &SemanticStoreId,
    access: &Access,
    human: &Session,
    assets: QualificationAssets,
    second: u8,
) -> Arc<VerifiedDecision> {
    let QualificationAssets {
        frozen,
        policies,
        decisions,
        counts,
    } = assets;
    let request = qualification(&counts);
    Qualifications::new(
        session, namespace, policies, decisions, frozen, access, human,
    )
    .execute(&request, counts, at(second))
    .await
    .unwrap()
}
pub(super) async fn run_phase(
    session: &mut AuthoritySession,
    namespace: &SemanticStoreId,
    access: &Access,
    human: &Session,
    root: &Path,
    phase: &str,
) {
    let (frozen, policies, decisions, counts, policy) =
        setup(session, namespace, human, root).await;
    let request = qualification(&counts);
    if let Some(boundary) = phase.strip_prefix("qualification-stop:") {
        let mut owner = Qualifications::new(
            session, namespace, policies, decisions, frozen, access, human,
        );
        owner.stop_at(boundary).unwrap();
        assert_eq!(
            owner.execute(&request, counts, at(0)).await.err(),
            Some("QUALIFICATION_COMMAND_OUTCOME_UNKNOWN")
        );
        std::process::exit(86);
    }
    if matches!(
        phase,
        "deferred-prepared-guard" | "deferred-final-guard" | "deferred-final-receipt"
    ) {
        let sql = match phase {
            "deferred-prepared-guard" => {
                "CREATE FUNCTION use_test_qualification_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER use_test_qualification_fault AFTER INSERT ON qualification_command_admission DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION use_test_qualification_fault()"
            }
            "deferred-final-guard" => {
                "CREATE FUNCTION use_test_qualification_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_advisory_unlock(1329199301,5); RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER use_test_qualification_fault AFTER UPDATE ON qualification_command_admission DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.state='COMPLETED') EXECUTE FUNCTION use_test_qualification_fault()"
            }
            _ => {
                "CREATE FUNCTION use_test_qualification_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN UPDATE product_command_receipt SET outcome_id=repeat('f',64) WHERE command_id=NEW.command_id; RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER use_test_qualification_fault AFTER INSERT ON product_command_receipt DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.command_kind='EVALUATE_QUALIFICATION') EXECUTE FUNCTION use_test_qualification_fault()"
            }
        };
        session
            .client_mut()
            .await
            .unwrap()
            .batch_execute(sql)
            .await
            .unwrap();
        assert!(
            Qualifications::new(
                session, namespace, policies, decisions, frozen, access, human
            )
            .execute(&request, counts, at(0))
            .await
            .is_err()
        );
        assert!(
            session.verify().await.is_err(),
            "unexpected mutation or guard loss invalidates the original physical owner"
        );
        return;
    }
    let weak = Arc::downgrade(&counts);
    let decision = qualify(
        session,
        namespace,
        access,
        human,
        QualificationAssets {
            frozen: frozen.clone(),
            policies: policies.clone(),
            decisions: decisions.clone(),
            counts: counts.clone(),
        },
        30,
    )
    .await;
    assert_eq!(decision.record()["outcome"], "APPROVED");
    let before = Commands::new(session.client_mut().await.unwrap())
        .load_verified_receipt(request.command_id())
        .await
        .unwrap()
        .unwrap();
    assert_eq!(before.outcome().kind(), OutcomeKind::QualificationDecision);
    assert_eq!(before.outcome().id(), decision.fingerprint());
    assert_eq!(
        qualify(
            session,
            namespace,
            access,
            human,
            QualificationAssets {
                frozen: frozen.clone(),
                policies: policies.clone(),
                decisions: decisions.clone(),
                counts: counts.clone()
            },
            50
        )
        .await
        .record(),
        decision.record()
    );
    assert_eq!(
        Commands::new(session.client_mut().await.unwrap())
            .load_verified_receipt(request.command_id())
            .await
            .unwrap()
            .unwrap(),
        before
    );
    if phase == "qualification-recover" {
        return;
    }
    if phase == "completed-missing-decision" {
        let fp = decision.fingerprint();
        let path = root
            .join("strategy/qualification-decisions/sha256")
            .join(&fp[..2])
            .join(fp)
            .join("manifest.json");
        std::fs::remove_file(&path).unwrap();
        assert!(
            Qualifications::new(
                session, namespace, policies, decisions, frozen, access, human
            )
            .execute(&request, counts, at(50))
            .await
            .is_err()
        );
        assert!(
            !path.exists(),
            "a completed replay must refuse repair, never republish the lost Decision"
        );
        return;
    }
    let promotion = PromotionRequest::new(
        command(7102),
        counts.subject_strategy_fingerprint(),
        decision.fingerprint(),
        &policy,
        "实验性回测；仅检查证据完整性",
    )
    .unwrap();
    if phase == "policy-mismatch" {
        let wrong = PromotionRequest::new(
            command(7102),
            counts.subject_strategy_fingerprint(),
            decision.fingerprint(),
            &"f".repeat(64),
            "must not become a grant",
        )
        .unwrap();
        assert_eq!(
            Promotions::new(session, namespace, frozen, access, human)
                .promote(&wrong, decision, at(0))
                .await
                .err(),
            Some("QUALIFICATION_DECISION_POLICY_MISMATCH")
        );
        return;
    }
    if phase == "historical-promotion" {
        let mut legacy = json!({"schema_version":1,"strategy_fingerprint":counts.subject_strategy_fingerprint(),"from_stage":"RESEARCH","to_stage":"BACKTEST","evidence_fingerprints":[counts.freeze_relation_fingerprint()],"decision":"APPROVED","reason":"Historical pre-qualification record","actor":"legacy-human","recorded_at":"2026-11-01T00:00:00+00:00","previous_record_fingerprint":null});
        legacy["record_fingerprint"] = json!(hash(&legacy).unwrap());
        PromotionRecord::from_record(&legacy).unwrap();
        session.client_mut().await.unwrap().execute("INSERT INTO strategy_promotion_record(promotion_record_fingerprint,strategy_fingerprint,from_stage,to_stage,evidence_fingerprints,previous_record_fingerprint,decision,reason,actor,recorded_at,schema_version) VALUES($1,$2,'RESEARCH','BACKTEST',$3,NULL,'APPROVED','Historical pre-qualification record','legacy-human','2026-11-01T00:00:00Z',1)",&[&legacy["record_fingerprint"].as_str().unwrap(),&counts.subject_strategy_fingerprint(),&vec![counts.freeze_relation_fingerprint().to_owned()]]).await.unwrap();
        assert!(
            strategy_promotion::read_verified_admission(
                session.client_mut().await.unwrap(),
                namespace,
                frozen,
                decision,
                strategy_promotion::BacktestAdmissionSelection {
                    strategy: counts.subject_strategy_fingerprint(),
                    relation: counts.freeze_relation_fingerprint(),
                    promotion: legacy["record_fingerprint"].as_str().unwrap(),
                    max_work: WORK,
                },
            )
            .await
            .is_err(),
            "a readable historical stage is not a new qualified admission"
        );
        return;
    }
    if let Some(boundary) = phase.strip_prefix("promotion-stop:") {
        let mut owner = Promotions::new(session, namespace, frozen, access, human);
        owner.stop_at(boundary).unwrap();
        assert_eq!(
            owner.promote(&promotion, decision, at(0)).await.err(),
            Some("PROMOTION_COMMAND_OUTCOME_UNKNOWN")
        );
        std::process::exit(86);
    }
    if matches!(
        phase,
        "deferred-promotion-guard" | "deferred-promotion-audit" | "deferred-promotion-freeze"
    ) {
        let statement = match phase {
            "deferred-promotion-guard" => "PERFORM pg_advisory_unlock(1329199301,5);",
            "deferred-promotion-audit" => {
                "UPDATE strategy_promotion_record SET reason='mutated after insert' WHERE promotion_record_fingerprint=NEW.promotion_record_fingerprint;"
            }
            _ => {
                "UPDATE strategy_freeze_record SET actor='mutated freeze audit' WHERE strategy_fingerprint=NEW.strategy_fingerprint;"
            }
        };
        session.client_mut().await.unwrap().batch_execute(&format!("CREATE FUNCTION use_test_promotion_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN {statement} RETURN NEW; END $$; CREATE CONSTRAINT TRIGGER use_test_promotion_fault AFTER INSERT ON strategy_promotion_record DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION use_test_promotion_fault()")).await.unwrap();
        assert!(
            Promotions::new(session, namespace, frozen, access, human)
                .promote(&promotion, decision, at(0))
                .await
                .is_err()
        );
        assert!(session.verify().await.is_err());
        return;
    }
    let record = Promotions::new(session, namespace, frozen.clone(), access, human)
        .promote(&promotion, decision.clone(), at(0))
        .await
        .unwrap();
    assert_eq!(record.record()["schema_version"], 2);
    assert_eq!(record.record()["to_stage"], "BACKTEST");
    assert_eq!(
        record.record()["recorded_at"],
        "2026-11-02T00:00:00.123456+00:00"
    );
    let mut identity = record.record().clone();
    identity
        .as_object_mut()
        .unwrap()
        .remove("record_fingerprint");
    assert_eq!(record.fingerprint(), hash(&identity).unwrap());
    assert_eq!(
        Promotions::new(session, namespace, frozen.clone(), access, human)
            .promote(&promotion, decision.clone(), at(50))
            .await
            .unwrap()
            .record(),
        record.record()
    );
    let pin = record.fingerprint().to_owned();
    let admission = strategy_promotion::read_verified_admission(
        session.client_mut().await.unwrap(),
        namespace,
        frozen,
        decision.clone(),
        strategy_promotion::BacktestAdmissionSelection {
            strategy: counts.subject_strategy_fingerprint(),
            relation: counts.freeze_relation_fingerprint(),
            promotion: &pin,
            max_work: WORK,
        },
    )
    .await
    .unwrap();
    assert_eq!(admission.promotion_fingerprint(), pin);
    admission.verify_cut().unwrap();
    drop(counts);
    assert!(
        weak.upgrade().is_some(),
        "the opaque Decision/Admission must retain actual count-byte proof ownership"
    );
    let tx = session
        .client_mut()
        .await
        .unwrap()
        .build_transaction()
        .read_only(true)
        .start()
        .await
        .unwrap();
    admission
        .verify_in_transaction(&tx, namespace)
        .await
        .unwrap();
    tx.rollback().await.unwrap();
    if phase == "admission-source-cut" {
        let lock = root.join(".source-cut.lock");
        std::fs::rename(&lock, root.join("retained-old-source-lock")).unwrap();
        std::fs::write(&lock, b"").unwrap();
        std::fs::set_permissions(lock, std::fs::Permissions::from_mode(0o600)).unwrap();
        assert!(admission.verify_cut().is_err());
        return;
    }
    if phase == "admission-decision-bytes" {
        let fp = decision.fingerprint();
        let file = root
            .join("strategy/qualification-decisions/sha256")
            .join(&fp[..2])
            .join(fp)
            .join("manifest.json");
        std::fs::write(file, b"corrupt exact Decision").unwrap();
        assert!(admission.verify_cut().is_err());
        return;
    }
    if phase == "admission-frozen-bytes" {
        let fp = admission.strategy_fingerprint();
        let file = root
            .join("strategy/frozen-revisions/sha256")
            .join(&fp[..2])
            .join(fp)
            .join("manifest.json");
        std::fs::write(file, b"corrupt exact frozen source").unwrap();
        assert!(admission.verify_cut().is_err());
        return;
    }
    if let Some(mutation) = phase.strip_prefix("admission-pg:") {
        let client = session.client_mut().await.unwrap();
        match mutation {
            "rehash" => {
                let mut changed = record.record().clone();
                changed
                    .as_object_mut()
                    .unwrap()
                    .remove("record_fingerprint");
                changed["reason"] = json!("Different self-consistent audit");
                let new = hash(&changed).unwrap();
                client.execute("UPDATE strategy_promotion_record SET reason='Different self-consistent audit',promotion_record_fingerprint=$2 WHERE promotion_record_fingerprint=$1",&[&pin,&new]).await.unwrap();
            }
            "namespace" => {
                client.batch_execute("ALTER TABLE strategy_catalog DROP CONSTRAINT strategy_catalog_semantic_namespace_id_fkey").await.unwrap();
                client.execute("UPDATE strategy_catalog SET semantic_namespace_id='22222222-2222-4222-8222-222222222222' WHERE strategy_fingerprint=$1",&[&admission.strategy_fingerprint()]).await.unwrap();
            }
            "chain" | "chain-orphan" => {
                let mut child = json!({"schema_version":1,"strategy_fingerprint":admission.strategy_fingerprint(),"from_stage":if mutation=="chain"{"BACKTEST"}else{"RESEARCH"},"to_stage":if mutation=="chain"{"SIM"}else{"BACKTEST"},"evidence_fingerprints":[admission.freeze_relation_fingerprint()],"decision":"REJECTED","reason":"Historical rejected continuation","actor":"legacy-human","recorded_at":"2026-11-01T00:00:00+00:00","previous_record_fingerprint":pin});
                child["record_fingerprint"] = json!(hash(&child).unwrap());
                PromotionRecord::from_record(&child).unwrap();
                client.execute("INSERT INTO strategy_promotion_record(promotion_record_fingerprint,strategy_fingerprint,from_stage,to_stage,evidence_fingerprints,previous_record_fingerprint,decision,reason,actor,recorded_at,schema_version) VALUES($1,$2,$3,$4,$5,$6,'REJECTED','Historical rejected continuation','legacy-human','2026-11-01T00:00:00Z',1)",&[&child["record_fingerprint"].as_str().unwrap(),&admission.strategy_fingerprint(),&child["from_stage"].as_str().unwrap(),&child["to_stage"].as_str().unwrap(),&vec![admission.freeze_relation_fingerprint().to_owned()],&pin]).await.unwrap();
            }
            "receipt" => {
                client.execute("UPDATE product_command_receipt SET outcome_id=repeat('f',64) WHERE command_id=$1::text::uuid",&[&command(7102).value()]).await.unwrap();
            }
            "freeze" => {
                client.execute("UPDATE strategy_freeze_record SET actor='changed retained audit' WHERE freeze_record_fingerprint=$1",&[&admission.freeze_relation_fingerprint()]).await.unwrap();
            }
            _ => panic!("unknown mutation"),
        }
        admission.verify_cut().unwrap();
        let tx = client
            .build_transaction()
            .read_only(true)
            .start()
            .await
            .unwrap();
        assert!(
            admission
                .verify_in_transaction(&tx, namespace)
                .await
                .is_err(),
            "retained FS locks cannot certify a changed PG ledger closure"
        );
        tx.rollback().await.unwrap();
        return;
    }
    assert_eq!(phase, "promotion-recover");
}
