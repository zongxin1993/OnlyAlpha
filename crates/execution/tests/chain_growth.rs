//! 账户交易链增长探针：量化提交与全链校验随交易笔数的增长形态。
//!
//! 默认忽略，显式执行：
//! `cargo test -p onlyalpha-execution --release --test chain_growth -- --ignored --exact --nocapture`
//! 链长覆盖：`OA_BENCH_CHAIN_SIZES=32,64,128`（单位：追加的估值事务条数）。
//! 放在 `tests/` 而不是 `benches/`，是因为 `scripts/rust_kernel_check.py` 只允许
//! `execution/tests/` 下的文件使用 `include_str!` 读取参考数据；本探针复用
//! `tests/support` 的夹具，不复制一份数据装配逻辑。
//!
//! 口径：
//! - 1 条账户交易 = `Store` 中一条 Ready `Record`（委托、成交、估值等），不是 1 根 K 线。
//! - `Components::reconcile` 每次遍历 `1..=sequence` 的全部账户交易，见
//!   `src/reconciliation.rs` 中 `verified_source_with_genesis` 的循环。
//! - `chain_replay_ms` 模拟回放主循环“每步追加后校验一次前缀”的累计成本；
//!   `chain_append_ms` 是只追加不校验的下界，两者之差即每步全链校验的净开销。
//! - `fixture_total_ms`、`prepare_total_ms`、`coordinate_total_ms` 拆分每步提交路径成本。
//! - 存储复用 `tests/support` 的内存 `MemoryStore`，用于隔离算法成本，
//!   不含 SQLite 写入与 fsync，因此绝对值低于真实回放。
//! 输出为 JSON 行，只用于同机同 profile 的相对比较，不构成质量门禁。

const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");

mod support;

use onlyalpha_execution::coordinate;
use serde_json::{Value, json};
use std::hint::black_box;
use std::time::Instant;
use support::{Harness, config, fill, input, open, stage};

type BenchError = Box<dyn std::error::Error>;

/// 交易链前缀：一笔委托进入 UNKNOWN 后部分成交，形成可持续估值的持仓。
fn seeded() -> Result<Harness, BenchError> {
    let mut harness = Harness::new(config())?;
    for value in [
        open(1, "BUY"),
        stage(2, 1, "UNKNOWN"),
        fill(3, 1, "4", "10.00", "1.00"),
    ] {
        commit(&mut harness, &value)?;
    }
    Ok(harness)
}

fn commit(harness: &mut Harness, value: &Value) -> Result<(), BenchError> {
    let prepared = harness.prepare(value)?;
    coordinate(&mut harness.store, &mut harness.components, &prepared)?;
    Ok(())
}

/// 逐笔估值事务：与 `tests/reconciliation.rs` 的估值夹具一致，可任意延长交易链。
fn valuation(harness: &Harness, n: u64) -> Result<Value, BenchError> {
    let state = harness.state()?;
    let evidence = onlyalpha_execution::digest(
        harness.checkpoint()?["components"][1]
            .to_string()
            .as_bytes(),
    );
    let mark = format!("{}.{:02}", 12 + n / 100, n % 100);
    Ok(input(
        n,
        "VALUATION",
        json!({"schema_version":1,"valuation":format!("valuation-{n}"),"version":n,
            "position_evidence":evidence,
            "economic_version":state["account"]["snapshot"]["economic_version"],
            "marks":[{"schema_version":1,"instrument":"600000.XSHG","mark":mark,
                "source_ref":format!("mark-{n}"),"family":"CLOSED_BAR","version":n,
                "time":n,"as_of_sequence":n}]}),
    ))
}

fn append(harness: &mut Harness, n: u64) -> Result<(), BenchError> {
    let value = valuation(harness, n)?;
    commit(harness, &value)
}

fn build(size: u64) -> Result<Harness, BenchError> {
    let mut harness = seeded()?;
    for n in 4..4 + size {
        append(&mut harness, n)?;
    }
    Ok(harness)
}

/// 只追加：交易链增长的线性下界。
fn chain_append_ms(size: u64) -> Result<(f64, u64), BenchError> {
    let started = Instant::now();
    let harness = build(size)?;
    Ok((
        started.elapsed().as_secs_f64() * 1_000.0,
        harness.store.rows.len() as u64,
    ))
}

/// 提交路径分段计时：夹具构造（读状态与证据）、prepare、coordinate 各自累计。
/// 三段之和应接近 `chain_append_ms`，明显缺口说明还有未归属的每步成本。
fn chain_split_ms(size: u64) -> Result<(f64, f64, f64), BenchError> {
    let mut harness = seeded()?;
    let (mut fixture_ms, mut prepare_ms, mut coordinate_ms) = (0.0, 0.0, 0.0);
    for n in 4..4 + size {
        let started = Instant::now();
        let value = valuation(&harness, n)?;
        fixture_ms += started.elapsed().as_secs_f64() * 1_000.0;
        let started = Instant::now();
        let prepared = harness.prepare(&value)?;
        prepare_ms += started.elapsed().as_secs_f64() * 1_000.0;
        let started = Instant::now();
        coordinate(&mut harness.store, &mut harness.components, &prepared)?;
        coordinate_ms += started.elapsed().as_secs_f64() * 1_000.0;
    }
    Ok((fixture_ms, prepare_ms, coordinate_ms))
}

/// 每步追加后立刻全链校验：对应回放主循环的实际形态。
fn chain_replay_ms(size: u64) -> Result<f64, BenchError> {
    let started = Instant::now();
    let mut harness = seeded()?;
    for n in 4..4 + size {
        append(&mut harness, n)?;
        black_box(harness.components.reconcile(&harness.store)?.record());
    }
    Ok(started.elapsed().as_secs_f64() * 1_000.0)
}

/// 链长固定时单次全链校验的成本，取 5 次中位数。
fn reconcile_once_us(size: u64) -> Result<(f64, u64), BenchError> {
    let harness = build(size)?;
    let records = harness.store.rows.len() as u64;
    let mut samples = Vec::new();
    for _ in 0..5 {
        let started = Instant::now();
        black_box(harness.components.reconcile(&harness.store)?.record());
        samples.push(started.elapsed().as_secs_f64() * 1_000_000.0);
    }
    samples.sort_by(|a, b| a.total_cmp(b));
    Ok((samples[samples.len() / 2], records))
}

fn sizes() -> Vec<u64> {
    match std::env::var("OA_BENCH_CHAIN_SIZES") {
        Ok(raw) if !raw.trim().is_empty() => raw
            .split(',')
            .filter_map(|item| item.trim().parse::<u64>().ok())
            .filter(|value| *value > 0)
            .collect(),
        _ => vec![16, 32, 64, 128, 256],
    }
}

fn round(value: f64) -> f64 {
    (value * 100.0).round() / 100.0
}

#[test]
#[ignore = "性能增长探针：显式使用 --ignored --nocapture 运行"]
fn chain_growth() -> Result<(), BenchError> {
    let profile = if cfg!(debug_assertions) {
        "debug"
    } else {
        "release"
    };
    println!(
        "{}",
        json!({"event":"inputs","profile":profile,"sizes":sizes(),
            "store":"MemoryStore（内存，不含 SQLite 与 fsync）",
            "unit":"chain_size = 追加的估值事务条数；交易链 = chain_size + 3 条前缀事务"})
    );
    let (mut previous_once, mut previous_append) = (None, None);
    for size in sizes() {
        let (append_ms, records) = chain_append_ms(size)?;
        let (fixture_ms, prepare_ms, coordinate_ms) = chain_split_ms(size)?;
        let (reconcile_us, _) = reconcile_once_us(size)?;
        let replay_ms = chain_replay_ms(size)?;
        // 若每步都全链校验，累计成本约为单次成本乘以 n/2，用于核对二次增长拟合。
        let quadratic_model_ms = reconcile_us * size as f64 / 2.0 / 1_000.0;
        println!(
            "{}",
            json!({"event":"sample","chain_size":size,"records":records,
                "reconcile_once_us":round(reconcile_us),
                "per_record_ns":(reconcile_us * 1_000.0 / records as f64).round(),
                "growth_ratio":previous_once.map(|p| round(reconcile_us / p)),
                "chain_append_ms":round(append_ms),
                "mean_append_us":(append_ms * 1_000.0 / size as f64).round(),
                "append_growth_ratio":previous_append.map(|p| round(append_ms / p)),
                "fixture_total_ms":round(fixture_ms),
                "prepare_total_ms":round(prepare_ms),
                "coordinate_total_ms":round(coordinate_ms),
                "coordinate_share":round(coordinate_ms / append_ms),
                "chain_replay_ms":round(replay_ms),
                "replay_over_append":round(replay_ms / append_ms),
                "quadratic_model_ms":round(quadratic_model_ms),
                "quadratic_excess_ms":round(replay_ms - append_ms)})
        );
        previous_once = Some(reconcile_us);
        previous_append = Some(append_ms);
    }
    Ok(())
}
