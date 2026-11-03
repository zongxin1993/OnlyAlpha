//! Owning seals for immutable native Backtest evidence, never caller DTO grants.
mod context;
pub(crate) use context::{BacktestReadContext,read_context};
pub(crate) use context::implementations as verify_implementation_bindings;
mod physical;
mod store;
pub(crate) use store::{Store,VerifiedEvidence};
mod manifest;
pub use manifest::Manifest;
use crate::security::immutable_json::SourceLock;
#[cfg(test)]
use crate::application::backtest_run::VerifiedRun;
use std::sync::Arc;
type Result<T>=std::result::Result<T,&'static str>;
const INVALID:&str="BACKTEST_EVIDENCE_CORRUPT";
const UNAVAILABLE:&str="BACKTEST_EVIDENCE_UNAVAILABLE";
const BUDGET:usize=128*1024*1024;

pub struct CompletionProof {
    run:String,
    specification:String,
    resolution:String,
    status:String,
    evidence:String,
    result:String,
    determinism:String,
    cut:Vec<Arc<SourceLock>>,
    verified:Option<Arc<store::Cut>>,
}
impl CompletionProof {
    pub fn run_id(&self)->&str {&self.run}
    pub fn specification_fingerprint(&self)->&str {&self.specification}
    pub fn admission_resolution_fingerprint(&self)->&str {&self.resolution}
    pub fn status(&self)->&str {&self.status}
    pub fn evidence_fingerprint(&self)->&str {&self.evidence}
    pub fn result_fingerprint(&self)->&str {&self.result}
    pub fn determinism_fingerprint(&self)->&str {&self.determinism}
    pub fn verify_cut(&self)->Result<()> {
        if self.cut.is_empty() {return Err("BACKTEST_EVIDENCE_CUT_REQUIRED");}
        for lock in &self.cut {lock.verify()?;}
        if let Some(verified)=&self.verified {verified.verify()?;}
        Ok(())
    }
    #[cfg(test)]
    pub(crate) fn for_value_test(run:&VerifiedRun,status:&str,evidence:&str,result:&str,determinism:&str,cut:Arc<SourceLock>)->Result<Self> {
        if !matches!(status,"COMPLETED"|"CANCELLED") || [evidence,result,determinism].iter().any(|s|!crate::is_sha256_hex(s)) {return Err("BACKTEST_EVIDENCE_INVALID");}
        cut.verify()?;
        Ok(Self{run:run.run_id().into(),specification:run.specification_fingerprint().into(),resolution:run.admission_resolution_fingerprint().into(),status:status.into(),evidence:evidence.into(),result:result.into(),determinism:determinism.into(),cut:vec![cut],verified:None})
    }
}

#[cfg(test)]
mod native_manifest_tests {
    use super::Manifest;
    use crate::application::factor_content::hash;
    use serde_json::{Value,json};
    fn sign(mut value:Value)->Value {
        value.as_object_mut().unwrap().remove("evidence_fingerprint");
        value["evidence_fingerprint"]=json!(hash(&value).unwrap());value
    }
    // Pure independent wire values. These records confer no Runtime, joined
    // producer, CompletionProof, Run publication or historical owning grant.
    fn native()->Value {
        sign(json!({"schema_version":2,"kind":"NATIVE_BTC_SPOT_NEXT_OPEN_EVIDENCE",
            "backtest_run_id":"00000000-0000-4000-8000-000000000802",
            "specification_fingerprint":"a".repeat(64),"admission_resolution_fingerprint":"b".repeat(64),
            "strategy_fingerprint":"c".repeat(64),"dataset_snapshot_fingerprint":"d".repeat(64),
            "dataset_binding_fingerprint":"e".repeat(64),"runtime_generation_fingerprint":"f".repeat(64),
            "preparation_fingerprint":"1".repeat(64),"result_fingerprint":"2".repeat(64),"determinism_fingerprint":"2".repeat(64),
            "artifacts":(["observation.json","replay-proof.json","replay-trace.json","result.json","runtime.json"].into_iter().enumerate()
                .map(|(i,name)|json!({"name":name,"sha256":format!("{i:064x}"),"size":i+1,"media_type":"application/json"})).collect::<Vec<_>>())}))
    }
    fn legacy()->Value {
        sign(json!({"schema_version":1,"backtest_run_id":"retained-original-public-run",
            "specification_fingerprint":"a".repeat(64),"admission_resolution_fingerprint":"b".repeat(64),
            "strategy_fingerprint":"c".repeat(64),"dataset_binding_fingerprint":"d".repeat(64),
            "base_dataset_snapshot_fingerprint":"e".repeat(64),"market_product_composition_fingerprint":"f".repeat(64),
            "portfolio_profile_fingerprint":"1".repeat(64),"risk_profile_fingerprint":"2".repeat(64),"execution_profile_fingerprint":"3".repeat(64),
            "kernel_semantics_version":"retained-reference-vector","implementation_fingerprints":["4".repeat(64),"5".repeat(64)],
            "result_fingerprint":"6".repeat(64),"determinism_fingerprint":"7".repeat(64),
            "artifacts":[{"name":"result.json","sha256":"8".repeat(64),"size":0,"media_type":"application/json"}]}))
    }
    #[test]
    fn native_manifest2_has_one_explicit_identity_without_fabricated_legacy_profiles() {
        let original=native();let parsed=Manifest::from_record(&original).unwrap();
        assert_eq!(parsed.schema_version(),2);assert_eq!(parsed.record(),&original);
        assert_eq!(parsed.fingerprint(),original["evidence_fingerprint"].as_str().unwrap());
        let mut body=original.clone();body.as_object_mut().unwrap().remove("evidence_fingerprint");
        assert_eq!(parsed.fingerprint(),hash(&body).unwrap());
        for key in ["backtest_run_id","specification_fingerprint","admission_resolution_fingerprint","strategy_fingerprint",
            "dataset_snapshot_fingerprint","dataset_binding_fingerprint","runtime_generation_fingerprint","preparation_fingerprint","result_fingerprint","determinism_fingerprint"] {
            let mut changed=body.clone();changed[key]=if key=="backtest_run_id" {json!("00000000-0000-4000-8000-000000000803")}else{json!("9".repeat(64))};
            let changed=sign(changed);let second=Manifest::from_record(&changed).unwrap();assert_ne!(second.fingerprint(),parsed.fingerprint(),"{key}");
        }
        for key in ["market_product_composition_fingerprint","portfolio_profile_fingerprint","risk_profile_fingerprint","execution_profile_fingerprint",
            "kernel_semantics_version","implementation_fingerprints","actor","created_at","joined","complete","authority","schema_version_alias"] {
            let mut changed=body.clone();changed[key]=json!("not an owning fact");assert!(Manifest::from_record(&sign(changed)).is_err(),"{key}");
        }
    }
    #[test]
    fn native_manifest3_pins_encoded_trace_and_logical_identity_without_relabelling_manifest2() {
        let old=native();let mut streamed=old.clone();
        streamed["schema_version"]=json!(3);
        streamed["trace_format"]=json!("RUNTIME_ENCODED_REPLAY_TRACE@2");
        streamed["logical_trace_fingerprint"]=json!("7".repeat(64));
        let streamed=sign(streamed);let parsed=Manifest::from_record(&streamed).unwrap();
        assert_eq!(parsed.schema_version(),3);assert_eq!(parsed.record(),&streamed);
        assert_ne!(parsed.fingerprint(),old["evidence_fingerprint"].as_str().unwrap());
        for key in ["trace_format","logical_trace_fingerprint"] {
            let mut missing=streamed.clone();missing.as_object_mut().unwrap().remove(key);
            assert!(Manifest::from_record(&sign(missing)).is_err(),"{key}");
        }
        for (key,value) in [("trace_format",json!("latest")),("logical_trace_fingerprint",json!("not-a-pin"))] {
            let mut changed=streamed.clone();changed[key]=value;
            assert!(Manifest::from_record(&sign(changed)).is_err(),"{key}");
        }
        let mut changed=streamed;changed["schema_version"]=json!(2);
        assert!(Manifest::from_record(&sign(changed)).is_err(),"new physical representation cannot relabel retained Evidence2");
        assert_eq!(Manifest::from_record(&old).unwrap().record(),&old);
    }
    #[test]
    fn native_manifest2_rejects_unknown_versions_paths_sets_and_non_exact_artifact_pins() {
        let original=native();
        for mutation in 0..18 {
            let mut changed=original.clone();
            match mutation {
                0=>changed["schema_version"]=json!(3),1=>changed["schema_version"]=json!(true),2=>changed["kind"]=json!("NATIVE_LIMIT"),
                3=>changed["backtest_run_id"]=json!("latest"),4=>changed["runtime_generation_fingerprint"]=json!("A".repeat(64)),
                5=>changed["dataset_snapshot_fingerprint"]=Value::Null,6=>{changed.as_object_mut().unwrap().remove("preparation_fingerprint");},
                7=>changed["artifacts"].as_array_mut().unwrap().reverse(),8=>{changed["artifacts"].as_array_mut().unwrap().pop();},
                9=>{let row=changed["artifacts"][0].clone();changed["artifacts"].as_array_mut().unwrap().push(row);},
                10=>changed["artifacts"][0]["name"]=json!("../observation.json"),11=>changed["artifacts"][0]["name"]=json!("/observation.json"),
                12=>changed["artifacts"][0]["name"]=json!("manifest.json"),13=>changed["artifacts"][0]["size"]=json!(-1),
                14=>changed["artifacts"][0]["size"]=json!(true),15=>changed["artifacts"][0]["sha256"]=json!("f".repeat(63)),
                16=>changed["artifacts"][0]["media_type"]=json!("text/plain"),_=>changed["artifacts"][0]["path"]=json!("hidden"),
            }
            assert!(Manifest::from_record(&sign(changed)).is_err(),"mutation {mutation}");
        }
        let mut rehashed=original;rehashed["artifacts"][0]["size"]=json!(100);
        assert!(Manifest::from_record(&rehashed).is_err(),"integrity must be checked before an owning proof exists");
    }
    #[test]
    fn retained_manifest1_keeps_its_original_bytes_and_never_becomes_native2() {
        let original=legacy();let bytes=serde_json::to_vec(&original).unwrap();let parsed=Manifest::from_record(&original).unwrap();
        assert_eq!(parsed.schema_version(),1);assert_eq!(parsed.record(),&original);assert_eq!(serde_json::to_vec(parsed.record()).unwrap(),bytes);
        // Legacy1 allowed a nonempty original Run name, zero-sized artifacts,
        // distinct result/determinism values and no native "kind" field.
        assert_eq!(parsed.fingerprint(),original["evidence_fingerprint"].as_str().unwrap());
        for mutation in 0..5 {
            let mut changed=original.clone();match mutation {
                0=>changed["schema_version"]=json!(2),1=>changed["kind"]=json!("NATIVE_BTC_SPOT_NEXT_OPEN_EVIDENCE"),
                2=>{changed.as_object_mut().unwrap().remove("portfolio_profile_fingerprint");},
                3=>changed["runtime_generation_fingerprint"]=json!("f".repeat(64)),_=>changed["implementation_fingerprints"].as_array_mut().unwrap().reverse(),
            }
            assert!(Manifest::from_record(&sign(changed)).is_err(),"legacy mutation {mutation}");
        }
        let mut empty=original;empty["artifacts"]=json!([]);empty["implementation_fingerprints"]=json!([]);
        assert!(Manifest::from_record(&sign(empty)).is_ok(),"retain the original Manifest1 value contract; absence of owning closure never grants publication");
    }
}

#[cfg(test)]
#[path="../../tests/application/support/backtest_evidence_assertions.rs"]
pub(crate) mod owner_tests;
