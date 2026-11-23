//! 使用真实 Account 公共接口验证诊断模式不改变恢复、重复应用和拒绝结果。
use onlyalpha_account::{Manager, Status, digest};
use onlyalpha_observability::{Config, Correlation, Mode, Session, measure};
use serde_json::Value;

#[test]
fn account_checkpoint_identity_and_original_errors_do_not_depend_on_diagnostic_mode() {
    let fixture: Value = serde_json::from_str(include_str!(
        "../../../../test-data/backtest-benchmarks/small.json"
    ))
    .unwrap();
    let cp = &fixture["execution"]["components"][2];
    let bytes = serde_json::to_vec(cp).unwrap();
    let original = digest(&bytes);
    let mut expected = None;
    for mode in [Mode::Off, Mode::Basic, Mode::Detail] {
        let session = Session::new(
            Config::new(mode, "account-regression", 256),
            std::io::sink(),
        )
        .unwrap();
        let actual = tracing::dispatcher::with_default(session.dispatch(), || {
            let mut owner = if cp["schema_version"] == 5 {
                Manager::new_checkpoint5(cp["config"].clone()).unwrap()
            } else {
                Manager::new(cp["config"].clone()).unwrap()
            };
            measure("backend", "account.restore", Correlation::default(), || {
                owner.restore(&bytes, &original)
            })
            .unwrap();
            let before = owner.checkpoint().unwrap();
            assert_eq!(before.0, bytes);
            let refused = measure(
                "backend",
                "account.restore_bad_digest",
                Correlation::default(),
                || owner.restore(&bytes, &"0".repeat(64)),
            )
            .unwrap_err();
            assert_eq!(owner.checkpoint().unwrap(), before);
            let duplicate = measure(
                "backend",
                "account.duplicate",
                Correlation::default(),
                || owner.apply(&cp["journal"][0]),
            )
            .unwrap();
            assert_eq!(duplicate.status, Status::Duplicate);
            assert_eq!(owner.checkpoint().unwrap(), before);
            (before, refused, duplicate.fact)
        });
        assert!(session.close().shutdown_complete);
        if let Some(expected) = &expected {
            assert_eq!(&actual, expected);
        } else {
            expected = Some(actual);
        }
    }
}
