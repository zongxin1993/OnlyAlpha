use criterion::{BatchSize, BenchmarkId, Criterion, Throughput, criterion_group, criterion_main};
use onlyalpha_calculation::{ExecutionBinding, ExecutionCursor};
use std::{hint::black_box, time::Duration};
fn bench(c: &mut Criterion) {
    let binding = ExecutionBinding::new(
        [
            "a".repeat(64),
            "b".repeat(64),
            "c".repeat(64),
            "d".repeat(64),
            "e".repeat(64),
            "f".repeat(64),
        ],
        "runtime/strategy/node",
    )
    .unwrap();
    let digest = "1".repeat(64);
    let mut g = c.benchmark_group("cursor.prepare_commit");
    for n in [1usize, 32, 256] {
        let times: Vec<_> = (1..=n).map(|n| n.to_string()).collect();
        let refs: Vec<_> = times.iter().map(String::as_str).collect();
        let mut check = ExecutionCursor::new(binding.clone());
        let p = check.prepare(&refs, &digest).unwrap();
        check
            .commit(&p, &binding, 1, &refs, n as u64, &digest)
            .unwrap();
        assert_eq!(check.revision(), 1);
        println!("BENCHMARK_RESULT {n} {}", check.capture());
        g.throughput(Throughput::Elements(n as u64));
        g.bench_function(BenchmarkId::from_parameter(n), |b| {
            b.iter_batched(
                || ExecutionCursor::new(binding.clone()),
                |mut cursor| {
                    let p = cursor.prepare(black_box(&refs), &digest).unwrap();
                    cursor
                        .commit(&p, &binding, 1, &refs, n as u64, &digest)
                        .unwrap();
                    black_box(cursor)
                },
                BatchSize::PerIteration,
            )
        });
    }
    g.finish();
}
criterion_group! {name=benches;config=Criterion::default().sample_size(10).warm_up_time(Duration::from_millis(200)).measurement_time(Duration::from_secs(1));targets=bench,program_bench,input_requirements_bench}
criterion_main!(benches);

fn input_requirements_bench(c: &mut Criterion) {
    let row = include_str!("../../../test-data/calculation/product-readers-v1.jsonl")
        .lines()
        .map(|line| serde_json::from_str::<serde_json::Value>(line).unwrap())
        .find(|row| row["case"] == "graph-basic")
        .unwrap();
    let graph =
        onlyalpha_calculation::product::Graph::from_record(&row["input"], 1024 * 1024).unwrap();
    assert_eq!(
        onlyalpha_calculation::finite_input::requirements(&graph, 8192)
            .unwrap()
            .history(),
        2
    );
    c.bench_function("finite_input.requirements/two_nodes", |b| {
        b.iter(|| {
            black_box(
                onlyalpha_calculation::finite_input::requirements(black_box(&graph), 8192).unwrap(),
            )
        })
    });
}

fn program_bench(c: &mut Criterion) {
    use onlyalpha_calculation::program::{
        Program, ProgramInput, ProgramInstance, ProgramValue, evaluate_batch,
    };
    use serde_json::json;
    use sha2::{Digest, Sha256};
    use std::{collections::BTreeMap, sync::Arc};
    let mut group = c.benchmark_group("factor_program");
    for period in [2usize, 64, 256] {
        let raw=json!({"schema_version":1,"numeric_policy":"DECIMAL28_HALF_EVEN_Q12_V1","inputs":{"close":{"type":"DECIMAL","role":"MARKET"}},"parameters":[],"nodes":[{"op":"input","name":"close"},{"op":"rolling_mean","args":[0],"period":period}],"outputs":{"value":1}}).to_string();
        let p = Program::decode(raw.as_bytes()).unwrap();
        let parameters = p.resolve_parameters(&json!({})).unwrap();
        let bound = Arc::new(p.bind(&parameters).unwrap());
        let rows = (0..1024)
            .map(|i| {
                ProgramInput::new(
                    "BENCH",
                    i,
                    BTreeMap::from([(
                        "close".into(),
                        if i < 512 && i % 97 == 0 {
                            ProgramValue::Missing
                        } else {
                            ProgramValue::Decimal((i as i64 % 31).into())
                        },
                    )]),
                )
                .unwrap()
            })
            .collect::<Vec<_>>();
        let batch = evaluate_batch(&bound, &rows).unwrap();
        assert!(
            batch
                .iter()
                .any(|row| matches!(row["value"], ProgramValue::Decimal(_))),
            "long-window benchmark must include actual numerical outputs"
        );
        let mut event = ProgramInstance::new(bound.clone());
        for (i, row) in rows.iter().enumerate() {
            assert_eq!(batch[i], event.step(row).unwrap());
        }
        let input_record = json!(
            rows.iter()
                .map(|r| r
                    .values()
                    .iter()
                    .map(|(k, v)| (k.clone(), v.record()))
                    .collect::<BTreeMap<_, _>>())
                .collect::<Vec<_>>()
        );
        let output_record = json!(
            batch
                .iter()
                .map(|r| r["value"].record())
                .collect::<Vec<_>>()
        );
        let hash = |v: &serde_json::Value| {
            Sha256::digest(v.to_string().as_bytes())
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        };
        println!(
            "PROGRAM_BENCH_IDENTITY {}",
            json!({"period":period,"program":p.fingerprint(),"rows":rows.len(),"program_bytes":raw.len(),"source_parse_count":0,"non_missing_outputs":batch.iter().filter(|r|!matches!(r["value"],ProgramValue::Missing)).count(),"inputs":hash(&input_record),"outputs":hash(&output_record)})
        );
        group.throughput(Throughput::Elements(1));
        group.bench_function(BenchmarkId::new("decode", period), |b| {
            b.iter(|| black_box(Program::decode(black_box(raw.as_bytes())).unwrap()))
        });
        group.bench_function(BenchmarkId::new("bind", period), |b| {
            b.iter(|| black_box(p.bind(black_box(&parameters)).unwrap()))
        });
        group.throughput(Throughput::Elements(rows.len() as u64));
        group.bench_function(BenchmarkId::new("batch", period), |b| {
            b.iter(|| black_box(evaluate_batch(&bound, black_box(&rows)).unwrap()))
        });
        group.bench_function(BenchmarkId::new("event", period), |b| {
            b.iter_batched(
                || ProgramInstance::new(bound.clone()),
                |mut state| {
                    for row in &rows {
                        black_box(state.step(black_box(row)).unwrap());
                    }
                },
                BatchSize::PerIteration,
            )
        });
        group.throughput(Throughput::Elements(4 * rows.len() as u64));
        group.bench_function(BenchmarkId::new("four_instances", period), |b| {
            b.iter_batched(
                || {
                    (0..4)
                        .map(|_| ProgramInstance::new(bound.clone()))
                        .collect::<Vec<_>>()
                },
                |mut states| {
                    for row in &rows {
                        for state in &mut states {
                            black_box(state.step(black_box(row)).unwrap());
                        }
                    }
                },
                BatchSize::PerIteration,
            )
        });
    }
    group.finish();
}
