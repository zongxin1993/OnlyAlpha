use super::*;

#[test]
fn checkpoint_requires_the_original_library_release_and_artifact() {
    let scope = Scope::decode(&json!({
        "engine":"engine", "runtime":"runtime", "gateway":"virtual", "account":"account",
        "generation":"a".repeat(64), "runtime_kind":"BACKTEST"
    }))
    .unwrap();
    let cash = OnlyMoney::from_record(&json!({
        "schema_version":1, "amount":"100000.00",
        "currency":{"schema_version":1,"code":"CNY","precision":2,"currency_type":"FIAT"}
    }))
    .unwrap();
    let artifact = "b".repeat(64);
    let config = json!({});
    let venue = VirtualBroker::new(scope.clone(), &artifact, cash.clone(), &config).unwrap();
    let mut cut = venue.checkpoint();
    assert_eq!(cut["binding"]["release_id"], "libs");
    assert_eq!(cut["binding"]["plugin_id"], "virtual");
    assert_eq!(cut["binding"]["version"], env!("CARGO_PKG_VERSION"));
    let restore = |cut: &Value, artifact: &str| {
        VirtualBroker::restore(
            scope.clone(),
            artifact,
            cash.clone(),
            &config,
            cut,
            &digest(cut),
        )
    };
    assert_eq!(restore(&cut, &artifact).unwrap().checkpoint(), cut);
    assert_eq!(
        restore(&cut, &"c".repeat(64)).err().unwrap().to_string(),
        "VIRTUAL_CHECKPOINT_BINDING"
    );
    cut["binding"]["release_id"] = json!("plugin-onlyalpha-broker-virtual");
    assert_eq!(
        restore(&cut, &artifact).err().unwrap().to_string(),
        "VIRTUAL_CHECKPOINT_BINDING"
    );
}
