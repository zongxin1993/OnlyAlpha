//! Filesystem acceptance for the canonical market-data WAL, not Product UI proof.
use onlyalpha_product_runtime::market_data_wal::{Error, Recovery, Wal};
use serde_json::{Value, json};
use std::{fs, path::PathBuf};
struct Root(PathBuf);
impl Root {
    fn new(label: &str) -> Self {
        let p = std::env::temp_dir().join(format!(
            "onlyalpha-market-wal-test-{}-{label}",
            std::process::id()
        ));
        fs::create_dir(&p).unwrap();
        Self(p)
    }
}
impl Drop for Root {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}
fn bundle() -> Value {
    json!({"schema_version":1,"evidence":{
        "raw_event_id":"raw-event:a","source_id":"source","capture_session_id":"capture",
        "provider":"PROVIDER","venue":"VENUE","market":"CASH","stream":"history",
        "provider_event_type":"page","provider_event_id":null,"provider_sequence":null,
        "ts_event_ns":null,"ts_receive_ns":1,"payload_codec":"application/json","provider_schema":"v1",
        "payload_base64":"e30=","raw_sha256":"44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a",
        "provenance":"REST_BACKFILL"},"canonical_facts":[]})
}
const CREATED: &str = "2026-10-22T00:00:00+00:00";
#[test]
fn durable_append_seal_and_new_reader_preserve_original_wal_frames() {
    let root = Root::new("restart");
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    assert!(matches!(
        Wal::new(&root.0, 1024 * 1024),
        Err(Error::Conflict)
    ));
    wal.create_segment("history", CREATED).unwrap();
    assert_eq!(wal.append(&bundle().to_string()).unwrap(), 0);
    assert_eq!(wal.append(&bundle().to_string()).unwrap(), 1);
    let segment = wal.seal(CREATED).unwrap();
    assert_eq!(segment["record_count"], 2);
    assert_eq!(segment["canonical_count"], 0);
    let bytes = fs::read(root.0.join("history.sealed.wal")).unwrap();
    assert_eq!(&bytes[..5], b"OAMD\x01");
    assert!(!root.0.join("history.open.wal").exists());
    drop(wal);
    let mut reader = Wal::new(&root.0, 1024 * 1024).unwrap();
    assert_eq!(reader.load_segment("history").unwrap(), segment);
    assert_eq!(
        reader.read_sealed("history").unwrap(),
        vec![bundle(), bundle()]
    );
}
#[test]
fn recovery_quarantines_only_the_invalid_open_suffix() {
    use std::io::Write;
    let root = Root::new("torn");
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    wal.create_segment("history", CREATED).unwrap();
    wal.append(&bundle().to_string()).unwrap();
    drop(wal);
    let path = root.0.join("history.open.wal");
    fs::OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(b"OAMD\x01torn")
        .unwrap();
    let mut recovered = Wal::new(&root.0, 1024 * 1024).unwrap();
    let Recovery::Sealed {
        segment,
        quarantined_tail,
    } = recovered.recover_segment("history").unwrap()
    else {
        panic!("recorded history must remain sealed")
    };
    assert!(quarantined_tail);
    assert_eq!(segment["record_count"], 1);
    assert_eq!(
        fs::read(root.0.join("history.corrupt-tail")).unwrap(),
        b"OAMD\x01torn"
    );
    assert_eq!(recovered.read_sealed("history").unwrap(), vec![bundle()]);
}
#[test]
fn corruption_capacity_and_foreign_record_links_never_become_accepted() {
    let root = Root::new("invalid");
    let mut wal = Wal::new(&root.0, 128).unwrap();
    wal.create_segment("history", CREATED).unwrap();
    assert_eq!(wal.append(&bundle().to_string()), Err(Error::Capacity));
    assert_eq!(
        fs::metadata(root.0.join("history.open.wal")).unwrap().len(),
        0
    );
    assert!(wal.create_segment("../escape", CREATED).is_err());
    drop(wal);
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    // An incomplete prior open is not silently rebound to a new writer identity.
    assert!(wal.create_segment("history", CREATED).is_err());
    wal.create_segment("other", CREATED).unwrap();
    let mut invalid = bundle();
    invalid["evidence"]["raw_sha256"] = "a".repeat(64).into();
    assert_eq!(wal.append(&invalid.to_string()), Err(Error::Invalid));
    let mut invalid = bundle();
    invalid["evidence"]["payload_base64"] = "***".into();
    assert_eq!(wal.append(&invalid.to_string()), Err(Error::Invalid));
    let mut invalid = bundle();
    invalid["evidence"]["capture_session_id"] = true.into();
    assert_eq!(wal.append(&invalid.to_string()), Err(Error::Invalid));
    wal.append(&bundle().to_string()).unwrap();
    wal.seal(CREATED).unwrap();
    drop(wal);
    let path = root.0.join("other.sealed.wal");
    let mut bytes = fs::read(&path).unwrap();
    *bytes.last_mut().unwrap() ^= 1;
    fs::write(path, bytes).unwrap();
    let mut reader = Wal::new(&root.0, 1024 * 1024).unwrap();
    assert!(reader.load_segment("other").is_err());
    assert!(reader.recover_segment("other").is_err());
}
#[test]
fn creation_crashes_and_empty_segments_have_a_deterministic_recovery() {
    for stage in ["metadata", "file", "published"] {
        let root = Root::new(stage);
        let prepared =
            json!({"schema_version":1,"segment_id":"history","created_at":CREATED}).to_string();
        if stage == "published" {
            fs::write(root.0.join("history.open.json"), &prepared).unwrap();
        } else {
            fs::write(root.0.join("history.open.json.tmp"), &prepared).unwrap();
        }
        if stage != "metadata" {
            fs::write(root.0.join("history.open.wal"), b"").unwrap();
        }
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        assert!(
            wal.recover_segment("history").is_ok(),
            "normal creation crash: {stage}"
        );
        assert!(!root.0.join("history.open.wal").exists());
        assert!(!root.0.join("history.open.json.tmp").exists());
        assert!(!root.0.join("history.sealed.wal").exists());
        if stage != "metadata" {
            assert!(root.0.join("history.abandoned.wal").exists());
        }
    }
}
#[test]
fn prepared_recovery_never_overwrites_an_already_published_document() {
    let root = Root::new("published-conflict");
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    wal.create_segment("history", CREATED).unwrap();
    wal.append(&bundle().to_string()).unwrap();
    let metadata = wal.seal(CREATED).unwrap();
    drop(wal);
    fs::rename(
        root.0.join("history.sealed.wal"),
        root.0.join("history.open.wal"),
    )
    .unwrap();
    fs::write(
        root.0.join("history.open.json"),
        json!({"schema_version":1,"segment_id":"history","created_at":CREATED}).to_string(),
    )
    .unwrap();
    fs::write(
        root.0.join("history.segment.json.tmp"),
        metadata.to_string(),
    )
    .unwrap();
    let published = b"an incompatible published document";
    fs::write(root.0.join("history.segment.json"), published).unwrap();
    let before = fs::read(root.0.join("history.open.wal")).unwrap();
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    assert!(wal.recover_segment("history").is_err());
    assert_eq!(
        fs::read(root.0.join("history.segment.json")).unwrap(),
        published
    );
    assert_eq!(fs::read(root.0.join("history.open.wal")).unwrap(), before);
}
#[test]
fn original_python_bar_history_and_missing_recovery_fields_are_read_without_rewrite() {
    let root = Root::new("python-history");
    historical_fixture(&root);
    let metadata_path = root.0.join("python-history.segment.json");
    let original = fs::read(&metadata_path).unwrap();
    let expected: Value =
        serde_json::from_slice(&fs::read(root.0.join("python-expected.json")).unwrap()).unwrap();
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    assert_eq!(wal.load_segment("python-history").unwrap(), expected);
    assert_eq!(fs::read(&metadata_path).unwrap(), original);
}
#[test]
fn canonical_fact_envelopes_match_their_exact_payload_even_with_a_valid_hash() {
    let root = Root::new("canonical-links");
    historical_fixture(&root);
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    let good: Value =
        serde_json::from_slice(&fs::read(root.0.join("python-bundle.json")).unwrap()).unwrap();
    wal.create_segment("test-write", CREATED).unwrap();
    for key in [
        "source_id",
        "update_id",
        "instrument_id",
        "data_type",
        "ts_event",
    ] {
        let mut invalid = good.clone();
        invalid["canonical_facts"][0]["canonical_payload"][key] = if key == "ts_event" {
            1.into()
        } else {
            "different".into()
        };
        let payload = &invalid["canonical_facts"][0]["canonical_payload"];
        invalid["canonical_facts"][0]["canonical_payload_hash"] =
            onlyalpha_metadata_json::fingerprint(&payload.to_string(), 1_000_000)
                .unwrap()
                .into();
        assert!(
            wal.append(&invalid.to_string()).is_err(),
            "hash-correct wrong relation: {key}"
        );
    }
    for timestamp in [json!(1), json!("1"), json!(1.0), json!(true), Value::Null] {
        let mut invalid = good.clone();
        invalid["canonical_facts"][0]["ts_event_ns"] = timestamp.clone();
        invalid["canonical_facts"][0]["canonical_payload"]["ts_event"] = timestamp;
        let payload = &invalid["canonical_facts"][0]["canonical_payload"];
        invalid["canonical_facts"][0]["canonical_payload_hash"] =
            onlyalpha_metadata_json::fingerprint(&payload.to_string(), 1_000_000)
                .unwrap()
                .into();
        assert_eq!(wal.append(&invalid.to_string()), Err(Error::Invalid));
    }
    let mut invalid = good.clone();
    invalid["canonical_facts"][0]["data_kind"] = "TRADE".into();
    assert!(wal.append(&invalid.to_string()).is_err());
    wal.append(&good.to_string()).unwrap();
    let result = wal.seal("2026-10-22T03:00:00+00:00").unwrap();
    assert_eq!(result["canonical_count"], 1);
    let reference: Value =
        serde_json::from_str(include_str!("fixtures/market_wal_history.json")).unwrap();
    use base64::{Engine, engine::general_purpose::STANDARD};
    assert_eq!(
        fs::read(root.0.join("test-write.sealed.wal")).unwrap(),
        STANDARD
            .decode(reference["native_wal_base64"].as_str().unwrap())
            .unwrap()
    );
    assert_eq!(
        result,
        serde_json::from_str::<Value>(reference["native_metadata_json"].as_str().unwrap()).unwrap()
    );
    assert_eq!(
        fs::read(root.0.join("test-write.segment.json")).unwrap(),
        reference["native_metadata_json"]
            .as_str()
            .unwrap()
            .as_bytes()
    );
}
#[test]
fn incomplete_raw_evidence_is_rejected_without_panicking_or_writing() {
    let root = Root::new("missing-fields");
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    wal.create_segment("history", CREATED).unwrap();
    for key in [
        "raw_event_id",
        "payload_base64",
        "raw_sha256",
        "ts_receive_ns",
        "provider_schema",
    ] {
        let mut missing = bundle();
        missing["evidence"].as_object_mut().unwrap().remove(key);
        assert_eq!(
            wal.append(&missing.to_string()),
            Err(Error::Invalid),
            "missing {key}"
        );
    }
    assert_eq!(
        fs::metadata(root.0.join("history.open.wal")).unwrap().len(),
        0
    );
}

fn historical_fixture(root: &Root) {
    let data: Value =
        serde_json::from_str(include_str!("fixtures/market_wal_history.json")).unwrap();
    use base64::{Engine, engine::general_purpose::STANDARD};
    fs::write(
        root.0.join("python-history.sealed.wal"),
        STANDARD
            .decode(data["sealed_wal_base64"].as_str().unwrap())
            .unwrap(),
    )
    .unwrap();
    fs::write(
        root.0.join("python-history.segment.json"),
        data["legacy_metadata_json"].as_str().unwrap(),
    )
    .unwrap();
    fs::write(
        root.0.join("python-expected.json"),
        data["original_metadata_json"].as_str().unwrap(),
    )
    .unwrap();
    fs::write(
        root.0.join("python-bundle.json"),
        data["native_bundle_json"].as_str().unwrap(),
    )
    .unwrap();
}

#[test]
fn extra_formal_provenance_is_not_an_ignorable_metadata_annotation() {
    for key in ["integration_binding_fingerprint", "bar_construction"] {
        let root = Root::new(key);
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        wal.create_segment("history", CREATED).unwrap();
        wal.append(&bundle().to_string()).unwrap();
        let mut metadata = wal.seal(CREATED).unwrap();
        metadata[key] = if key == "integration_binding_fingerprint" {
            "e".repeat(64).into()
        } else {
            json!({"schema_version":2,"fingerprint":"e".repeat(64)})
        };
        let bytes = metadata.to_string().into_bytes();
        let path = root.0.join("history.segment.json");
        fs::write(&path, &bytes).unwrap();
        assert!(wal.load_segment("history").is_err(), "extra formal {key}");
        assert_eq!(fs::read(path).unwrap(), bytes);
    }
}
#[test]
fn prepared_seal_recovery_keeps_the_original_bytes_and_observed_seal_time() {
    for stage in ["prepared", "renamed"] {
        let root = Root::new(stage);
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        wal.create_segment("history", CREATED).unwrap();
        wal.append(&bundle().to_string()).unwrap();
        let original = wal.seal("2026-10-22T01:00:00+00:00").unwrap();
        drop(wal);
        let original_bytes = fs::read(root.0.join("history.sealed.wal")).unwrap();
        fs::rename(
            root.0.join("history.segment.json"),
            root.0.join("history.segment.json.tmp"),
        )
        .unwrap();
        fs::write(
            root.0.join("history.open.json"),
            json!({"schema_version":1,"segment_id":"history","created_at":CREATED}).to_string(),
        )
        .unwrap();
        if stage == "prepared" {
            fs::rename(
                root.0.join("history.sealed.wal"),
                root.0.join("history.open.wal"),
            )
            .unwrap();
        }
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        let Recovery::Sealed {
            segment,
            quarantined_tail,
        } = wal.recover_segment("history").unwrap()
        else {
            panic!("seal transition lost")
        };
        assert!(!quarantined_tail);
        assert_eq!(segment, original);
        assert_eq!(
            fs::read(root.0.join("history.sealed.wal")).unwrap(),
            original_bytes
        );
        assert!(!root.0.join("history.segment.json.tmp").exists());
    }
}

fn creation_metadata() -> String {
    json!({"schema_version":1,"segment_id":"history","created_at":CREATED}).to_string()
}
#[test]
fn published_creation_without_its_wal_is_corrupt_and_preserved() {
    for suffix in ["open.json", "abandoned.json"] {
        let root = Root::new(suffix);
        let path = root.0.join(format!("history.{suffix}"));
        let original = creation_metadata();
        fs::write(&path, &original).unwrap();
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        assert_eq!(wal.recover_segment("history"), Err(Error::Corrupt));
        assert_eq!(fs::read_to_string(path).unwrap(), original);
        assert!(!root.0.join("history.abandoned.wal").exists());
    }
}
#[test]
fn interrupted_abandonment_is_idempotent_at_each_durable_transition() {
    for stage in ["prepared", "open", "renamed", "published", "orphan"] {
        let root = Root::new(stage);
        if stage != "orphan" {
            fs::write(
                root.0.join(match stage {
                    "prepared" => "history.open.json.tmp",
                    "published" => "history.abandoned.json",
                    _ => "history.open.json",
                }),
                creation_metadata(),
            )
            .unwrap();
        }
        fs::write(
            root.0
                .join(if matches!(stage, "prepared" | "open" | "orphan") {
                    "history.open.wal"
                } else {
                    "history.abandoned.wal"
                }),
            b"",
        )
        .unwrap();
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        let first = wal.recover_segment("history").unwrap();
        assert_eq!(wal.recover_segment("history").unwrap(), first);
        assert!(!root.0.join("history.sealed.wal").exists());
        assert!(root.0.join("history.abandoned.wal").exists());
        assert!(wal.create_segment("history", CREATED).is_err());
    }
}
#[test]
fn first_torn_frame_is_preserved_and_abandoned_across_repeated_recovery() {
    for length in [1, 52, 54, 100] {
        let root = Root::new(&format!("first-torn-{length}"));
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        wal.create_segment("history", CREATED).unwrap();
        wal.append(&bundle().to_string()).unwrap();
        drop(wal);
        let path = root.0.join("history.open.wal");
        fs::OpenOptions::new()
            .write(true)
            .open(&path)
            .unwrap()
            .set_len(length)
            .unwrap();
        let torn = fs::read(&path).unwrap();
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        let recovered = wal
            .recover_segment("history")
            .expect("first torn frame must abandon");
        assert_eq!(
            recovered,
            Recovery::Abandoned {
                quarantined_tail: true,
                quarantined_creation: false,
            }
        );
        assert_eq!(wal.recover_segment("history").unwrap(), recovered);
        assert!(root.0.join("history.abandoned.wal").exists());
        assert_eq!(fs::read(root.0.join("history.corrupt-tail")).unwrap(), torn);
        assert!(!root.0.join("history.segment.json").exists());
    }
}
#[test]
fn partial_quarantine_write_resumes_only_from_the_exact_invalid_suffix() {
    use std::io::Write;
    for retained in [0, 1, 5, 9] {
        let root = Root::new(&format!("quarantine-{retained}"));
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        wal.create_segment("history", CREATED).unwrap();
        wal.append(&bundle().to_string()).unwrap();
        drop(wal);
        let tail = b"OAMD\x01torn";
        fs::OpenOptions::new()
            .append(true)
            .open(root.0.join("history.open.wal"))
            .unwrap()
            .write_all(tail)
            .unwrap();
        fs::write(root.0.join("history.corrupt-tail"), &tail[..retained]).unwrap();
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        assert!(
            wal.recover_segment("history").is_ok(),
            "partial quarantine {retained}"
        );
        assert_eq!(fs::read(root.0.join("history.corrupt-tail")).unwrap(), tail);
        assert_eq!(wal.read_sealed("history").unwrap(), vec![bundle()]);
    }
}
#[test]
fn conflicting_quarantine_never_truncates_original_wal() {
    let root = Root::new("quarantine-conflict");
    fs::write(root.0.join("history.open.json"), creation_metadata()).unwrap();
    fs::write(root.0.join("history.open.wal"), b"original-torn-frame").unwrap();
    fs::write(root.0.join("history.corrupt-tail"), b"different").unwrap();
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    assert_eq!(wal.recover_segment("history"), Err(Error::Conflict));
    assert_eq!(
        fs::read(root.0.join("history.open.wal")).unwrap(),
        b"original-torn-frame"
    );
    assert_eq!(
        fs::read(root.0.join("history.corrupt-tail")).unwrap(),
        b"different"
    );
}
#[test]
fn incomplete_seal_preparation_is_preserved_before_deterministic_reseal() {
    let partials: &[&[u8]] = &[
        b"",
        b"{",
        b"{\"schema_version\":",
        b"{\"annotation\":\"\xe4\xb8",
    ];
    for (index, partial) in partials.iter().enumerate() {
        let root = Root::new(&format!("partial-seal-{index}"));
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        wal.create_segment("history", CREATED).unwrap();
        wal.append(&bundle().to_string()).unwrap();
        drop(wal);
        let original = fs::read(root.0.join("history.open.wal")).unwrap();
        fs::write(root.0.join("history.segment.json.tmp"), partial).unwrap();
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        let recovered = wal
            .recover_segment("history")
            .expect("recover unpublished truncated JSON");
        assert_eq!(wal.recover_segment("history").unwrap(), recovered);
        assert_eq!(
            fs::read(root.0.join("history.sealed.wal")).unwrap(),
            original
        );
        assert_eq!(
            fs::read(root.0.join("history.segment.json.incomplete")).unwrap(),
            *partial
        );
        let metadata = wal.load_segment("history").unwrap();
        assert_eq!(metadata["sealed_at"], CREATED);
    }
}
#[test]
fn corrupt_or_already_sealed_preparation_is_never_discarded() {
    for (index, (prepared, sealed)) in [
        (b"{\"invalid\":true}".as_slice(), false),
        (b"{]".as_slice(), false),
        (b"{\"bad\":\"\xff".as_slice(), false),
        (b"{".as_slice(), true),
    ]
    .into_iter()
    .enumerate()
    {
        let root = Root::new(&format!("invalid-prepared-{index}"));
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        wal.create_segment("history", CREATED).unwrap();
        wal.append(&bundle().to_string()).unwrap();
        drop(wal);
        let name = if sealed {
            "history.sealed.wal"
        } else {
            "history.open.wal"
        };
        if sealed {
            fs::rename(root.0.join("history.open.wal"), root.0.join(name)).unwrap();
        }
        let original = fs::read(root.0.join(name)).unwrap();
        fs::write(root.0.join("history.segment.json.tmp"), prepared).unwrap();
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        assert!(wal.recover_segment("history").is_err());
        assert_eq!(fs::read(root.0.join(name)).unwrap(), original);
        assert_eq!(
            fs::read(root.0.join("history.segment.json.tmp")).unwrap(),
            prepared
        );
        assert!(!root.0.join("history.segment.json").exists());
    }
}

#[test]
fn recovery_preparation_can_resume_after_a_second_interrupted_write() {
    let root = Root::new("repeated-preparation");
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    wal.create_segment("history", CREATED).unwrap();
    wal.append(&bundle().to_string()).unwrap();
    let original = wal.seal(CREATED).unwrap();
    drop(wal);
    let metadata = fs::read(root.0.join("history.segment.json")).unwrap();
    fs::remove_file(root.0.join("history.segment.json")).unwrap();
    fs::rename(
        root.0.join("history.sealed.wal"),
        root.0.join("history.open.wal"),
    )
    .unwrap();
    fs::write(root.0.join("history.open.json"), creation_metadata()).unwrap();
    fs::write(
        root.0.join("history.segment.json.incomplete"),
        b"{\"original",
    )
    .unwrap();
    fs::write(
        root.0.join("history.segment.json.tmp"),
        &metadata[..metadata.len() / 2],
    )
    .unwrap();
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    assert!(wal.recover_segment("history").is_ok());
    assert_eq!(wal.load_segment("history").unwrap(), original);
    assert_eq!(
        fs::read(root.0.join("history.segment.json.incomplete")).unwrap(),
        b"{\"original"
    );
    assert_eq!(
        fs::read(root.0.join("history.segment.json")).unwrap(),
        metadata
    );
}

#[test]
fn whole_segment_context_cannot_mix_sources_capture_or_binding() {
    for key in [
        "source_id",
        "capture_session_id",
        "provider",
        "venue",
        "market",
        "stream",
        "provider_schema",
        "payload_codec",
        "provenance",
        "integration_binding_fingerprint",
    ] {
        let root = Root::new(&format!("context-{key}"));
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        wal.create_segment("history", CREATED).unwrap();
        wal.append(&bundle().to_string()).unwrap();
        let mut foreign = bundle();
        foreign["evidence"][key] = match key {
            "integration_binding_fingerprint" => "a".repeat(64).into(),
            "provenance" => "REPLAY".into(),
            _ => "foreign".into(),
        };
        wal.append(&foreign.to_string()).unwrap();
        let original = fs::read(root.0.join("history.open.wal")).unwrap();
        assert_eq!(wal.seal(CREATED), Err(Error::Corrupt), "mixed {key}");
        drop(wal);
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        assert!(wal.recover_segment("history").is_err());
        assert_eq!(fs::read(root.0.join("history.open.wal")).unwrap(), original);
        assert!(!root.0.join("history.segment.json").exists());
    }
}

#[test]
fn complete_prepared_metadata_must_match_every_formal_field() {
    for key in [
        "segment_id",
        "source_id",
        "capture_session_id",
        "content_hash",
        "record_count",
        "integration_binding_fingerprint",
    ] {
        let root = Root::new(&format!("prepared-field-{key}"));
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        wal.create_segment("history", CREATED).unwrap();
        wal.append(&bundle().to_string()).unwrap();
        let mut metadata = wal.seal(CREATED).unwrap();
        drop(wal);
        metadata[key] = if key == "record_count" {
            99.into()
        } else {
            "e".repeat(64).into()
        };
        fs::remove_file(root.0.join("history.segment.json")).unwrap();
        fs::rename(
            root.0.join("history.sealed.wal"),
            root.0.join("history.open.wal"),
        )
        .unwrap();
        fs::write(root.0.join("history.open.json"), creation_metadata()).unwrap();
        let prepared = metadata.to_string();
        fs::write(root.0.join("history.segment.json.tmp"), &prepared).unwrap();
        let original = fs::read(root.0.join("history.open.wal")).unwrap();
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        assert!(wal.recover_segment("history").is_err(), "prepared {key}");
        assert_eq!(fs::read(root.0.join("history.open.wal")).unwrap(), original);
        assert_eq!(
            fs::read_to_string(root.0.join("history.segment.json.tmp")).unwrap(),
            prepared
        );
    }
}

#[test]
fn missing_or_null_optional_provenance_and_unknown_annotations_preserve_bytes() {
    let root = Root::new("nullable-history");
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    wal.create_segment("history", CREATED).unwrap();
    wal.append(&bundle().to_string()).unwrap();
    let expected = wal.seal(CREATED).unwrap();
    let mut metadata = expected.clone();
    metadata["integration_binding_fingerprint"] = Value::Null;
    metadata["bar_construction"] = Value::Null;
    metadata["historical_annotation"] = "kept verbatim".into();
    let bytes = metadata.to_string();
    fs::write(root.0.join("history.segment.json"), &bytes).unwrap();
    assert_eq!(wal.load_segment("history").unwrap(), expected);
    assert_eq!(
        fs::read_to_string(root.0.join("history.segment.json")).unwrap(),
        bytes
    );
}

fn snapshot(root: &Root) -> std::collections::BTreeMap<String, Vec<u8>> {
    fs::read_dir(&root.0)
        .unwrap()
        .map(|entry| {
            let path = entry.unwrap().path();
            (
                path.file_name().unwrap().to_str().unwrap().to_owned(),
                fs::read(path).unwrap(),
            )
        })
        .filter(|(name, _)| name != ".writer.lock")
        .collect()
}

#[test]
fn mutually_exclusive_wal_states_fail_before_any_file_mutation() {
    let cases: &[(&str, &[&str])] = &[
        ("open-sealed", &["open.wal", "open.json", "sealed.wal"]),
        ("open-published", &["open.wal", "open.json", "segment.json"]),
        (
            "open-abandoned-wal",
            &["open.wal", "open.json", "abandoned.wal"],
        ),
        (
            "open-abandoned-json",
            &["open.wal", "open.json", "abandoned.json"],
        ),
        (
            "sealed-abandoned-wal",
            &["sealed.wal", "segment.json", "abandoned.wal"],
        ),
        (
            "sealed-abandoned-json",
            &["sealed.wal", "segment.json", "abandoned.json"],
        ),
        (
            "prepared-abandoned",
            &["sealed.wal", "segment.json.tmp", "abandoned.wal"],
        ),
        (
            "duplicate-creation",
            &["open.wal", "open.json", "open.json.tmp"],
        ),
        (
            "creation-after-seal",
            &["sealed.wal", "segment.json", "open.json.tmp"],
        ),
        (
            "creation-with-seal-prepared",
            &["open.wal", "segment.json.tmp", "open.json.tmp"],
        ),
        (
            "duplicate-seal",
            &["sealed.wal", "segment.json", "segment.json.tmp"],
        ),
        (
            "duplicate-abandonment",
            &["abandoned.wal", "abandoned.json", "open.json"],
        ),
        (
            "duplicate-prepared-abandonment",
            &["abandoned.wal", "abandoned.json", "open.json.tmp"],
        ),
        ("open-gc", &["open.wal", "open.json", "gc.wal"]),
        ("sealed-gc", &["sealed.wal", "segment.json", "gc.json"]),
    ];
    for (label, suffixes) in cases {
        let root = Root::new(label);
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        wal.create_segment("history", CREATED).unwrap();
        wal.append(&bundle().to_string()).unwrap();
        let metadata = wal.seal(CREATED).unwrap().to_string();
        drop(wal);
        let frame = fs::read(root.0.join("history.sealed.wal")).unwrap();
        fs::remove_file(root.0.join("history.sealed.wal")).unwrap();
        fs::remove_file(root.0.join("history.segment.json")).unwrap();
        for suffix in *suffixes {
            let bytes = match *suffix {
                "open.wal" | "sealed.wal" => frame.clone(),
                "segment.json" | "segment.json.tmp" => metadata.as_bytes().to_vec(),
                "open.json" | "open.json.tmp" | "abandoned.json" => {
                    creation_metadata().into_bytes()
                }
                _ => Vec::new(),
            };
            fs::write(root.0.join(format!("history.{suffix}")), bytes).unwrap();
        }
        let before = snapshot(&root);
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        assert!(
            wal.recover_segment("history").is_err(),
            "recovery accepted {label}"
        );
        assert_eq!(snapshot(&root), before, "recovery changed {label}");
        assert!(
            wal.load_segment("history").is_err(),
            "reader accepted {label}"
        );
        assert_eq!(snapshot(&root), before, "reader changed {label}");
    }
}

#[test]
fn orphan_abandonment_marker_resumes_only_its_exact_deterministic_prefix() {
    let marker =
        b"{\"reason\":\"CREATION_ORPHAN\",\"schema_version\":1,\"segment_id\":\"history\"}";
    for retained in [0, 1, 20, marker.len() - 1] {
        let root = Root::new(&format!("orphan-marker-{retained}"));
        fs::write(root.0.join("history.abandoned.wal"), b"").unwrap();
        fs::write(root.0.join("history.abandoned.json"), &marker[..retained]).unwrap();
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        assert_eq!(
            wal.recover_segment("history"),
            Ok(Recovery::Abandoned {
                quarantined_tail: false,
                quarantined_creation: false
            })
        );
        assert_eq!(
            fs::read(root.0.join("history.abandoned.json")).unwrap(),
            marker
        );
        assert_eq!(
            wal.recover_segment("history"),
            Ok(Recovery::Abandoned {
                quarantined_tail: false,
                quarantined_creation: false
            })
        );
    }
    let root = Root::new("orphan-marker-conflict");
    fs::write(root.0.join("history.abandoned.wal"), b"").unwrap();
    fs::write(root.0.join("history.abandoned.json"), b"{\"created_at\":").unwrap();
    let before = snapshot(&root);
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    assert!(wal.recover_segment("history").is_err());
    assert_eq!(snapshot(&root), before);
}

#[test]
fn incomplete_creation_is_preserved_and_abandoned_without_inventing_time() {
    let prefixes: &[&[u8]] = &[
        b"",
        b"{",
        b"{\"created_at\":\"2026",
        b"{\"annotation\":\"\xe4\xb8",
    ];
    for (index, prefix) in prefixes.iter().enumerate() {
        for empty_wal in [false, true] {
            let root = Root::new(&format!("creation-prefix-{index}-{empty_wal}"));
            fs::write(root.0.join("history.open.json.tmp"), prefix).unwrap();
            if empty_wal {
                fs::write(root.0.join("history.open.wal"), b"").unwrap();
            }
            let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
            let outcome = wal
                .recover_segment("history")
                .expect("incomplete unaccepted creation must abandon");
            assert_eq!(
                outcome,
                Recovery::Abandoned {
                    quarantined_tail: false,
                    quarantined_creation: true
                }
            );
            assert_eq!(wal.recover_segment("history").unwrap(), outcome);
            assert_eq!(
                fs::read(root.0.join("history.open.json.incomplete")).unwrap(),
                *prefix
            );
            assert!(root.0.join("history.abandoned.wal").exists());
            assert!(!root.0.join("history.segment.json").exists());
            let metadata: Value =
                serde_json::from_slice(&fs::read(root.0.join("history.abandoned.json")).unwrap())
                    .unwrap();
            assert!(metadata.get("created_at").is_none());
            assert!(wal.create_segment("history", CREATED).is_err());
        }
    }
}

#[test]
fn incomplete_creation_cannot_hide_nonempty_wal_or_repair_complete_malformed_metadata() {
    for (index, (metadata, data)) in [
        (b"{".as_slice(), b"unaccepted-nonempty-wal".as_slice()),
        (b"{}".as_slice(), b"".as_slice()),
        (b"{]".as_slice(), b"".as_slice()),
        (b"{\"bad\":\"\xff".as_slice(), b"".as_slice()),
    ]
    .into_iter()
    .enumerate()
    {
        let root = Root::new(&format!("invalid-creation-{index}"));
        fs::write(root.0.join("history.open.json.tmp"), metadata).unwrap();
        fs::write(root.0.join("history.open.wal"), data).unwrap();
        let before = snapshot(&root);
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        assert!(wal.recover_segment("history").is_err());
        assert_eq!(snapshot(&root), before);
    }
}

#[test]
fn retained_creation_metadata_is_the_exact_lineage_for_seal_recovery_and_load() {
    for stage in ["prepared-open", "prepared-sealed", "published"] {
        let root = Root::new(&format!("creation-lineage-{stage}"));
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        wal.create_segment("history", CREATED).unwrap();
        wal.append(&bundle().to_string()).unwrap();
        let mut metadata = wal.seal("2026-10-22T03:00:00+00:00").unwrap();
        drop(wal);
        metadata["created_at"] = "2026-10-22T01:00:00+00:00".into();
        fs::write(root.0.join("history.segment.json"), metadata.to_string()).unwrap();
        fs::write(root.0.join("history.open.json"), creation_metadata()).unwrap();
        if stage != "published" {
            fs::rename(
                root.0.join("history.segment.json"),
                root.0.join("history.segment.json.tmp"),
            )
            .unwrap();
        }
        if stage == "prepared-open" {
            fs::rename(
                root.0.join("history.sealed.wal"),
                root.0.join("history.open.wal"),
            )
            .unwrap();
        }
        let before = snapshot(&root);
        let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
        assert_eq!(
            wal.recover_segment("history"),
            Err(Error::Corrupt),
            "changed creation {stage}"
        );
        assert_eq!(snapshot(&root), before);
        assert!(wal.load_segment("history").is_err());
        assert_eq!(snapshot(&root), before);
    }
    let root = Root::new("creation-lineage-utc");
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    wal.create_segment("history", CREATED).unwrap();
    wal.append(&bundle().to_string()).unwrap();
    let expected = wal.seal(CREATED).unwrap();
    fs::write(
        root.0.join("history.open.json"),
        creation_metadata().replace("+00:00", "Z"),
    )
    .unwrap();
    let before = snapshot(&root);
    assert_eq!(wal.load_segment("history").unwrap(), expected);
    assert_eq!(snapshot(&root), before);
}

#[test]
fn incomplete_creation_cannot_mutate_nonempty_abandoned_history() {
    let root = Root::new("nonempty-abandoned");
    fs::write(root.0.join("history.open.json.tmp"), b"{").unwrap();
    fs::write(root.0.join("history.abandoned.wal"), b"unproven-history").unwrap();
    let before = snapshot(&root);
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    assert_eq!(wal.recover_segment("history"), Err(Error::Corrupt));
    assert_eq!(snapshot(&root), before);
}

#[test]
fn sealed_descriptor_leaves_the_live_recorder_free_and_retains_single_owner() {
    let root = Root::new("sealed-handle");
    let mut wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    wal.create_segment("old", CREATED).unwrap();
    wal.append(&bundle().to_string()).unwrap();
    wal.seal(CREATED).unwrap();
    let mut sealed = wal.sealed_handle().unwrap();
    wal.create_segment("live", CREATED).unwrap();
    wal.append(&bundle().to_string()).unwrap();
    assert_eq!(sealed.published_sealed().unwrap(), vec!["old"]);
    assert_eq!(sealed.load_segment("old").unwrap()["record_count"], 1);
    assert!(sealed.load_segment("live").is_err());
    wal.append(&bundle().to_string()).unwrap();
    assert!(wal.recovery_pending().is_err());
    wal.seal(CREATED).unwrap();
    assert!(wal.recover_segment("old").is_err());
    drop(wal);
    assert!(matches!(
        Wal::new(&root.0, 1024 * 1024),
        Err(Error::Conflict)
    ));
    drop(sealed);
    let wal = Wal::new(&root.0, 1024 * 1024).unwrap();
    assert_eq!(wal.published_sealed().unwrap(), vec!["live", "old"]);
}
