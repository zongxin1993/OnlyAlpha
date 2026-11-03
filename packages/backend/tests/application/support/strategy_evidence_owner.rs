//! Actual owning readers + original Human Freeze, using the existing DB harness.
//! This module never calls a cfg(test) value/seal factory.
use crate::{
    application::{command::CommandId,frozen_strategy::{FrozenPlan,FrozenStore},strategy_projection::{FreezeRequest,Freezes}},
    bootstrap::deployment,
    persistence::{authority_session::AuthoritySession,research_evidence::Store,research_submission},
    security::{human_access::{Access,Admission},protected_files},
};
use serde_json::{Value,json};
use std::{os::fd::AsFd,path::Path};
pub async fn run_phase(session:&mut AuthoritySession,root:&Path,phase:&str){
    let request:Value=serde_json::from_slice(&std::fs::read(std::env::var("ONLYALPHA_STRATEGY_EVIDENCE_REQUEST").unwrap()).unwrap()).unwrap();
    let run=research_submission::load(session.client_mut().await.unwrap(),request["run_id"].as_str().unwrap(),Some("local-developer")).await.unwrap();
    if phase=="runtime-work-inventory" {
        use crate::persistence::research_runtime::{Registry,RuntimeEvidenceHold};
        use std::os::unix::fs::MetadataExt;
        let runtime=Path::new(request["runtime_root"].as_str().unwrap());
        let journal=runtime.join("generation-events.jsonl");
        let before=(std::fs::metadata(&journal).unwrap().ino(),std::fs::read(&journal).unwrap());
        // This is the actual archived, shared-lock reader even after release.
        // The new inventory must also be read-only, never take an EX lock.
        let held=RuntimeEvidenceHold::open(runtime,run.run_id(),"research",run.runtime_generation_fingerprint().unwrap()).unwrap();
        let bindings=Registry::unreleased_work_bindings(runtime).unwrap();
        let unique=bindings.iter().map(|(work,_,_)|work).collect::<std::collections::BTreeSet<_>>();
        assert_eq!(unique.len(),bindings.len());
        held.verify().unwrap();
        assert_eq!((std::fs::metadata(&journal).unwrap().ino(),std::fs::read(&journal).unwrap()),before,"read-only recovery inventory cannot append, replace or regrant work");
        println!("STRATEGY_EVIDENCE_VALUE {}",json!({"bindings":bindings,"read_only":true}));
        return;
    }
    let evidence=Store::open(root).unwrap().with_runtime_root(Path::new(request["runtime_root"].as_str().unwrap())).unwrap();
    let seal=evidence.read_verified_strategy(&run).unwrap();
    seal.verify_cut().unwrap();
    assert_eq!(seal.run_id(),run.run_id());
    assert_eq!(seal.specification_fingerprint(),run.specification_fingerprint());
    assert_eq!(seal.candidate_fingerprint(),run.strategy_specification().unwrap().candidate_fingerprint().unwrap());
    let descriptor=protected_files::open_directory(root).unwrap();
    let frozen=FrozenStore::open(descriptor.as_fd()).unwrap();
    let namespace=deployment::load_semantic_store_id_at(&descriptor).unwrap();
    let access=Access::new(&"a".repeat(64)).unwrap();
    let message=http::Request::builder().uri("/api/v2/integration-types").header("host","127.0.0.1:5173")
        .header("cookie",format!("onlyalpha_dev_session={}","a".repeat(64))).body(()).unwrap();
    let Admission::Owner(human)=access.admit(&message).unwrap() else{panic!("actual Human identity")};
    let command=CommandId::new(request["freeze_command"].as_str().unwrap()).unwrap();
    if phase=="freeze" {
        let input=FreezeRequest::new(command,run.run_id(),seal.candidate_fingerprint(),Some("actual complete Strategy evidence")).unwrap();
        let result=Freezes::new(session,&frozen,&namespace,&human).execute(&input,&seal,request["at"].as_str().unwrap(),4096,8*1024*1024).await.unwrap();
        let plan=FrozenPlan::from_verified(&seal).unwrap();
        assert_eq!(result["strategy_fingerprint"],plan.revision().fingerprint());
        let relation=result["freeze_relation_fingerprint"].as_str().unwrap();
        let counts=evidence.read_verified_counts(&run,&frozen,relation).unwrap();
        counts.verify_cut().unwrap();
        assert_eq!(counts.subject_strategy_fingerprint(),plan.revision().fingerprint());
        assert_eq!(counts.research_result_fingerprint(),seal.research_result_fingerprint());
        assert_eq!(counts.freeze_relation_fingerprint(),relation);
        assert_eq!(counts.statistics_result_count(),2);
        assert_eq!(counts.calculation_result_count(),2);
        assert!(evidence.read_verified_counts(&run,&frozen,&"f".repeat(64)).is_err());
        println!("STRATEGY_EVIDENCE_VALUE {}",json!({"freeze":result,"source_revision":seal.source_revision().to_record(),
            "candidate":seal.candidate_fingerprint(),"result":seal.research_result_fingerprint(),
            "equivalence":seal.equivalence_evidence_fingerprints(),"producer":seal.research_execution_evidence_fingerprints(),
            "admission":seal.admission_evidence_fingerprint(),"counts":[counts.statistics_result_count(),counts.calculation_result_count()]}));
        return;
    }
    if phase=="qualification-source-history" {
        drop(seal);
        qualification_history(session,root,&request,&run,&frozen,&namespace).await;
        return;
    }
    assert_eq!(phase,"stale-seal");
    let counts=evidence.read_verified_counts(&run,&frozen,request["freeze_relation"].as_str().unwrap()).unwrap();
    use std::os::unix::fs::PermissionsExt;
    let path=Path::new(request["tamper_path"].as_str().unwrap());
    let original=std::fs::read(path).unwrap();let permissions=std::fs::metadata(path).unwrap().permissions();
    let mut changed=original.clone();let index=changed.len()-1;changed[index]^=1;
    std::fs::set_permissions(path,std::fs::Permissions::from_mode(permissions.mode()|0o200)).unwrap();
    std::fs::write(path,&changed).unwrap();
    let seal_rejected=seal.verify_cut().is_err();
    let counts_rejected=counts.verify_cut().is_err();
    let plan_rejected=FrozenPlan::from_verified(&seal).is_err();
    let input=FreezeRequest::new(command.clone(),run.run_id(),seal.candidate_fingerprint(),None).unwrap();
    let command_rejected=Freezes::new(session,&frozen,&namespace,&human).execute(&input,&seal,request["at"].as_str().unwrap(),4096,8*1024*1024).await.is_err();
    std::fs::write(path,&original).unwrap();std::fs::set_permissions(path,permissions).unwrap();
    assert!(seal_rejected&&counts_rejected&&plan_rejected&&command_rejected,"retained byte witnesses must invalidate existing seals before any semantic publication");
    let count:i64=session.client_mut().await.unwrap().query_one("SELECT count(*) FROM product_command_admission WHERE command_id=$1::text::uuid",&[&command.value()]).await.unwrap().get(0);
    assert_eq!(count,0);
    seal.verify_cut().unwrap();counts.verify_cut().unwrap();
    println!("STRATEGY_EVIDENCE_VALUE {}",json!({"stale_seal_refused":true,"run_id":run.run_id()}));
}

async fn qualification_history(
    session:&mut AuthoritySession,root:&Path,request:&Value,run:&crate::application::research_run::VerifiedRun,
    frozen:&FrozenStore,namespace:&deployment::SemanticStoreId,
){
    use crate::{application::{factor_content::hash,qualification_policy::{Policy,Store as Policies},research_novelty::Subject},
        persistence::{qualification_decision::Store as Decisions,research_novelty::Authority},security::immutable_json::{Directory,put}};
    use std::{collections::BTreeMap,sync::Arc};
    let semantic=Path::new(request["semantic_root"].as_str().unwrap());
    let roots:BTreeMap<String,std::path::PathBuf>=serde_json::from_value(request["source_roots"].clone()).unwrap();
    assert_eq!(roots["QUALIFICATION_DECISION"],root.join("strategy/qualification-decisions"));
    let base_profile=root.join(".onlyalpha-factor-research-owner-profile.json");
    let base_bytes=std::fs::read(&base_profile).unwrap();
    let base:Value=serde_json::from_slice(&base_bytes).unwrap();
    assert_eq!(base["profile_fingerprint"],"e65c1f68866533f9779f85f6f254ce1b43115ea22b6a33bb4cd7af31ba8fc01b");
    let extension_path=root.join(".onlyalpha-strategy-research-owner-extension-v1.json");
    let extension_bytes=std::fs::read(&extension_path).unwrap();
    let extension:Value=serde_json::from_slice(&extension_bytes).unwrap();
    assert_eq!(extension["base_profile_fingerprint"],base["profile_fingerprint"]);
    assert_eq!(extension["semantic_store_id"],namespace.value());
    let mut extension_identity=extension.clone();
    extension_identity.as_object_mut().unwrap().remove("extension_fingerprint");
    assert_eq!(extension["extension_fingerprint"],hash(&extension_identity).unwrap());
    assert_eq!(extension["file_source_extensions"],json!([{"family":"QUALIFICATION_DECISION","owner":"strategy/qualification-decisions","source_schema_version":1,"enumeration_contract_version":2}]));
    let authority=Authority::new(semantic,&root.join("experiment-memory"),roots).unwrap()
        .with_runtime_root(Path::new(request["runtime_root"].as_str().unwrap())).unwrap();
    let first=authority.refresh_projection(session.client_mut().await.unwrap()).await.unwrap();
    let current_path=root.join("experiment-memory/revisions/sha256").join(&first[..2]).join(&first).join("projection.json");
    let current:Value=serde_json::from_slice(&std::fs::read(&current_path).unwrap()).unwrap();
    let current_reference=current["source_manifest"]["cuts"].as_array().unwrap().iter().find(|r|r["source_family"]=="QUALIFICATION_DECISION").unwrap();
    assert_eq!(current_reference["enumeration_contract_version"],2);
    for reference in current["source_manifest"]["cuts"].as_array().unwrap() {
        if reference["source_family"]!="QUALIFICATION_DECISION" {
            assert_eq!(reference["enumeration_contract_version"],1,"the extension changes Q enumeration only");
        }
    }
    // Retained historical reference vector: original enum1 captured the empty
    // legacy top owner. These exact bytes/projection are test preconditions,
    // not a current producer allowed to mint old-cut ActionProofs.
    let mut legacy_cut=json!({"schema_version":1,"source_family":"QUALIFICATION_DECISION","source_schema_version":1,
        "enumeration_contract_version":1,"cut_boundary":"FILE_PUBLICATION_BARRIER_V1",
        "completeness_proof":"SOURCE_OWNED_EXCLUSIVE_INVENTORY_V1","entries":[]});
    legacy_cut["cut_fingerprint"]=json!(hash(&legacy_cut).unwrap());
    let legacy_id=legacy_cut["cut_fingerprint"].as_str().unwrap();
    let legacy_owner=Directory::open(&root.join("qualification-decisions")).unwrap();
    put(&legacy_owner,&["closed-cuts","sha256",&legacy_id[..2],legacy_id],"manifest.json",&legacy_cut).unwrap();
    let mut legacy=current.clone();
    let reference=legacy["source_manifest"]["cuts"].as_array_mut().unwrap().iter_mut().find(|r|r["source_family"]=="QUALIFICATION_DECISION").unwrap();
    for key in ["source_family","source_schema_version","enumeration_contract_version","cut_fingerprint","cut_boundary","completeness_proof"] {reference[key]=legacy_cut[key].clone();}
    let mut manifest=legacy["source_manifest"].clone();manifest.as_object_mut().unwrap().remove("manifest_fingerprint");
    legacy["source_manifest"]["manifest_fingerprint"]=json!(hash(&manifest).unwrap());
    let identity=hash(&json!({"source_cut_manifest_fingerprint":legacy["source_manifest"]["manifest_fingerprint"],
        "projection_schema_version":7,"projector_algorithm_version":7,"logical_digest":legacy["logical_digest"]})).unwrap();
    legacy["revision_fingerprint"]=json!(identity);
    let projection=Directory::open(&root.join("experiment-memory")).unwrap();
    put(&projection,&["revisions","sha256",&identity[..2],&identity],"projection.json",&legacy).unwrap();
    let legacy_file=root.join("qualification-decisions/closed-cuts/sha256").join(&legacy_id[..2]).join(legacy_id).join("manifest.json");
    let legacy_bytes=std::fs::read(&legacy_file).unwrap();
    let original_projection_bytes=std::fs::read(root.join("experiment-memory/revisions/sha256").join(&identity[..2]).join(&identity).join("projection.json")).unwrap();
    let mut query=run.strategy_specification().unwrap().subject().unwrap().to_record();
    query["candidate_fingerprint"]=json!("f".repeat(64));query["specification_fingerprint"]=json!("e".repeat(64));
    let subject=Subject::new(query).unwrap();
    let command=CommandId::new(request["qualification_history_command"].as_str().unwrap()).unwrap();
    let group=authority.seal(session.client_mut().await.unwrap(),&command,std::slice::from_ref(&subject),"onlyalpha.factor-research","1",&identity).await.unwrap();
    assert_eq!(group["disposition"],"ACTIONABLE");
    assert_eq!(authority.authorize_action(session.client_mut().await.unwrap(),&command,std::slice::from_ref(&subject),&identity).await.err(),Some("NOVELTY_DECISION_STALE"));
    let evidence=Store::open(root).unwrap().with_runtime_root(Path::new(request["runtime_root"].as_str().unwrap())).unwrap();
    let counts=Arc::new(evidence.read_verified_counts(run,frozen,request["freeze_relation"].as_str().unwrap()).unwrap());
    let mut value=json!({"schema_version":1,"policy_id":"experimental-backtest","policy_version":"1","gate":"RESEARCH_TO_BACKTEST",
        "missing_evidence_behavior":"FAIL","aggregation":"ALL","criteria":[
        {"criterion_id":"calculation-count","evidence_kind":"RESEARCH_RESULT","metric":"research.calculation_result_count","comparison":"GE","threshold":"1"},
        {"criterion_id":"statistics-count","evidence_kind":"RESEARCH_RESULT","metric":"research.statistics_result_count","comparison":"GE","threshold":"2"}]});
    let mut policy_identity=value.clone();policy_identity["domain"]=json!("onlyalpha.strategy.qualification-policy");
    value["policy_fingerprint"]=json!(hash(&policy_identity).unwrap());
    let policy=Policy::from_json(&value.to_string(),64*1024*1024).unwrap();
    let descriptor=protected_files::open_directory(root).unwrap();
    let policies=Arc::new(Policies::open(descriptor.as_fd()).unwrap());
    policies.admit(session,namespace,&[policy],64*1024*1024).await.unwrap();
    let decisions=Arc::new(Decisions::open(root).unwrap());
    let decision=decisions.publish_evidence(policies,"experimental-backtest","1",crate::persistence::qualification_decision::Evidence::Research(counts.clone())).unwrap();
    let decision_id=decision.fingerprint().to_owned();
    assert_eq!(decision.record()["outcome"],"APPROVED");
    drop(decision);drop(counts);
    // The existing snapshot already owns canonical SourceLock::acquire. This
    // healthy read must reuse it, not deadlock by acquiring publication again.
    let fresh=authority.refresh_projection(session.client_mut().await.unwrap()).await.unwrap();
    let fresh_projection:Value=serde_json::from_slice(&std::fs::read(root.join("experiment-memory/revisions/sha256").join(&fresh[..2]).join(&fresh).join("projection.json")).unwrap()).unwrap();
    let qualified=fresh_projection["source_manifest"]["cuts"].as_array().unwrap().iter().find(|r|r["source_family"]=="QUALIFICATION_DECISION").unwrap();
    assert_eq!(qualified["enumeration_contract_version"],2);
    let qualified_id=qualified["cut_fingerprint"].as_str().unwrap();
    let cut:Value=serde_json::from_slice(&std::fs::read(root.join("strategy/qualification-decisions/closed-cuts/sha256").join(&qualified_id[..2]).join(qualified_id).join("manifest.json")).unwrap()).unwrap();
    assert!(cut["entries"].as_array().unwrap().iter().any(|entry|entry["identity"]==decision_id));
    assert_eq!(authority.refresh_projection(session.client_mut().await.unwrap()).await.unwrap(),fresh,"the same healthy captured owners remain readable without reacquiring their exclusive cut locks");
    assert!(!root.join("qualification-decisions/sha256").join(&decision_id[..2]).join(&decision_id).exists(),"canonical Decisions are never mirrored into the legacy owner");
    assert_eq!(std::fs::read(&base_profile).unwrap(),base_bytes);
    assert_eq!(std::fs::read(&extension_path).unwrap(),extension_bytes);
    // A real action-time proof must retain the actual owning Q/Policy/Counts
    // verification after the source verifier and its local cache are dropped.
    let action_command=CommandId::new("00000000-0000-4000-8000-000000000776").unwrap();
    let action_group=authority.seal(session.client_mut().await.unwrap(),&action_command,std::slice::from_ref(&subject),"onlyalpha.factor-research","1",&fresh).await.unwrap();
    assert_eq!(action_group["disposition"],"ACTIONABLE");
    let action=authority.authorize_action(session.client_mut().await.unwrap(),&action_command,std::slice::from_ref(&subject),&fresh).await.unwrap();
    action.verify_cut().unwrap();
    {
        use std::os::unix::fs::PermissionsExt;
        let decision_path=root.join("strategy/qualification-decisions/sha256").join(&decision_id[..2]).join(&decision_id).join("manifest.json");
        let policy_path=root.join("strategy/qualification-policies/experimental-backtest/1/manifest.json");
        for path in [decision_path,policy_path] {
            let bytes=std::fs::read(&path).unwrap();let permissions=std::fs::metadata(&path).unwrap().permissions();
            std::fs::set_permissions(&path,std::fs::Permissions::from_mode(permissions.mode()|0o200)).unwrap();
            std::fs::write(&path,b"corrupt retained qualification dependency").unwrap();
            let rejected=action.verify_cut().is_err();
            std::fs::write(&path,&bytes).unwrap();std::fs::set_permissions(&path,permissions).unwrap();
            assert!(rejected,"ActionProof cannot discard owning Qualification dependencies after capture");
            action.verify_cut().unwrap();
        }
    }
    drop(action);
    let replay=authority.seal(session.client_mut().await.unwrap(),&command,std::slice::from_ref(&subject),"onlyalpha.factor-research","1",&fresh).await.unwrap();
    assert_eq!(replay,group,"original retained enum1 group is audited against original exact sources");
    assert_eq!(std::fs::read(&legacy_file).unwrap(),legacy_bytes);
    assert_eq!(std::fs::read(root.join("experiment-memory/revisions/sha256").join(&identity[..2]).join(&identity).join("projection.json")).unwrap(),original_projection_bytes);
    let absent=legacy_file.with_file_name("use_test_original_cut_unavailable");std::fs::rename(&legacy_file,&absent).unwrap();
    let missing=authority.seal(session.client_mut().await.unwrap(),&command,std::slice::from_ref(&subject),"onlyalpha.factor-research","1",&fresh).await.is_err();
    std::fs::rename(&absent,&legacy_file).unwrap();
    assert!(missing,"missing original enum1 fact must not fallback to a current enum2 cut");
    let decision_path=root.join("strategy/qualification-decisions/sha256").join(&decision_id[..2]).join(&decision_id).join("manifest.json");
    let bytes=std::fs::read(&decision_path).unwrap();std::fs::write(&decision_path,b"corrupt canonical decision").unwrap();
    let rejected=authority.refresh_projection(session.client_mut().await.unwrap()).await.is_err();
    assert_eq!(std::fs::read(&decision_path).unwrap(),b"corrupt canonical decision");std::fs::write(&decision_path,&bytes).unwrap();
    assert!(rejected,"legacy empty top owner cannot conceal a canonical Decision fact");
    println!("STRATEGY_EVIDENCE_VALUE {}",json!({"qualification_source_history":true,"decision":decision_id,"legacy_projection":identity,"current_projection":fresh}));
}
