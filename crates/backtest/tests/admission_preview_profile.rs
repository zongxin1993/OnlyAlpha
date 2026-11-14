//! 真实保留 checkpoint 的冷恢复/单次复用对照；不构成 Web 或交易准入验收。
use onlyalpha_execution::{AdmissionPreview, Components, digest};
use onlyalpha_runtime::VerifiedReplaySnapshot;
use serde_json::{Value, json};
use std::{path::Path, time::Instant};

fn rss_kib() -> Option<u64> {
    std::fs::read_to_string("/proc/self/status")
        .ok()?
        .lines()
        .find_map(|line| {
            line.strip_prefix("VmRSS:")?
                .split_whitespace()
                .next()?
                .parse()
                .ok()
        })
}

#[test]
#[ignore = "需要真实保留 runtime 和 meta 身份；见 Backtest README"]
fn retained_checkpoint_admission_preview_profile() {
    let root = std::env::var("OA_PROFILE_RUNTIME_ROOT").expect("需要 OA_PROFILE_RUNTIME_ROOT");
    let identity: Value = serde_json::from_str(
        &std::fs::read_to_string(
            std::env::var("OA_PROFILE_IDENTITY").expect("需要 OA_PROFILE_IDENTITY"),
        )
        .unwrap(),
    )
    .unwrap();
    let source = VerifiedReplaySnapshot::read(
        Path::new(&root),
        identity["configuration"].clone(),
        identity["kernel_artifact"].as_str().unwrap(),
    )
    .unwrap();
    let configuration = source.binding()["participants"]["policy"]["execution"].clone();
    let record = source
        .records()
        .last()
        .expect("需要非空真实执行记录")
        .prepared()
        .record();
    let components: Vec<_> = record["projections"]
        .as_array()
        .unwrap()
        .iter()
        .map(|row| row["result"].clone())
        .collect();
    let checkpoint = json!({"schema_version":1,"config":configuration,"sequence":source.records().len(),"pending":null,"components":components});
    let template = source
        .records()
        .iter()
        .find(|row| row.prepared().input()["op"] == "ADMIT")
        .expect("需要原始 ADMIT 样本")
        .prepared()
        .input()
        .clone();
    let sequence = checkpoint["components"][5]["last_runtime_sequence"]
        .as_u64()
        .unwrap()
        + 1;
    let inputs: Vec<_> = (0..67)
        .map(|index| {
            let mut input = template.clone();
            input["input_id"] = json!(format!("preview-profile-{index}"));
            input["source_ref"] = json!(format!("preview-profile-source-{index}"));
            input["runtime_sequence"] = json!(sequence);
            input
        })
        .collect();
    // 该探针在终态 checkpoint 上复算更新身份的原始命令；每个结果必须与冷入口一致。
    // 它测量恢复复用，不把生成的技术输入解释为当前有效交易意图。
    let result = |value: Result<Option<onlyalpha_execution::Error>, onlyalpha_execution::Error>| {
        value.map(|v| v.map(|e| e.0)).map_err(|e| e.0)
    };
    let warmup = Components::admission_rejection(&configuration, &checkpoint, &inputs[0]);
    let mut probe = AdmissionPreview::default();
    assert_eq!(
        result(probe.check(&configuration, &checkpoint, &inputs[0])),
        result(warmup)
    );
    drop(probe);
    let mut samples = Vec::new();
    for round in 1..=3 {
        let started = Instant::now();
        let cold: Vec<_> = inputs
            .iter()
            .map(|input| {
                result(Components::admission_rejection(
                    &configuration,
                    &checkpoint,
                    input,
                ))
            })
            .collect();
        let cold_ns = started.elapsed().as_nanos();
        let before_rss = rss_kib();
        let mut preview = AdmissionPreview::default();
        let started = Instant::now();
        let reused: Vec<_> = inputs
            .iter()
            .map(|input| result(preview.check(&configuration, &checkpoint, input)))
            .collect();
        let reused_ns = started.elapsed().as_nanos();
        let held_rss = rss_kib();
        assert_eq!(reused, cold, "每个新输入的复算结果必须等于完整冷入口");
        assert!(
            cold.iter().all(|r| r.is_err() || matches!(r, Ok(Some(_)))),
            "终态技术样本不得被当成可提交许可"
        );
        let outcomes: Vec<_> = cold
            .iter()
            .map(|v| format!("{v:?}"))
            .collect::<std::collections::BTreeSet<_>>()
            .into_iter()
            .collect();
        drop(preview);
        let row = json!({"round":round,"calls":inputs.len(),"cold_ns":cold_ns.to_string(),"reused_ns":reused_ns.to_string(),"rss_before_kib":before_rss,"rss_held_kib":held_rss,"rss_after_drop_kib":rss_kib(),"outcomes":outcomes});
        println!("ADMISSION_PREVIEW_PROFILE {row}");
        samples.push(row);
    }
    println!(
        "ADMISSION_PREVIEW_PROFILE_SUMMARY {}",
        json!({"profile":if cfg!(debug_assertions){"dev"}else{"release"},"checkpoint_bytes":checkpoint.to_string().len(),"checkpoint_sha256":digest(checkpoint.to_string().as_bytes()),"configuration_sha256":digest(configuration.to_string().as_bytes()),"kernel_artifact":identity["kernel_artifact"],"sequence":source.records().len(),"samples":samples})
    );
    source.verify_cut().unwrap();
}
