//! Technical comparison/benchmark command, never a business Runtime entry point.
use onlyalpha_calculation_worker::{Client, Worker, WorkerError};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::{OnlyBar, OnlyBarType},
    time::{OnlyTimestamp, OnlyUtcDateTime},
};
use serde_json::{Value, json};
use std::{
    error::Error,
    path::Path,
    str::FromStr,
    time::{Duration, Instant},
};

const DEADLINE: Duration = Duration::from_secs(10);
fn data(base: &Value, count: usize) -> Result<Vec<OnlyBar>, Box<dyn Error>> {
    (0..count)
        .map(|index| {
            let mut row = base.clone();
            for key in ["open", "high", "low", "close"] {
                row[key]["value"] = json!(format!("{}.00", index + 1));
            }
            for key in ["bar_start", "bar_end", "ts_event", "ts_init"] {
                let time = OnlyUtcDateTime::from_str(base[key].as_str().ok_or("time")?)?;
                let nanos = OnlyTimestamp::from_datetime(time).to_unix_nanos()
                    + index as i64 * 60_000_000_000_i64;
                row[key] = json!(
                    OnlyTimestamp::from_unix_nanos(nanos)
                        .to_datetime_exact()?
                        .to_string()
                );
            }
            Ok(OnlyBar::from_record(&row)?)
        })
        .collect()
}
fn create(client: &mut Client, scope: &str, bar_type: &OnlyBarType) -> Result<(), Box<dyn Error>> {
    let resolution = client.resolve(json!({"period":3}), DEADLINE)?;
    client.create(
        scope,
        resolution,
        bar_type.clone(),
        &"c".repeat(64),
        DEADLINE,
    )?;
    Ok(())
}
fn main() -> Result<(), Box<dyn Error>> {
    let args: Vec<_> = std::env::args().collect();
    if args.len() != 4 {
        return Err("usage: calculation-bridge-check PYTHON EXPECTED_ARTIFACT FACT_VECTORS".into());
    }
    let python = Path::new(&args[1]);
    let artifact = args[2].clone();
    let generation = "a".repeat(64);
    let text = std::fs::read_to_string(&args[3])?;
    let base: Value = text
        .lines()
        .map(serde_json::from_str::<Value>)
        .collect::<Result<Vec<_>, _>>()?
        .into_iter()
        .find(|v| v["id"] == "bar")
        .ok_or("bar vector")?["record"]
        .clone();
    let bars = data(&base, 5)?;
    let bar_type = bars[0].bar_type();
    // Independent expected SMA3 values, not computed by either implementation under test.
    let mut client = Client::new(Worker::spawn(
        python,
        generation.clone(),
        artifact.clone(),
        DEADLINE,
    )?);
    create(&mut client, "runtime/cluster/first", bar_type)?;
    create(&mut client, "runtime/cluster/second", bar_type)?;
    let warmup = client.update("runtime/cluster/first", &bars[..2], DEADLINE)?;
    assert_eq!(
        warmup
            .iter()
            .map(|p| p["value"].clone())
            .collect::<Vec<_>>(),
        vec![json!("1.000000000000"), json!("1.500000000000")]
    );
    assert!(warmup.iter().all(|p| p["ready"] == false));
    let checkpoint = client.capture("runtime/cluster/first", DEADLINE)?;
    assert!(matches!(
        client.update("runtime/cluster/first", &bars[1..2], DEADLINE),
        Err(WorkerError::Invalid)
    ));
    assert_eq!(
        client
            .capture("runtime/cluster/first", DEADLINE)?
            .to_bytes(),
        checkpoint.to_bytes()
    );
    let expected = client.update("runtime/cluster/first", &bars[2..], DEADLINE)?;
    assert_eq!(
        expected
            .iter()
            .map(|p| p["value"].clone())
            .collect::<Vec<_>>(),
        vec![
            json!("2.000000000000"),
            json!("3.000000000000"),
            json!("4.000000000000")
        ]
    );
    assert!(expected.iter().all(|p| p["ready"] == true));
    assert_eq!(
        client.update("runtime/cluster/second", &bars[..1], DEADLINE)?[0]["samples"],
        1
    );
    drop(client); // Kills/reaps the actual first process. New process restores exact state.
    let mut restored = Client::new(Worker::spawn(
        python,
        generation.clone(),
        artifact.clone(),
        DEADLINE,
    )?);
    create(&mut restored, "runtime/cluster/first", bar_type)?;
    restored.restore("runtime/cluster/first", &checkpoint, DEADLINE)?;
    assert_eq!(
        restored.update("runtime/cluster/first", &bars[2..], DEADLINE)?,
        expected
    );
    restored.reset("runtime/cluster/first", DEADLINE)?;
    assert_eq!(
        restored.update("runtime/cluster/first", &bars[..1], DEADLINE)?[0]["samples"],
        1
    );
    restored.close("runtime/cluster/first", DEADLINE)?;
    assert!(restored.capture("runtime/cluster/first", DEADLINE).is_err());
    drop(restored);
    assert!(matches!(
        Worker::spawn(python, generation.clone(), "0".repeat(64), DEADLINE),
        Err(WorkerError::Unknown(_))
    ));
    let bars = data(&base, 2048)?;
    for size in [1, 64, 256] {
        let startup = Instant::now();
        let mut client = Client::new(Worker::spawn(
            python,
            generation.clone(),
            artifact.clone(),
            DEADLINE,
        )?);
        let startup_ms = startup.elapsed().as_secs_f64() * 1000.0;
        create(&mut client, "runtime/benchmark/sma", bar_type)?;
        let mut durations = Vec::new();
        let mut compute = Duration::ZERO;
        let total = Instant::now();
        for chunk in bars.chunks(size) {
            let start = Instant::now();
            client.update("runtime/benchmark/sma", chunk, DEADLINE)?;
            durations.push(start.elapsed().as_secs_f64() * 1000.0);
            compute += client.last_compute_time();
        }
        let total_ms = total.elapsed().as_secs_f64() * 1000.0;
        durations.sort_by(f64::total_cmp);
        println!(
            "{}",
            json!({"batch_size":size,"bars":bars.len(),"startup_ms":startup_ms,"total_ms":total_ms,"worker_backend_ms":compute.as_secs_f64()*1000.0,"batch_p50_ms":durations[durations.len()/2],"batch_p95_ms":durations[(durations.len()*95/100).min(durations.len()-1)]})
        );
        client.close("runtime/benchmark/sma", DEADLINE)?;
    }
    println!("REAL_SMA_BRIDGE_PASS");
    Ok(())
}
