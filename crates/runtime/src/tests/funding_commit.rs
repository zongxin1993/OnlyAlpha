use super::{INTERRUPT_FUNDING_COMMIT, Store};
use crate::{BoundBrokerJournal, Runtime};
#[path = "../../tests/support/perpetual_run.rs"]
mod perpetual_run;
use perpetual_run::{artifact, prepare_prefix, scenario};

#[test]
fn before_and_after_sqlite_commit_loss_recover_exact_original_funding_once() {
    let (cfg, inputs) = scenario();
    let (_comparison, uninterrupted) = prepare_prefix(&cfg, &inputs, 7);
    let expected = uninterrupted.state().unwrap();
    for committed in [false, true] {
        let (root, mut rt) = prepare_prefix(&cfg, &inputs, 6);
        rt.save_checkpoint().unwrap();
        let plan = rt.prepare_original_funding(&inputs[6]).unwrap();
        INTERRUPT_FUNDING_COMMIT.with(|point| point.set(Some(committed)));
        assert_eq!(
            rt.apply_original_funding(&plan).unwrap_err().0,
            "TEST_COMMIT_UNKNOWN"
        );
        assert_eq!(rt.store.get(7).unwrap().is_some(), committed);
        drop(rt);
        let mut recovered = Runtime::open(&root.0, cfg.clone(), &artifact()).unwrap();
        if committed {
            assert_eq!(recovered.state().unwrap(), expected);
        }
        recovered.apply(&inputs[6]).unwrap();
        recovered.apply(&inputs[6]).unwrap();
        assert_eq!(recovered.state().unwrap(), expected);
        assert_eq!(
            recovered.records().unwrap(),
            uninterrupted.records().unwrap()
        );
    }
}

#[test]
fn committed_but_unready_funding_projection_cannot_issue_a_sealed_transcript() {
    use onlyalpha_execution::{ProjectionData, digest};
    use serde_json::json;
    let (cfg, inputs) = scenario();
    let (root, mut runtime) = prepare_prefix(&cfg, &inputs, 6);
    let (owners, mut rows) = runtime.fork_ready().unwrap();
    let native = runtime.prepare_original_funding(&inputs[6]).unwrap();
    INTERRUPT_FUNDING_COMMIT.with(|point| point.set(Some(true)));
    assert_eq!(
        runtime.apply_original_funding(&native).unwrap_err().0,
        "TEST_COMMIT_UNKNOWN"
    );
    let tail = runtime.store.get(7).unwrap().unwrap();
    assert!(!tail.ready());
    rows.push(tail);
    let mut data = ProjectionData::new(&owners, &rows);
    data.replay().unwrap();
    let manifest = json!({"schema_version":1,"configuration":digest(cfg.to_string().as_bytes()),"kernel_artifact":artifact(),"input_pin":"c".repeat(64),"initial_time":{"schema_version":1,"unix_nanos":inputs[0]["time"]},"final_time":{"schema_version":1,"unix_nanos":inputs[6]["time"]},"inputs":inputs.iter().map(|v| digest(v.to_string().as_bytes())).collect::<Vec<_>>()});
    let outcome =
        json!({"schema_version":1,"status":"INCOMPLETE","reason":"pending commit comparison"});
    let result = data.transcript(&manifest, &outcome).unwrap().record();
    assert!(!runtime.store.get(7).unwrap().unwrap().ready());
    assert!(
        [
            "final_seal",
            "id",
            "determinism_fingerprint",
            "result_fingerprint"
        ]
        .iter()
        .all(|field| result.get(*field).is_none()),
        "本地回放不应替未实际 Ready 的 SQL 尾行签发正式封存"
    );
    drop(runtime);
    let recovered = Runtime::open(&root.0, cfg, &artifact()).unwrap();
    let actual = recovered
        .backtest_result(&manifest, &outcome)
        .unwrap()
        .record();
    assert!(!actual["final_seal"].is_null());
    assert!(actual["id"].as_str().unwrap().starts_with("BTR-"));
    assert_eq!(
        actual["determinism_fingerprint"].as_str().unwrap().len(),
        64
    );
    assert_eq!(
        actual["result_fingerprint"],
        actual["determinism_fingerprint"]
    );
    for (field, value) in result.as_object().unwrap() {
        assert_eq!(
            actual.get(field.as_str()),
            Some(value),
            "候选经济数据与实际封存的字段 {field} 应一致"
        );
    }
}
