use criterion::{BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use std::{hint::black_box, time::Duration};
const RAW: &str = include_str!("../../../test-data/backtest-benchmarks/large.json");
use onlyalpha_broker::BrokerCommand;
fn bench(c: &mut Criterion) {
    let v: serde_json::Value = serde_json::from_str(RAW).unwrap();
    let config = &v["execution"]["components"][0]["config"];
    let scope = serde_json::json!({"runtime_kind":"BACKTEST","engine":config["engine_id"],"runtime":config["runtime_id"],"account":"experimental-account","gateway":config["gateway_id"],"generation":config["generation"]});
    let mut request = v["execution"]["components"][0]["journal"][0]["request"].clone();
    request["account_id"] = serde_json::json!({"schema_version":1,"value":"experimental-account"});
    let raw = serde_json::json!({"schema_version":1,"scope":scope,"operation":"SUBMIT","command_id":"benchmark-command","order":"benchmark-order","client":"benchmark-client","request":request});
    black_box(BrokerCommand::decode(&raw).unwrap());
    let mut g = c.benchmark_group("command.decode");
    for n in [16u64, 128, 740] {
        println!(
            "BENCHMARK_RESULT {n} {}",
            BrokerCommand::decode(&raw).unwrap().record()
        );
        g.throughput(Throughput::Elements(n));
        g.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter(|| {
                for _ in 0..n {
                    black_box(BrokerCommand::decode(black_box(&raw)).unwrap());
                }
            })
        });
    }
    g.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench}
criterion_main!(benches);
