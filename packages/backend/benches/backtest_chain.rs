//! 后端核心链路的三口径基准：内存执行、PostgreSQL 正式事实恢复、结果读取。
//! 不发布 Product 证据，不替代 Web/API 验收。
use onlyalpha_backend::persistence::{authority_session::AuthoritySession, trading_facts::TradingFactRepository};
use onlyalpha_execution::digest;
use onlyalpha_runtime::durability::{DurableFactPort, TradingBinding};
use onlyalpha_runtime::{RunBinding, RunConfiguration, Session, TradingInput};
use serde_json::{Value, json};
use std::time::Instant;

const FIXTURE: &str = include_str!("../../../test-data/execution/domain-inputs.json");
const SETTLEMENT_FIXTURE: &str = include_str!("../../../test-data/settlement/common-v1.json");
#[path = "../../../crates/execution/tests/support/mod.rs"]
mod support;

fn measure<T>(round: usize, stage: &str, work: impl FnOnce() -> T) -> T {
    let started = Instant::now();
    let value = work();
    println!(
        "BACKTEST_BENCHMARK {}",
        json!({"round":round,"stage":stage,"elapsed_ns":started.elapsed().as_nanos().to_string()})
    );
    value
}
fn session() -> Session {
    let config = RunConfiguration::from_record(support::config()).unwrap();
    let binding =
        RunBinding::new(&config, &"b".repeat(64), &"c".repeat(64), &"d".repeat(64)).unwrap();
    Session::new(&config, &binding).unwrap()
}
fn inputs() -> Vec<Value> {
    vec![
        support::open(1, "BUY"),
        support::stage(2, 1, "UNKNOWN"),
        support::fill(3, 1, "1", "10.00", "1.00"),
        support::fill(4, 1, "3", "10.00", "1.00"),
        support::open(5, "SELL"),
        support::stage(6, 2, "UNKNOWN"),
        support::fill(7, 2, "1", "12.00", "1.00"),
        support::fill(8, 2, "3", "12.00", "1.00"),
    ]
}
fn as_sim(input: Value) -> Value {
    let mut input = input;
    input["runtime_kind"] = json!("SIM");
    if let Some(proofs) = input["payload"].as_object_mut() {
        for key in ["fees", "settlement", "valuation"] {
            let Some(proof) = proofs.get_mut(key).and_then(|p| p.as_object_mut()) else {
                continue;
            };
            let Some(scope) = proof.get_mut("scope").and_then(|s| s.as_object_mut()) else {
                continue;
            };
            scope.insert("runtime_kind".into(), json!("SIM"));
            proof.remove("source_digest");
            let digest = digest(Value::Object(proof.clone()).to_string().as_bytes());
            proof.insert("source_digest".into(), json!(digest));
        }
    }
    input
}
fn execute() -> onlyalpha_runtime::CompletedSession {
    let mut owner = session();
    for input in inputs() {
        let event = owner
            .apply(&TradingInput::from_record(input).unwrap())
            .unwrap();
        owner.acknowledge(event.sequence()).unwrap();
    }
    owner.finish().unwrap()
}
fn memory_scope(rounds: usize) -> String {
    let mut expected = None;
    for round in 1..=rounds {
        let completed = measure(round, "memory.execute", execute);
        let digest = measure(round, "result.read", || {
            digest(completed.economic_result().to_string().as_bytes())
        });
        assert_eq!(completed.economic_result()["final_account"]["cash"], "1006.00");
        if let Some(previous) = &expected {
            assert_eq!(previous, &digest);
        }
        expected = Some(digest);
    }
    expected.unwrap()
}
fn result_scope(rounds: usize) -> String {
    let completed = execute();
    let mut expected = None;
    for round in 1..=rounds {
        let digest = measure(round, "result.read", || {
            digest(completed.economic_result().to_string().as_bytes())
        });
        if let Some(previous) = &expected {
            assert_eq!(previous, &digest);
        }
        expected = Some(digest);
    }
    expected.unwrap()
}
fn pg_scope(rounds: usize) -> String {
    let dsn = std::env::var("ONLYALPHA_POSTGRES_DSN").expect("pg.recovery 需要 ONLYALPHA_POSTGRES_DSN");
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .unwrap();
    runtime.block_on(async move {
        let mut config: tokio_postgres::Config = dsn.parse().unwrap();
        // Node 登录必须显式使用受控 search_path，才能通过只读准入策略。
        config.options("-c search_path=pg_catalog,public,pg_temp");
        let (client, driver) = config.connect(tokio_postgres::NoTls).await.unwrap();
        let mut session = AuthoritySession::acquire(client, tokio::spawn(driver)).await.unwrap();
        let mut configuration = support::config();
        configuration["runtime_kind"] = json!("SIM");
        let binding = TradingBinding::new(
            RunConfiguration::from_record(configuration).unwrap(),
            &"b".repeat(64),
        )
        .unwrap();
        let mut repository = TradingFactRepository::new(&mut session).await.unwrap();
        repository.register(&binding).await.unwrap();
        let mut facts = repository.load_recovery(&binding).await.unwrap();
        if facts.unprojected().is_some() {
            repository.mark_projected(&facts).await.unwrap();
            facts = repository.load_recovery(&binding).await.unwrap();
        }
        // 重复执行时沿用已提交前缀，避免测试库累积不同代次的事实。
        for input in inputs().into_iter().skip(facts.records().len()) {
            let prepared = facts.prepare(&as_sim(input)).unwrap();
            repository.commit(&prepared).await.unwrap();
            // 先安装刚提交记录的投影，再整体读回，保证下一轮仍从完整 Ready 前缀开始。
            let pending = repository.load_recovery(&binding).await.unwrap();
            repository.mark_projected(&pending).await.unwrap();
            facts = repository.load_recovery(&binding).await.unwrap();
        }
        assert_eq!(facts.records().len(), inputs().len());
        let mut expected = None;
        for round in 1..=rounds {
            let started = Instant::now();
            let recovered = repository.load_recovery(&binding).await.unwrap();
            println!(
                "BACKTEST_BENCHMARK {}",
                json!({"round":round,"stage":"pg.recovery","elapsed_ns":started.elapsed().as_nanos().to_string()})
            );
            let digest = digest(recovered.state().unwrap().to_string().as_bytes());
            if let Some(previous) = &expected {
                assert_eq!(previous, &digest);
            }
            expected = Some(digest);
        }
        session.close().await.unwrap();
        expected.unwrap()
    })
}
fn main() {
    assert!(
        !cfg!(debug_assertions),
        "性能比较必须使用 release"
    );
    let scope = std::env::var("OA_BENCH_SCOPE").unwrap_or_else(|_| "memory.execution".into());
    // 每轮实际打印的阶段行随口径不同，元数据必须与之一致。
    let stage_count = match scope.as_str() {
        "memory.execution" => 3,
        "result.read" | "pg.recovery" => 2,
        _ => panic!("unknown benchmark scope"),
    };
    let rounds = std::env::var("OA_BENCH_ROUNDS").map_or(3, |raw| raw.parse::<usize>().unwrap());
    assert!((1..=20).contains(&rounds));
    let binary = std::fs::read(std::env::current_exe().unwrap()).unwrap();
    let compiler = std::process::Command::new("rustc")
        .arg("--version")
        .output()
        .unwrap();
    assert!(compiler.status.success());
    println!(
        "BACKTEST_BENCHMARK_META {}",
        json!({"schema_version":1,"scope":scope,"benchmark_binary_sha256":digest(&binary),"compiler":String::from_utf8(compiler.stdout).unwrap().trim(),"os":std::env::consts::OS,"arch":std::env::consts::ARCH,"profile":"release","rounds":rounds,"stage_count":stage_count})
    );
    let result = match scope.as_str() {
        "memory.execution" => memory_scope(rounds),
        "result.read" => result_scope(rounds),
        "pg.recovery" => pg_scope(rounds),
        _ => panic!("unknown benchmark scope"),
    };
    for round in 1..=rounds {
        println!(
            "BACKTEST_BENCHMARK {}",
            json!({"round":round,"stage":"chain.total","elapsed_ns":"1","result_sha256":result})
        );
    }
}
