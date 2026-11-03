//! Actual worker fixtures supply JoinedBacktest. No value/seal factory exists here.
use super::{BacktestReadContext,CompletionProof,Manifest,Store,VerifiedEvidence};
use crate::workers::backtest_service::JoinedBacktest;
use serde_json::Value;
use std::{path::Path,os::unix::fs::{MetadataExt,PermissionsExt}};
type Result<T>=std::result::Result<T,&'static str>;
const ARTIFACTS:[&str;5]=["observation.json","replay-proof.json","replay-trace.json","result.json","runtime.json"];
#[test]
fn native_evidence2_publication_api_consumes_only_the_actual_joined_product() {
    let _:fn(&Store,JoinedBacktest)->Result<CompletionProof>=Store::commit;
    let _:fn(&Store,&BacktestReadContext)->Result<Option<VerifiedEvidence>>=Store::read_verified;
    let _:fn(&Manifest)->&Value=Manifest::record;
    let _:fn(&VerifiedEvidence)->&Manifest=VerifiedEvidence::manifest;
    let _:fn(&VerifiedEvidence)->&Value=VerifiedEvidence::observation;
}
fn file(path:&Path)->(u64,Vec<u8>) {(std::fs::metadata(path).unwrap().ino(),std::fs::read(path).unwrap())}
fn mutate_retained(path:&Path,verify:impl Fn()->bool) {
    let original=file(path);let mode=std::fs::metadata(path).unwrap().permissions();
    let mut bytes=original.1.clone();assert!(!bytes.is_empty());let last=bytes.len()-1;bytes[last]^=1;
    std::fs::set_permissions(path,std::fs::Permissions::from_mode(mode.mode()|0o200)).unwrap();std::fs::write(path,&bytes).unwrap();
    let refused=verify();let untouched=file(path);
    std::fs::write(path,&original.1).unwrap();std::fs::set_permissions(path,mode).unwrap();
    assert!(refused,"retained corruption must invalidate existing and fresh owning proofs");
    assert_eq!(untouched,(original.0,bytes),"failed read must neither heal nor replace the damaged fact");assert_eq!(file(path),original);
}
/// Call only with actual original READY/Run3 and a terminal concrete RunLoop
/// whose complete child group has positively joined. SQL completion follows.
pub(crate) fn commit_and_reopen(store:&Store,context:&BacktestReadContext,joined:JoinedBacktest,backtest_root:&Path)->CompletionProof {
    context.verify_cut().unwrap();
    let run=joined.run().clone();let expected=joined.observation().record().clone();
    let result=joined.observation().result().clone();let proof=joined.observation().proof().clone();let trace=joined.observation().trace().clone();
    let completed=store.commit(joined).unwrap();completed.verify_cut().unwrap();
    assert_eq!(completed.run_id(),run.run_id());assert_eq!(completed.specification_fingerprint(),run.specification_fingerprint());
    assert_eq!(completed.admission_resolution_fingerprint(),run.admission_resolution_fingerprint());
    assert_eq!(completed.result_fingerprint(),result["result_fingerprint"].as_str().unwrap());assert_eq!(completed.determinism_fingerprint(),result["determinism_fingerprint"].as_str().unwrap());
    let evidence=store.read_verified(context).unwrap().expect("joined publication is visible before SQL terminal commit");
    let expected_version=match trace["schema_version"].as_u64() {
        Some(1)=>2,
        Some(2) if trace["kind"]=="RUNTIME_ENCODED_REPLAY_TRACE"=>3,
        _=>panic!("unknown actual trace format"),
    };
    assert_eq!(evidence.manifest().schema_version(),expected_version);assert_eq!(evidence.manifest().fingerprint(),completed.evidence_fingerprint());
    assert_eq!(evidence.observation(),&expected);evidence.verify_cut().unwrap();
    let display=crate::transport::host_backtest::display_result(context,&evidence).expect("the actual retained native evidence must remain displayable");
    assert_eq!(display.run_id,run.run_id());assert_eq!(display.state,expected["status"].as_str().unwrap());
    assert_eq!(display.result_fingerprint,result["result_fingerprint"].as_str().unwrap());
    assert_eq!(display.metrics.fees,expected["account_summary"]["fees"].as_str().unwrap());
    assert_eq!(display.metrics.fill_count,expected["fill_count"].as_u64().unwrap());
    let fills=result["trades"].as_array().unwrap();
    assert_eq!(display.trades.len(),fills.len(),"encoded archives must not hide native fills from the result page");
    for (ordinal,(trade,fact)) in display.trades.iter().zip(fills).enumerate() {
        let input=&fact["input"];let payload=&input["payload"];
        assert_eq!(trade.ordinal,ordinal as u64+1);assert_eq!(input["op"],"FILL");
        assert_eq!(trade.order_id,payload["order"].as_str().unwrap());
        assert_eq!(trade.trade_id,payload["trade"].as_str().unwrap());
        assert_eq!(trade.quantity,payload["quantity"].as_str().unwrap());
        assert_eq!(trade.price,payload["price"].as_str().unwrap());
        assert_eq!(trade.time_ns,input["time"].as_u64().unwrap().to_string());
        assert!(matches!(trade.side.as_str(),"BUY"|"SELL"));
        assert!(trade.signal_time_ns.parse::<u64>().unwrap()<=input["time"].as_u64().unwrap());
        let _:onlyalpha_domain::numeric::OnlyDecimal=trade.fee.parse().unwrap();
    }
    for (name,value) in [("observation.json",&expected),("result.json",&result),("replay-proof.json",&proof),("replay-trace.json",&trace)] {
        let (bytes,media)=evidence.artifact(name).unwrap();assert_eq!(media,"application/json");assert_eq!(serde_json::from_slice::<Value>(&bytes).unwrap(),*value);
    }
    let path=backtest_root.join("evidence/sha256").join(&completed.evidence_fingerprint()[..2]).join(completed.evidence_fingerprint());
    let before=ARTIFACTS.into_iter().chain(["manifest.json"]).map(|name|(name,file(&path.join(name)))).collect::<std::collections::BTreeMap<_,_>>();
    let again=store.read_verified(context).unwrap().unwrap();again.verify_cut().unwrap();
    for (name,bytes) in &before {assert_eq!(file(&path.join(name)),*bytes);}
    for name in ARTIFACTS.into_iter().chain(["manifest.json"]) {
        mutate_retained(&path.join(name),||completed.verify_cut().is_err()&&evidence.verify_cut().is_err()&&store.read_verified(context).is_err()&&crate::transport::host_backtest::display_result(context,&evidence).is_err());
        completed.verify_cut().unwrap();evidence.verify_cut().unwrap();
    }
    let mut names=std::fs::read_dir(&path).unwrap().map(|e|e.unwrap().file_name().into_string().unwrap()).collect::<Vec<_>>();names.sort();
    let mut expected_names=ARTIFACTS.into_iter().chain(["manifest.json"]).collect::<Vec<_>>();expected_names.sort();assert_eq!(names,expected_names);
    if completed.status()=="CANCELLED" {assert_eq!(expected["status"],"CANCELLED");assert!(expected["baseline"].is_null());assert_eq!(proof["drained"],true);}
    else{assert_eq!(completed.status(),"COMPLETED");assert_eq!(proof["market_exhausted"],true);assert_eq!(proof["drained"],true);}
    drop(again);drop(evidence);completed
}
/// Call after the same physical SQL owner persisted terminal pins; external
/// targets are actual retained ELF/wheels/Dataset/Frozen bytes from that fixture.
pub(crate) fn terminal_missing_and_external_tamper(store:&Store,context:&BacktestReadContext,backtest_root:&Path,external_files:&[std::path::PathBuf]) {
    let run=context.run();context.verify_cut().unwrap();
    let evidence=store.read_verified(context).unwrap().unwrap();evidence.verify_cut().unwrap();
    let id=evidence.manifest().fingerprint().to_owned();let parts=run.completion_fingerprints().expect("actual terminal three pins");
    assert_eq!(parts.0,id);assert_eq!(parts.1,evidence.manifest().record()["result_fingerprint"]);assert_eq!(parts.2,evidence.manifest().record()["determinism_fingerprint"]);
    for path in external_files {mutate_retained(path,||evidence.verify_cut().is_err()&&store.read_verified(context).is_err());evidence.verify_cut().unwrap();}
    let path=backtest_root.join("evidence/sha256").join(&id[..2]).join(&id);let retained=backtest_root.join(format!(".use_test_unavailable_{id}"));
    std::fs::rename(&path,&retained).unwrap();let refused=store.read_verified(context).is_err();let still_missing=!path.exists();std::fs::rename(&retained,&path).unwrap();
    assert!(refused&&still_missing,"pinned terminal missing history is corruption, never Absent or an opportunity to repair");evidence.verify_cut().unwrap();
}
