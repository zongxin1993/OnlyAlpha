//! 完成阶段读取剖析：量化回测封板时「整库读回原始回放日志」的分段成本。
//!
//! 读数字前必看的口径：
//! - 参与者只有 `onlyalpha-runtime` 的只读快照，不含策略、算子、产品准入与 PostgreSQL 侧证据装配。
//!   它对应 `TerminalSnapshot::read` 的第一步 `VerifiedReplaySnapshot::read` 与其后的逐步读取，
//!   即封板尾巴里与 Runtime 直接相关的部分。
//! - 输入是一次真实回放留下的 runtime 目录（含 records、checkpoints 与全部 replay_steps）。
//!   合成骨架没有账户交易记录，量不到 checkpoint 重放与记录解码的成本，因此本剖析不接受合成输入。
//! - 目录所在存储决定 I/O 份额：容器内 overlay 与宿主 bind mount（virtiofs）上的同一份数据
//!   必须分别测量后才可用于产品结论。
//! - 本剖析不设门禁、不落基线文件；数字只留在运行者上下文，不构成验收 Authority。
//!
//! 用法（容器内，工作目录为源码根）：
//! `OA_PROFILE_RUNTIME_ROOT=<runtime 目录> OA_PROFILE_IDENTITY=<该库 meta.payload 导出的 JSON>`
//! `cargo test --release --locked --offline -p onlyalpha-backtest --test completion_read_profile -- --ignored --nocapture`
//! 可选 `OA_PROFILE_ROUNDS`（默认 3 轮）。
use onlyalpha_runtime::VerifiedReplaySnapshot;
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::time::Instant;

/// 一次完整读取的三段成本：打开快照、逐条读回全部步、再校验一次读切面。
struct Round {
    open_ms: f64,
    steps_ms: f64,
    cut_ms: f64,
    stat_ms: f64,
    steps: usize,
}

#[test]
#[ignore = "需要一次真实回放保留的 runtime 目录与身份文件，见模块头口径说明"]
fn completion_read_profile() {
    let root = required("OA_PROFILE_RUNTIME_ROOT");
    let identity = identity_inputs(&required("OA_PROFILE_IDENTITY"));
    let configuration = identity["configuration"].clone();
    let artifact = identity["kernel_artifact"]
        .as_str()
        .expect("身份文件必须带 kernel_artifact")
        .to_owned();
    let rounds = std::env::var("OA_PROFILE_ROUNDS")
        .ok()
        .and_then(|raw| raw.parse::<usize>().ok())
        .filter(|count| *count > 0)
        .unwrap_or(3);
    let database = root.join("runtime.sqlite3");
    let bytes = std::fs::metadata(&database)
        .expect("runtime 库必须可读")
        .len();
    emit(
        json!({"kind":"config","root":root,"profile":profile(),"rounds":rounds,
        "database_bytes":bytes,"scope":"VerifiedReplaySnapshot 打开、逐条 read_step、再次 verify_cut；不含策略与产品准入"}),
    );
    let samples: Vec<Round> = (1..=rounds)
        .map(|round| measure(&root, &configuration, &artifact, &database, round))
        .collect();
    for (round, sample) in (1..=rounds).zip(&samples) {
        emit(json!({"kind":"sample","round":round,"steps":sample.steps,
            "open_ms":two(sample.open_ms),"steps_total_ms":two(sample.steps_ms),
            "per_step_ms":two(sample.steps_ms / sample.steps as f64),
            "verify_cut_ms":two(sample.cut_ms),"stat_probe_ms":two(sample.stat_ms)}));
    }
    let opens = median(samples.iter().map(|sample| sample.open_ms).collect());
    let steps = median(samples.iter().map(|sample| sample.steps_ms).collect());
    let cuts = median(samples.iter().map(|sample| sample.cut_ms).collect());
    let stats = median(samples.iter().map(|sample| sample.stat_ms).collect());
    let count = samples[0].steps;
    emit(
        json!({"kind":"summary","steps":count,"database_bytes":bytes,
        "median_open_ms":two(opens),"median_steps_total_ms":two(steps),
        "median_per_step_ms":two(steps / count as f64),"median_verify_cut_ms":two(cuts),
        "median_stat_probe_ms":two(stats),
        "open_share_of_open_plus_steps":two(opens / (opens + steps)),
        "stat_probe_per_step_ms":two(stats / count as f64),
        "note":"封板首次发布按代码路径要读两次 terminal：近似 2×(open+steps)，另加每次 verify_cut 一次整库读"}),
    );
}

/// 一轮测量：打开 → 逐条读回 → 再校验，另测同等次数的文件元数据与小读探针。
fn measure(
    root: &Path,
    configuration: &Value,
    artifact: &str,
    database: &Path,
    round: usize,
) -> Round {
    let started = Instant::now();
    let snapshot = VerifiedReplaySnapshot::read(root, configuration.clone(), artifact)
        .unwrap_or_else(|error| panic!("第 {round} 轮必须能打开只读快照: {error:?}"));
    let open_ms = elapsed(&started);
    let refs = snapshot.refs().to_vec();
    let started = Instant::now();
    let mut total = 0_u64;
    for reference in &refs {
        let step = snapshot.read_step(reference).unwrap_or_else(|error| {
            panic!("第 {round} 轮必须能读回步 {}: {error:?}", reference.index())
        });
        total += step.to_string().len() as u64;
    }
    let steps_ms = elapsed(&started);
    assert!(total > 0, "逐条读回必须产出非空步内容");
    let started = Instant::now();
    snapshot
        .verify_cut()
        .unwrap_or_else(|error| panic!("第 {round} 轮读切面校验必须通过: {error:?}"));
    let cut_ms = elapsed(&started);
    drop(snapshot);
    // 与 read_step 内 verify_file 同量级的最小探针：一次 stat 加一次 100 字节读。
    let started = Instant::now();
    for _ in 0..refs.len() {
        let metadata = std::fs::metadata(database).expect("元数据探测必须成功");
        assert!(metadata.len() > 0, "元数据探测必须看到非空库");
        let mut header = [0_u8; 100];
        let mut file = std::fs::File::open(database).expect("小读探测必须能打开库");
        std::io::Read::read_exact(&mut file, &mut header).expect("小读探测必须读到头部");
    }
    let stat_ms = elapsed(&started);
    Round {
        open_ms,
        steps_ms,
        cut_ms,
        stat_ms,
        steps: refs.len(),
    }
}

fn required(name: &str) -> PathBuf {
    let raw = std::env::var(name).unwrap_or_else(|_| panic!("缺少 {name}，见模块头口径说明"));
    let path = PathBuf::from(raw);
    assert!(
        path.is_dir() || path.is_file(),
        "{name} 指向的路径必须存在: {path:?}"
    );
    path
}

/// 身份文件就是该 runtime 库 meta.payload 的原文，含 configuration 与 kernel_artifact。
fn identity_inputs(path: &Path) -> Value {
    let text = std::fs::read_to_string(path).expect("身份文件必须可读");
    serde_json::from_str(&text).expect("身份文件必须是 JSON")
}

fn profile() -> &'static str {
    if cfg!(debug_assertions) {
        "dev"
    } else {
        "release"
    }
}

fn elapsed(started: &Instant) -> f64 {
    started.elapsed().as_secs_f64() * 1_000.0
}

fn median(mut values: Vec<f64>) -> f64 {
    values.sort_by(f64::total_cmp);
    let middle = values.len() / 2;
    if values.len() % 2 == 1 {
        values[middle]
    } else {
        (values[middle - 1] + values[middle]) / 2.0
    }
}

fn two(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}

fn emit(record: Value) {
    println!("{record}");
}
