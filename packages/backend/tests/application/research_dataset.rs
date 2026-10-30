use onlyalpha_backend::application::research_dataset::Dataset;
use serde_json::{Value, json};
fn bar() -> Value {
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/market_wal_history.json")).unwrap();
    let bundle: Value =
        serde_json::from_str(fixture["native_bundle_json"].as_str().unwrap()).unwrap();
    bundle["canonical_facts"][0]["canonical_payload"]["payload"]["value"].clone()
}
#[test]
fn exact_dataset_materialization_preserves_domain_and_nanoseconds() {
    let b = bar();
    let definition = json!({"schema_version":2,"dataset_type":"HISTORICAL_BAR","instruments":["BTCUSDT.BINANCE"],"bar_semantic":b["bar_type"]["semantic"],"time_range":{"start":"2026-01-01T00:00:00+00:00","end":"2026-01-01T00:02:00+00:00"},"quality_policy":"STRICT","closed_only":true});
    let d = Dataset::from_bars(&definition, &[b], &"a".repeat(64), 100).unwrap();
    assert_eq!(d.rows()[0]["ts_event_ns"], json!(1767225660000000000_i64));
    assert_eq!(d.rows()[0]["close"], "101.000000000000000000");
}

fn reference() -> Value {
    serde_json::from_slice(
        &std::fs::read(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                .join("tests/application/fixtures/research_dataset.json"),
        )
        .unwrap(),
    )
    .unwrap()
}
fn dataset() -> Dataset {
    let r = reference();
    Dataset::from_bars(
        &r["definition"],
        r["bars"].as_array().unwrap(),
        r["construction_fingerprint"].as_str().unwrap(),
        100,
    )
    .unwrap()
}
fn provenance() -> Value {
    json!([{"instrument_id":"BTCUSDT.BINANCE","source_id":"BINANCE_SPOT","plugin_id":"durable-market-data","plugin_version":"1","data_version":"BINANCE_SPOT_V1","cache_content_fingerprint":null,"resolved_ranges":[["start","end"]],"observed_ranges":[["start","end"]],"source_metadata":{}}])
}
struct Temp(std::path::PathBuf);
impl Temp {
    fn new() -> Self {
        let mut entropy = [0u8; 16];
        getrandom::fill(&mut entropy).unwrap();
        let name = entropy
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect::<String>();
        let p = std::env::temp_dir().join(format!("onlyalpha-dataset-{name}"));
        std::fs::create_dir(&p).unwrap();
        Self(p)
    }
}
impl Drop for Temp {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}
#[test]
fn canonical_dataset_rows_and_identities_match_independent_arrow_sdk() {
    let r = reference();
    let d = dataset();
    assert_eq!(d.rows(), r["rows"].as_array().unwrap());
    assert_eq!(d.definition(), &r["definition"]);
    assert_eq!(
        onlyalpha_backend::application::research_dataset::schema(),
        r["schema"]
    );
    assert_eq!(
        d.content_fingerprint(),
        r["content_fingerprint"].as_str().unwrap()
    );
    assert_eq!(
        d.snapshot_fingerprint(),
        r["snapshot_fingerprint"].as_str().unwrap()
    );
    assert_eq!(
        d.rows()[1]["close"],
        "12345678901234567890.123456789012345678"
    );
    assert_eq!(
        d.rows()[1]["ts_event_ns"].as_i64().unwrap() % 1_000_000_000,
        123457000
    );
}
#[test]
fn invalid_dataset_and_duplicate_logical_bars_are_not_repaired() {
    let r = reference();
    let bars = r["bars"].as_array().unwrap();
    for (key, value) in [
        ("closed_only", json!(false)),
        ("quality_policy", json!("LENIENT")),
        ("schema_version", json!(true)),
        ("instruments", json!(["BTCUSDT.BINANCE", "BTCUSDT.BINANCE"])),
    ] {
        let mut d = r["definition"].clone();
        d[key] = value;
        assert!(
            Dataset::from_bars(&d, bars, &"a".repeat(64), 100).is_err(),
            "{key}"
        );
    }
    let mut duplicate = bars.clone();
    duplicate.push(bars[0].clone());
    assert!(Dataset::from_bars(&r["definition"], &duplicate, &"a".repeat(64), 100).is_err());
    let mut open = bars.clone();
    open[0]["is_closed"] = json!(false);
    assert!(Dataset::from_bars(&r["definition"], &open, &"a".repeat(64), 100).is_err());
    assert!(Dataset::from_bars(&r["definition"], bars, &"a".repeat(64), 1).is_err());
}
#[test]
fn parquet_publication_reopen_and_put_once_reuse_preserve_exact_identity() {
    use onlyalpha_backend::persistence::research_dataset::Store;
    let root = Temp::new();
    let d = dataset();
    let store = Store::open(&root.0, 100, 1024 * 1024).unwrap();
    let a = store
        .commit(&d, &provenance(), "2026-10-29T00:00:00Z")
        .unwrap();
    assert_eq!(a.dataset().rows(), d.rows());
    let b = Store::open(&root.0, 100, 1024 * 1024)
        .unwrap()
        .load(d.snapshot_fingerprint())
        .unwrap();
    assert_eq!(a.manifest(), b.manifest());
    let c = store
        .commit(&d, &provenance(), "2026-10-30T00:00:00Z")
        .unwrap();
    assert_eq!(a.manifest(), c.manifest());
}
#[test]
fn corrupt_or_missing_published_files_are_never_overwritten_or_reused() {
    use onlyalpha_backend::persistence::research_dataset::Store;
    for corruption in ["bytes", "missing", "manifest"] {
        let root = Temp::new();
        let d = dataset();
        let store = Store::open(&root.0, 100, 1024 * 1024).unwrap();
        store
            .commit(&d, &provenance(), "2026-10-29T00:00:00Z")
            .unwrap();
        let target = root
            .0
            .join("sha256")
            .join(&d.snapshot_fingerprint()[..2])
            .join(d.snapshot_fingerprint());
        let p = target.join("data/p-000000.parquet");
        match corruption {
            "bytes" => std::fs::write(&p, b"corrupt").unwrap(),
            "missing" => std::fs::remove_file(&p).unwrap(),
            _ => {
                let path = target.join("manifest.json");
                let mut m: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
                m["definition"]["instruments"] = json!(["OTHER.BINANCE"]);
                std::fs::write(path, serde_json::to_vec(&m).unwrap()).unwrap();
            }
        }
        assert!(
            store.load(d.snapshot_fingerprint()).is_err(),
            "{corruption}"
        );
        assert!(
            store
                .commit(&d, &provenance(), "2026-10-29T00:00:00Z")
                .is_err(),
            "{corruption}"
        );
    }
}
#[test]
fn rebound_root_and_symlinked_partition_are_not_acknowledged() {
    use onlyalpha_backend::persistence::research_dataset::Store;
    let root = Temp::new();
    let d = dataset();
    let store = Store::open(&root.0, 100, 1024 * 1024).unwrap();
    store
        .commit(&d, &provenance(), "2026-10-29T00:00:00Z")
        .unwrap();
    let target = root
        .0
        .join("sha256")
        .join(&d.snapshot_fingerprint()[..2])
        .join(d.snapshot_fingerprint());
    let p = target.join("data/p-000000.parquet");
    let moved = target.join("saved.parquet");
    std::fs::rename(&p, &moved).unwrap();
    std::os::unix::fs::symlink(&moved, &p).unwrap();
    assert!(store.load(d.snapshot_fingerprint()).is_err());
    let moved_root = root.0.with_extension("moved");
    std::fs::rename(&root.0, &moved_root).unwrap();
    std::fs::create_dir(&root.0).unwrap();
    assert!(store.load(d.snapshot_fingerprint()).is_err());
    std::fs::remove_dir_all(moved_root).unwrap();
}
#[test]
fn selected_snapshot_read_budget_fails_before_decoding_or_certifying_absence() {
    use onlyalpha_backend::persistence::research_dataset::Store;
    let root = Temp::new();
    let d = dataset();
    let store = Store::open(&root.0, 100, 1024 * 1024).unwrap();
    store
        .commit(&d, &provenance(), "2026-10-29T00:00:00Z")
        .unwrap();
    assert!(
        Store::open(&root.0, 1, 1024 * 1024)
            .unwrap()
            .load(d.snapshot_fingerprint())
            .is_err()
    );
    assert!(
        Store::open(&root.0, 100, 64)
            .unwrap()
            .load(d.snapshot_fingerprint())
            .is_err()
    );
}

#[test]
fn source_scope_is_validated_before_any_physical_materialization_read() {
    use onlyalpha_backend::{
        application::research_dataset::NativeMaterializationPlan, persistence::market_data::Scope,
    };
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/market_wal_history.json")).unwrap();
    let metadata: Value =
        serde_json::from_str(fixture["native_metadata_json"].as_str().unwrap()).unwrap();
    let mut s = json!({});
    for key in [
        "source_id",
        "market",
        "instrument_id",
        "data_kind",
        "start_ns",
        "end_ns",
        "data_version",
        "bar_type",
        "first_sequence",
        "last_sequence",
        "bar_construction",
    ] {
        s[key] = metadata[key].clone();
    }
    let scope = Scope::from_record(&s).unwrap();
    let b = bar();
    let definition = json!({"schema_version":2,"dataset_type":"HISTORICAL_BAR","instruments":["BTCUSDT.BINANCE"],"bar_semantic":b["bar_type"]["semantic"],"time_range":{"start":"2026-01-01T00:01:00Z","end":"2026-01-01T00:02:00Z"},"quality_policy":"STRICT","closed_only":true});
    assert!(
        NativeMaterializationPlan::new(
            &definition,
            &format!("market-data-revision:{}", "a".repeat(64)),
            scope.clone(),
            100
        )
        .is_ok()
    );
    let mut wider = definition.clone();
    wider["time_range"]["end"] = json!("2026-01-01T00:03:00Z");
    assert!(
        NativeMaterializationPlan::new(
            &wider,
            &format!("market-data-revision:{}", "a".repeat(64)),
            scope.clone(),
            100
        )
        .is_err()
    );
    assert!(
        NativeMaterializationPlan::new(&definition, "some-latest-id", scope.clone(), 100).is_err()
    );
    assert!(
        NativeMaterializationPlan::new(
            &definition,
            &format!("market-data-revision:{}", "a".repeat(64)),
            scope,
            0
        )
        .is_err()
    );
}

#[test]
fn native_dataset_retains_microseconds_without_binary_float_seconds() {
    let value = dataset();
    let rows = value.rows();
    let original = reference();
    assert_eq!(rows[1]["ts_event_ns"], original["rows"][1]["ts_event_ns"]);
    let nanos = rows[1]["ts_event_ns"].as_i64().unwrap();
    assert_eq!(nanos.rem_euclid(1_000_000_000), 123457000);
}
#[test]
fn native_decimal128_retains_all_38_digits_without_ambient_python_context() {
    assert_eq!(
        dataset().rows()[1]["close"],
        "12345678901234567890.123456789012345678"
    );
}
