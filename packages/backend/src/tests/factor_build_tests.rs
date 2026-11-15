//! Real PG + sealed SDK compilation. No synthetic certifying owner or bool token.
use onlyalpha_backend::{
    application::{
        factor_build::{BuildStatus, FactorBuildService},
        private_assets::authoring::{API_FINGERPRINT, Draft},
    },
    bootstrap::deployment::SemanticStoreId,
};
use onlyalpha_calculation::program::{ProgramInput, ProgramInstance, ProgramValue, evaluate_batch};
use onlyalpha_calculation_bridge::ChartInstallation;
use serde_json::json;
use std::{collections::BTreeMap, path::PathBuf, sync::Arc};
const NS: &str = "99999999-9999-4999-8999-999999999999";
async fn installation() -> Arc<ChartInstallation> {
    static INSTALL: tokio::sync::OnceCell<(PathBuf, String)> = tokio::sync::OnceCell::const_new();
    let (path, sha) = INSTALL
        .get_or_init(|| async {
            let n = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos();
            let root = PathBuf::from(format!(
                "/workspace/test-results/factor-build-sdk-{}-{n}",
                std::process::id()
            ));
            let target = root.join("algorithms");
            let r = std::process::Command::new("python")
                .args(["/workspace/scripts/build_algorithm_sdk.py"])
                .arg(root.join("wheels"))
                .arg("--install")
                .arg(&target)
                .output()
                .unwrap();
            assert!(r.status.success(), "{}", String::from_utf8_lossy(&r.stderr));
            let sha = String::from_utf8(r.stdout).unwrap().trim().to_owned();
            (target, sha)
        })
        .await;
    Arc::new(ChartInstallation::open(path, sha).unwrap())
}
async fn source(c: &tokio_postgres::Client) -> (String, String) {
    source_default(c, 2).await
}
async fn source_default(c: &tokio_postgres::Client, default: i64) -> (String, String) {
    source_named(
        c,
        default,
        &format!("private.factor.native_build_test_{default}"),
    )
    .await
}
async fn source_named(c: &tokio_postgres::Client, default: i64, id: &str) -> (String, String) {
    let id = id.to_owned();
    let d=Draft::new(json!({"schema_version":1,"factor_id":id,"base_revision_fingerprint":null,"semantic_version":"1","source_text":"def calculate(api, inputs, parameters):\n    return {\"value\": api.rolling_mean(inputs[\"close\"], parameters[\"period\"])}\n","factor_api_version":1,"factor_api_contract_fingerprint":API_FINGERPRINT,"input_contract":{"close":{"type":"DECIMAL"}},"parameter_contract":{"period":{"type":"INTEGER","default":default,"required":false}},"output_contract":{"value":{"type":"DECIMAL"}},"description":"storage integration","economic_rationale":"controlled example","category":"price","tags":["test"]})).unwrap();
    let r = d.revision().unwrap();
    let rev = r["revision_fingerprint"].as_str().unwrap().to_owned();
    c.execute("INSERT INTO private_factor_asset(factor_id,schema_version) VALUES($1,1) ON CONFLICT DO NOTHING",&[&id]).await.unwrap();
    c.execute("INSERT INTO private_factor_revision(revision_fingerprint,factor_id,source_text,source_sha256,payload,schema_version) VALUES($1,$2,$3,$4,$5::text::jsonb,1) ON CONFLICT DO NOTHING",&[&rev,&id,&r["source_text"].as_str().unwrap(),&r["source_sha256"].as_str().unwrap(),&r.to_string()]).await.unwrap();
    (id, rev)
}
#[tokio::test]
async fn actual_build_once_exact_parameter_certificates_and_reload_have_no_source_execution() {
    let mut c = super::tests::database().await;
    let (id, revision) = source(&c.client).await;
    let installation = installation().await;
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await
        .unwrap();
    let ns = SemanticStoreId::new(NS).unwrap();
    let mut owner = FactorBuildService::new(&mut c.client, &ns, installation)
        .await
        .unwrap();
    assert!(
        owner
            .resolve_ready_binding(&id, &revision, &json!({}))
            .await
            .is_err()
    );
    let first = owner.request(&id, &revision, &json!({})).await.unwrap();
    assert!(matches!(first, BuildStatus::Building));
    let report = owner.run_pending().await.unwrap().unwrap();
    assert_eq!(report.source_parse_count, Some(1));
    assert!(matches!(report.status, BuildStatus::Ready));
    let a = owner
        .resolve_ready_binding(&id, &revision, &json!({}))
        .await
        .unwrap();
    let ap = a.program_fingerprint().to_owned();
    let ac = a.certificate_fingerprint().to_owned();
    assert!(matches!(
        owner
            .resolve_ready_binding(&id, &revision, &json!({"period":3}))
            .await,
        Err(onlyalpha_backend::application::factor_build::BuildError::NotReady)
    ));

    owner
        .request(&id, &revision, &json!({"period":3}))
        .await
        .unwrap();
    let report = owner.run_pending().await.unwrap().unwrap();
    assert_eq!(report.source_parse_count, Some(0));
    let b = owner
        .resolve_ready_binding(&id, &revision, &json!({"period":3}))
        .await
        .unwrap();
    assert_eq!(ap, b.program_fingerprint());
    assert_ne!(ac, b.certificate_fingerprint());
    let program = a.program();
    let input = |n, v: i64| {
        ProgramInput::new(
            "TEST",
            n,
            BTreeMap::from([("close".into(), ProgramValue::Decimal(v.into()))]),
        )
        .unwrap()
    };
    let rows = vec![input(0, 1i64), input(1, 3), input(2, 7)];
    let batch = evaluate_batch(program, &rows).unwrap();
    let mut event = ProgramInstance::new(Arc::new(program.clone()));
    for (i, r) in rows.iter().enumerate() {
        assert_eq!(event.step(r).unwrap(), batch[i]);
    }
    assert_eq!(batch[1]["value"].record(), json!("2.000000000000"));
    let again = owner
        .resolve_ready_binding(&id, &revision, &json!({"period":"2"}))
        .await
        .unwrap();
    assert_eq!(again.certificate_fingerprint(), ac);
}

#[tokio::test]
async fn failed_default_certification_retains_the_valid_program_for_new_parameters() {
    let mut c = super::tests::database().await;
    let (id, revision) = source_default(&c.client, 0).await;
    let installation = installation().await;
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await
        .unwrap();
    let ns = SemanticStoreId::new(NS).unwrap();
    let mut owner = FactorBuildService::new(&mut c.client, &ns, installation)
        .await
        .unwrap();
    let first = owner.run_pending().await.unwrap().unwrap();
    assert_eq!(first.revision, revision);
    assert_eq!(first.status, BuildStatus::Failed);
    assert!(
        owner
            .resolve_ready_binding(&id, &revision, &json!({}))
            .await
            .is_err()
    );
    owner
        .request(&id, &revision, &json!({"period":2}))
        .await
        .unwrap();
    let second = owner.run_pending().await.unwrap().unwrap();
    assert_eq!(second.status, BuildStatus::Ready);
    assert_eq!(
        second.source_parse_count,
        Some(0),
        "parameter certification failure cannot force rebuilding the same valid program"
    );
    assert!(
        owner
            .resolve_ready_binding(&id, &revision, &json!({"period":2}))
            .await
            .is_ok()
    );
}
#[tokio::test]
async fn background_owner_builds_the_durable_default_request_and_drains() {
    use onlyalpha_backend::workers::factor_build::{Service, Status};
    let admin = super::tests::database().await;
    let (id, revision) = source_default(&admin.client, 4).await;
    let installation = installation().await;
    let mut pg: tokio_postgres::Config = std::env::var("ONLYALPHA_POSTGRES_DSN")
        .unwrap()
        .parse()
        .unwrap();
    assert_eq!(pg.get_dbname(), Some("onlyalpha_dev_validation_test"));
    let prepared = std::process::Command::new("python")
        .args(["-m", "scripts.factor_build_database", "--test"])
        .current_dir("/workspace")
        .output()
        .unwrap();
    assert!(
        prepared.status.success(),
        "{}",
        String::from_utf8_lossy(&prepared.stderr)
    );
    pg.user("onlyalpha_factor_builder_test");
    let (client, driver) = pg.connect(tokio_postgres::NoTls).await.unwrap();
    let driver = tokio::spawn(driver);
    let mut service = Service::start(
        client,
        driver,
        SemanticStoreId::new(NS).unwrap(),
        installation.clone(),
    )
    .await
    .unwrap();
    let mut observed = service.subscribe();
    tokio::time::timeout(std::time::Duration::from_secs(20), async {
        loop {
            if let Status::Published { revision: done, .. } = observed.borrow().clone() {
                if done == revision {
                    break;
                }
            }
            observed.changed().await.unwrap();
        }
    })
    .await
    .unwrap();
    service.drain().await.unwrap();
    assert_eq!(*service.subscribe().borrow(), Status::Stopped);
    let mut other = super::tests::database().await;
    other.runtime().await;
    other
        .client
        .batch_execute("SET ROLE onlyalpha_job_reader")
        .await
        .unwrap();
    let mut read = FactorBuildService::new(
        &mut other.client,
        &SemanticStoreId::new(NS).unwrap(),
        installation,
    )
    .await
    .unwrap();
    assert!(
        read.resolve_ready_binding(&id, &revision, &json!({}))
            .await
            .is_ok()
    );
}

#[tokio::test]
async fn public_example_uses_the_same_revision_build_certificate_and_native_execution() {
    let mut c = super::tests::database().await;
    let root = PathBuf::from("/workspace/examples/private-assets/factor/simple_momentum");
    let asset: serde_json::Value =
        serde_json::from_slice(&std::fs::read(root.join("asset.json")).unwrap()).unwrap();
    let mut draft = asset["factor"].clone();
    draft["schema_version"] = json!(1);
    draft["base_revision_fingerprint"] = json!(null);
    draft["source_text"] = json!(std::fs::read_to_string(root.join("source.py")).unwrap());
    draft["factor_api_version"] = json!(1);
    draft["factor_api_contract_fingerprint"] = json!(API_FINGERPRINT);
    draft["description"] = asset["description"].clone();
    let revision = Draft::new(draft).unwrap().revision().unwrap();
    let id = revision["factor_id"].as_str().unwrap();
    let fingerprint = revision["revision_fingerprint"].as_str().unwrap();
    c.client
        .execute(
            "INSERT INTO private_factor_asset(factor_id,schema_version) VALUES($1,1)",
            &[&id],
        )
        .await
        .unwrap();
    c.client.execute("INSERT INTO private_factor_revision(revision_fingerprint,factor_id,source_text,source_sha256,payload,schema_version) VALUES($1,$2,$3,$4,$5::text::jsonb,1)",&[&fingerprint,&id,&revision["source_text"].as_str().unwrap(),&revision["source_sha256"].as_str().unwrap(),&revision.to_string()]).await.unwrap();
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await
        .unwrap();
    let ns = SemanticStoreId::new(NS).unwrap();
    let mut owner = FactorBuildService::new(&mut c.client, &ns, installation().await)
        .await
        .unwrap();
    let report = owner.run_pending().await.unwrap().unwrap();
    assert_eq!(report.status, BuildStatus::Ready);
    assert_eq!(report.source_parse_count, Some(1));
    let ready = owner
        .resolve_ready_binding(id, fingerprint, &json!({}))
        .await
        .unwrap();
    let mut event = ProgramInstance::new(Arc::new(ready.program().clone()));
    let rows = [100, 110, 99]
        .into_iter()
        .enumerate()
        .map(|(i, n)| {
            ProgramInput::new(
                "EXAMPLE",
                i as u64,
                BTreeMap::from([("close".into(), ProgramValue::Decimal(n.into()))]),
            )
            .unwrap()
        })
        .collect::<Vec<_>>();
    let batch = evaluate_batch(ready.program(), &rows).unwrap();
    for (i, row) in rows.iter().enumerate() {
        assert_eq!(batch[i], event.step(row).unwrap());
    }
    assert_eq!(batch[0]["value"], ProgramValue::Missing);
    assert_eq!(batch[1]["value"].record(), json!("0.100000000000"));
    assert_eq!(batch[2]["value"].record(), json!("-0.100000000000"));
}
#[tokio::test]
#[ignore = "explicit release-only real build/certification performance"]
async fn factor_build_performance_matrix() {
    let mut c = super::tests::database().await;
    let (id, rev) = source(&c.client).await;
    let sdk = installation().await;
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await
        .unwrap();
    let ns = SemanticStoreId::new(NS).unwrap();
    let mut owner = FactorBuildService::new(&mut c.client, &ns, sdk)
        .await
        .unwrap();
    for period in [2, 3, 64, 256] {
        let parameters = if period == 2 {
            json!({})
        } else {
            json!({"period":period})
        };
        let start = std::time::Instant::now();
        owner.request(&id, &rev, &parameters).await.unwrap();
        let request = start.elapsed();
        let start = std::time::Instant::now();
        let report = owner.run_pending().await.unwrap().unwrap();
        let build = start.elapsed();
        assert_eq!(report.status, BuildStatus::Ready);
        let start = std::time::Instant::now();
        let ready = owner
            .resolve_ready_binding(&id, &rev, &parameters)
            .await
            .unwrap();
        let read = start.elapsed();
        println!(
            "FACTOR_BUILD_BENCH {}",
            json!({"period":period,"request_us":request.as_micros(),"build_certify_publish_us":build.as_micros(),"read_decode_bind_us":read.as_micros(),"source_parse_count":report.source_parse_count,"program":ready.program_fingerprint(),"certificate":ready.certificate_fingerprint(),"vm_hwm":std::fs::read_to_string("/proc/self/status").unwrap().lines().find(|s|s.starts_with("VmHWM:")).unwrap_or("unknown")})
        );
    }
}

#[tokio::test]
async fn concurrent_versions_share_one_construction_but_have_exact_revision_certificates() {
    let mut a = super::tests::database().await;
    let mut b = super::tests::database().await;
    let (ida, ra) = source_named(&a.client, 5, "private.factor.concurrent_build_a").await;
    let (idb, rb) = source_named(&a.client, 5, "private.factor.concurrent_build_b").await;
    a.runtime().await;
    b.runtime().await;
    a.client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await
        .unwrap();
    b.client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await
        .unwrap();
    let sdk = installation().await;
    let ns = SemanticStoreId::new(NS).unwrap();
    let mut oa = FactorBuildService::new(&mut a.client, &ns, sdk.clone())
        .await
        .unwrap();
    let mut ob = FactorBuildService::new(&mut b.client, &ns, sdk)
        .await
        .unwrap();
    let (x, y) = tokio::join!(oa.run_pending(), ob.run_pending());
    let mut reports = [x.unwrap(), y.unwrap()]
        .into_iter()
        .flatten()
        .collect::<Vec<_>>();
    // The competing construction is now positively finished, so one observation
    // can consume its still-BUILDING request without polling or a sleep.
    if reports
        .iter()
        .filter(|r| r.status == BuildStatus::Ready)
        .count()
        < 2
    {
        reports.push(oa.run_pending().await.unwrap().unwrap());
    }
    assert_eq!(
        reports
            .iter()
            .filter(|r| r.status == BuildStatus::Ready)
            .count(),
        2
    );
    assert_eq!(
        reports
            .iter()
            .map(|r| r.source_parse_count.unwrap())
            .sum::<u64>(),
        1
    );
    let a = oa
        .resolve_ready_binding(&ida, &ra, &json!({}))
        .await
        .unwrap();
    let b = ob
        .resolve_ready_binding(&idb, &rb, &json!({}))
        .await
        .unwrap();
    assert_eq!(a.program_fingerprint(), b.program_fingerprint());
    assert_ne!(a.certificate_fingerprint(), b.certificate_fingerprint());
}

#[tokio::test]
async fn integer_source_is_ready_for_exact_parameters_and_rejects_fractional_input() {
    let mut c = super::tests::database().await;
    let id = "private.factor.integer_program";
    let draft=Draft::new(json!({"schema_version":1,"factor_id":id,"base_revision_fingerprint":null,"semantic_version":"1","source_text":"def calculate(api, inputs, parameters):\n    literal = 7\n    selected = api.where(api.gt(inputs[\"count\"], 0), parameters[\"offset\"], literal)\n    return {\"value\": selected, \"decimal_value\": selected}\n","factor_api_version":1,"factor_api_contract_fingerprint":API_FINGERPRINT,"input_contract":{"count":{"type":"INTEGER","nullable":true}},"parameter_contract":{"offset":{"type":"INTEGER","default":3}},"output_contract":{"value":{"type":"INTEGER","nullable":true},"decimal_value":{"type":"DECIMAL","nullable":true}},"description":"Integer contract","economic_rationale":"Controlled typed output","category":"test","tags":[]})).unwrap();
    let revision = draft.revision().unwrap();
    let rev = revision["revision_fingerprint"].as_str().unwrap();
    c.client
        .execute(
            "INSERT INTO private_factor_asset(factor_id,schema_version) VALUES($1,1)",
            &[&id],
        )
        .await
        .unwrap();
    c.client.execute("INSERT INTO private_factor_revision(revision_fingerprint,factor_id,source_text,source_sha256,payload,schema_version) VALUES($1,$2,$3,$4,$5::text::jsonb,1)",&[&rev,&id,&revision["source_text"].as_str().unwrap(),&revision["source_sha256"].as_str().unwrap(),&revision.to_string()]).await.unwrap();
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await
        .unwrap();
    let ns = SemanticStoreId::new(NS).unwrap();
    let mut owner = FactorBuildService::new(&mut c.client, &ns, installation().await)
        .await
        .unwrap();
    let report = owner.run_pending().await.unwrap().unwrap();
    assert_eq!(report.revision, rev);
    assert_eq!(report.status, BuildStatus::Ready);
    assert_eq!(report.source_parse_count, Some(1));
    let ready = owner
        .resolve_ready_binding(id, rev, &json!({}))
        .await
        .unwrap();
    assert_eq!(ready.program().program().output_types()["value"], "INTEGER");
    let row = |sequence, n: i64| {
        ProgramInput::new(
            "COUNT",
            sequence,
            BTreeMap::from([("count".into(), ProgramValue::Decimal(n.into()))]),
        )
        .unwrap()
    };
    let rows = [row(0, 1), row(1, -1)];
    let batch = evaluate_batch(ready.program(), &rows).unwrap();
    assert_eq!(batch[0]["value"].record(), json!(3));
    assert_eq!(batch[1]["value"].record(), json!(7));
    assert_eq!(batch[0]["decimal_value"].record(), json!("3.000000000000"));
    let mut state = ProgramInstance::new(Arc::new(ready.program().clone()));
    assert_eq!(state.step(&rows[0]).unwrap(), batch[0]);
    let before = state.capture();
    let bad = ProgramInput::new(
        "COUNT",
        1,
        BTreeMap::from([(
            "count".into(),
            ProgramValue::Decimal("1.5".parse().unwrap()),
        )]),
    )
    .unwrap();
    assert!(state.step(&bad).is_err());
    assert_eq!(state.capture(), before);
    let mut restored = ProgramInstance::new(Arc::new(ready.program().clone()));
    restored.restore(&before).unwrap();
    assert_eq!(restored.step(&rows[1]).unwrap(), batch[1]);
    owner.request(id, rev, &json!({"offset":4})).await.unwrap();
    let report = owner.run_pending().await.unwrap().unwrap();
    assert_eq!(report.status, BuildStatus::Ready);
    assert_eq!(report.source_parse_count, Some(0));
    let next = owner
        .resolve_ready_binding(id, rev, &json!({"offset":4}))
        .await
        .unwrap();
    assert_eq!(next.program_fingerprint(), ready.program_fingerprint());
    assert_ne!(
        next.certificate_fingerprint(),
        ready.certificate_fingerprint()
    );
}

#[tokio::test]
async fn fractional_output_cannot_borrow_an_integer_contract_to_get_ready() {
    let mut c = super::tests::database().await;
    let id = "private.factor.fractional_output";
    let draft=Draft::new(json!({"schema_version":1,"factor_id":id,"base_revision_fingerprint":null,"semantic_version":"1","source_text":"def calculate(api, inputs, parameters):\n    return {\"value\": api.decimal(\"1.5\")}\n","factor_api_version":1,"factor_api_contract_fingerprint":API_FINGERPRINT,"input_contract":{"count":{"type":"INTEGER"}},"parameter_contract":{},"output_contract":{"value":{"type":"INTEGER"}},"description":"Invalid integer output","economic_rationale":"Controlled rejection","category":"test","tags":[]})).unwrap();
    let revision = draft.revision().unwrap();
    let rev = revision["revision_fingerprint"].as_str().unwrap();
    c.client
        .execute(
            "INSERT INTO private_factor_asset(factor_id,schema_version) VALUES($1,1)",
            &[&id],
        )
        .await
        .unwrap();
    c.client.execute("INSERT INTO private_factor_revision(revision_fingerprint,factor_id,source_text,source_sha256,payload,schema_version) VALUES($1,$2,$3,$4,$5::text::jsonb,1)",&[&rev,&id,&revision["source_text"].as_str().unwrap(),&revision["source_sha256"].as_str().unwrap(),&revision.to_string()]).await.unwrap();
    c.runtime().await;
    c.client
        .batch_execute("SET ROLE onlyalpha_factor_builder")
        .await
        .unwrap();
    let ns = SemanticStoreId::new(NS).unwrap();
    let mut owner = FactorBuildService::new(&mut c.client, &ns, installation().await)
        .await
        .unwrap();
    let report = owner.run_pending().await.unwrap().unwrap();
    assert_eq!(report.revision, rev);
    assert_eq!(report.status, BuildStatus::Failed);
    assert!(matches!(
        owner.resolve_ready_binding(id, rev, &json!({})).await,
        Err(onlyalpha_backend::application::factor_build::BuildError::NotReady)
    ));
}
