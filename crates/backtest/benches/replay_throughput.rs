//! `onlyalpha-backtest` 回放吞吐基准：给出回放骨架每步成本的基数与随输入长度的增长比。
//!
//! 读数字前必看的口径：
//! - 参与者是空实现计数桩（`BENCHMARK_SKELETON`），不含策略、算子、行情装配与产品准入。
//!   因此 `steps_per_s` 只覆盖输入身份与排序、事件推进、Runtime 绑定、轨迹与状态落盘，
//!   不等于产品端到端速度；产品端到端速度由 Web/OpenAPI 整体测试的分阶段计时另行证明。
//! - `profile` 取自编译期断言：`cargo bench` 使用 bench（继承 release）profile，
//!   `cargo bench --profile dev` 使用 dev profile。两者相差可达一个数量级，禁止混比。
//! - 本基准不设门禁、不落基线文件；测量数字留在运行者上下文，不构成验收 Authority。
//!
//! 用法：`cargo bench -p onlyalpha-backtest`；
//! 定向长度：`OA_BENCH_SIZES=250,500 cargo bench -p onlyalpha-backtest`。
//! `growth_ratio` 是相邻长度（每次翻倍）中位耗时的比值：2.0 表示线性，4.0 表示平方级。
//! `work_dir_bytes` 统计工作目录实际占用，含 SQLite 预分配页，只用于观察落盘量级，不是每条记录的净字节。

use onlyalpha_backtest::{
    Candidate, Error, Inputs, MarketInput, Participants, RunLoop, RunSpec, Source,
};
use onlyalpha_calculation_bridge::fingerprint;
use onlyalpha_domain::{base::OnlyDomainModel, market::OnlyBar};
use serde_json::{Value, json};
use std::path::{Path, PathBuf};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

/// 合成 Bar 的参考记录，与集成测试同源，保证走同一套领域校验。
const FACTS: &str = include_str!("../../../test-data/domain/fact-records-v1.jsonl");
const DATA_VERSION: &str = "benchmark-v1";
const SOURCE_ID: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
/// 单源长度与合成时间戳的上限：超出后会跨出参考月份，需要改成可进位的日历。
const MAX_BARS: u64 = 40_000;
/// 每个长度先跑一轮不计入样本，避免把磁盘与页缓存冷启动当成骨架成本。
const WARMUP_ROUNDS: usize = 1;
const SAMPLE_ROUNDS: usize = 3;

fn main() {
    let sizes = sizes();
    let reference = reference_bar();
    emit(json!({
        "kind": "config",
        "profile": profile(),
        "sizes": sizes,
        "sample_rounds": SAMPLE_ROUNDS,
        "warmup_rounds": WARMUP_ROUNDS,
        "participant": "BENCHMARK_SKELETON",
        "scope": "输入身份与排序、事件推进、Runtime 绑定、轨迹与状态落盘；不含策略与产品准入"
    }));
    let mut previous: Option<f64> = None;
    for size in &sizes {
        for _ in 0..WARMUP_ROUNDS {
            measure(*size, &reference, "warmup");
        }
        let samples: Vec<Sample> = (1..=SAMPLE_ROUNDS)
            .map(|round| measure(*size, &reference, &format!("r{round}")))
            .collect();
        for (round, sample) in (1..=SAMPLE_ROUNDS).zip(&samples) {
            emit(json!({
                "kind": "sample", "size": size, "round": round,
                "inputs_ms": two(sample.inputs_ms), "create_ms": two(sample.create_ms),
                "run_ms": two(sample.run_ms), "seal_ms": two(sample.seal_ms),
                "work_dir_bytes": sample.bytes
            }));
        }
        let run_ms = median(samples.iter().map(|sample| sample.run_ms).collect());
        let growth = previous.replace(run_ms).map(|prior| two(run_ms / prior));
        emit(json!({
            "kind": "summary",
            "size": size,
            "median_inputs_ms": two(median(samples.iter().map(|s| s.inputs_ms).collect())),
            "median_create_ms": two(median(samples.iter().map(|s| s.create_ms).collect())),
            "median_run_ms": two(run_ms),
            "median_seal_ms": two(median(samples.iter().map(|s| s.seal_ms).collect())),
            "median_total_ms": two(median(samples.iter().map(Sample::total_ms).collect())),
            "steps_per_s": two(f64::from(u32::try_from(*size).unwrap_or(u32::MAX)) * 1_000.0 / run_ms),
            "median_work_dir_bytes_per_step": two(median(
                samples.iter().map(|s| s.bytes as f64 / *size as f64).collect()
            )),
            "growth_ratio": growth,
            "read_growth_as": {"linear": 2.0, "quadratic": 4.0}
        }));
    }
}

/// 一次完整有限回放：建输入、创建可恢复工作、跑完输入、封板并读回结果。
fn measure(size: u64, reference: &Value, tag: &str) -> Sample {
    let root = work_root(size, tag);
    let _ = std::fs::remove_dir_all(&root);
    std::fs::create_dir_all(&root).expect("基准必须能创建临时工作目录");
    let started = Instant::now();
    let inputs = inputs(size, reference);
    let inputs_ms = elapsed(&started);
    let started = Instant::now();
    let mut run = RunLoop::create(
        &root,
        spec(&format!("benchmark-{size}-{tag}")),
        inputs,
        Skeleton { steps: 0 },
    )
    .expect("合成输入必须能被 RunLoop 接受");
    let create_ms = elapsed(&started);
    let started = Instant::now();
    run.run().expect("有限回放必须完成");
    let run_ms = elapsed(&started);
    let started = Instant::now();
    run.terminate("COMPLETED", None)
        .expect("输入耗尽后必须能封板");
    let result = run.result().expect("封板后必须能读回结果");
    let seal_ms = elapsed(&started);
    assert_eq!(
        result["market_exhausted"],
        json!(true),
        "基准必须真的消费完全部合成输入"
    );
    let bytes = directory_bytes(&root);
    std::fs::remove_dir_all(&root).expect("基准必须能清理临时工作目录");
    Sample {
        inputs_ms,
        create_ms,
        run_ms,
        seal_ms,
        bytes,
    }
}

struct Sample {
    inputs_ms: f64,
    create_ms: f64,
    run_ms: f64,
    seal_ms: f64,
    bytes: u64,
}

impl Sample {
    fn total_ms(&self) -> f64 {
        self.inputs_ms + self.create_ms + self.run_ms + self.seal_ms
    }
}

/// 只计数不交易的参与者，用来界定回放骨架自身成本。
struct Skeleton {
    steps: u64,
}

impl Participants for Skeleton {
    fn binding(&self) -> Value {
        json!({
            "schema_version": 1,
            "kind": "BENCHMARK_SKELETON",
            "configuration": fingerprint(configuration().to_string().as_bytes()),
            "generation": configuration()["generation"],
            "initial_ns": "0",
            "strategies": {"cluster": "revision"},
            "sources": [SOURCE_ID]
        })
    }
    fn capture(&mut self) -> Result<Value, Error> {
        Ok(json!({"steps": self.steps}))
    }
    fn restore(&mut self, value: &Value) -> Result<(), Error> {
        self.steps = value["steps"]
            .as_u64()
            .ok_or_else(|| Error("benchmark".into()))?;
        Ok(())
    }
    fn process(&mut self, input: &MarketInput, _: &mut Candidate) -> Result<Value, Error> {
        self.steps += 1;
        Ok(json!({"input": input.identity(), "steps": self.steps}))
    }
    fn quiescent(&self) -> Result<bool, Error> {
        Ok(true)
    }
}

fn inputs(size: u64, reference: &Value) -> Inputs {
    let source = Source::new(
        SOURCE_ID,
        &"b".repeat(64),
        &"c".repeat(64),
        DATA_VERSION,
        0,
        size,
    )
    .expect("合成 Source");
    let facts = (0..size)
        .map(|index| {
            MarketInput::new(source.id(), index + 1, DATA_VERSION, bar(reference, index))
                .expect("合成 MarketInput")
        })
        .collect();
    Inputs::new(vec![source], facts).expect("合成 Inputs")
}

fn bar(reference: &Value, index: u64) -> OnlyBar {
    let mut record = reference.clone();
    let (day, start) = stamp(index);
    let (_, end) = stamp(index + 1);
    record["bar_start"] = json!(start);
    record["bar_end"] = json!(end);
    record["ts_event"] = json!(end);
    record["ts_init"] = json!(end);
    record["trading_day"] = json!(day);
    let cents = 1_000 + index % 200;
    record["open"]["value"] = json!(money(cents));
    record["high"]["value"] = json!(money(cents + 7));
    record["low"]["value"] = json!(money(cents - 5));
    record["close"]["value"] = json!(money(cents + 3));
    record["volume"]["value"] = json!((100 + index).to_string());
    OnlyBar::from_record(&record).expect("合成 Bar 必须通过领域校验")
}

/// 合成 1 分钟 Bar 自 2025-01-06T00:00:00Z 起连续推进；返回日历日与该分钟的起点。
fn stamp(minute: u64) -> (String, String) {
    let day = 6 + minute / 1_440;
    let rest = minute % 1_440;
    (
        format!("2025-01-{day:02}"),
        format!("2025-01-{day:02}T{:02}:{:02}:00Z", rest / 60, rest % 60),
    )
}

fn money(cents: u64) -> String {
    format!("{}.{:02}", cents / 100, cents % 100)
}

fn configuration() -> Value {
    json!({"schema_version":1,"engine":"engine","runtime":"runtime","account":"account","gateway":"gateway","generation":"a".repeat(64),"runtime_kind":"BACKTEST","currency":{"schema_version":1,"code":"USD","precision":2,"currency_type":"FIAT"},"initial_cash":"1000.00","capitals":{"cluster":"1000.00"},"profiles":{"cluster":{"schema_version":1,"revision":"revision","instruments":["A.X"],"rules":[]}},"instruments":[{"schema_version":1,"id":"A.X","price_precision":2,"quantity_precision":0,"multiplier":"1"}]})
}

fn spec(work_id: &str) -> RunSpec {
    RunSpec {
        work_id: work_id.into(),
        configuration: configuration(),
        kernel_artifact: "e".repeat(64),
        driver_artifact: "f".repeat(64),
        initial_ns: 0.into(),
    }
}

fn reference_bar() -> Value {
    FACTS
        .lines()
        .filter_map(|line| serde_json::from_str::<Value>(line).ok())
        .find(|entry| entry["id"] == "bar")
        .expect("参考数据必须包含 OnlyBar 记录")["record"]
        .clone()
}

fn sizes() -> Vec<u64> {
    let configured = std::env::var("OA_BENCH_SIZES").unwrap_or_default();
    let sizes = if configured.trim().is_empty() {
        vec![60, 120, 240, 480]
    } else {
        configured
            .split(',')
            .filter_map(|value| value.trim().parse::<u64>().ok())
            .filter(|value| *value > 0)
            .collect()
    };
    assert!(
        !sizes.is_empty(),
        "OA_BENCH_SIZES 必须给出至少一个正整数长度"
    );
    assert!(
        *sizes.iter().max().unwrap_or(&0) <= MAX_BARS,
        "合成 Bar 长度上限为 {MAX_BARS}，再长需要改成可进位的日历"
    );
    sizes
}

fn work_root(size: u64, tag: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |value| value.subsec_nanos());
    std::env::temp_dir().join(format!(
        "oa-backtest-bench-{}-{size}-{tag}-{nonce}",
        std::process::id()
    ))
}

fn directory_bytes(root: &Path) -> u64 {
    let mut total = 0;
    let mut pending = vec![root.to_path_buf()];
    while let Some(directory) = pending.pop() {
        for entry in std::fs::read_dir(&directory).expect("基准必须能读取产物目录") {
            let path = entry.expect("基准必须能读取产物条目").path();
            let metadata = std::fs::symlink_metadata(&path).expect("基准必须能读取产物元数据");
            if metadata.is_dir() {
                pending.push(path);
            } else {
                total += metadata.len();
            }
        }
    }
    total
}

fn elapsed(started: &Instant) -> f64 {
    started.elapsed().as_secs_f64() * 1_000.0
}

fn median(mut values: Vec<f64>) -> f64 {
    values.sort_by(|left, right| left.partial_cmp(right).expect("耗时必须是有限数"));
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

fn profile() -> &'static str {
    if cfg!(debug_assertions) {
        "dev"
    } else {
        "release"
    }
}

fn emit(value: Value) {
    println!("{value}");
}
