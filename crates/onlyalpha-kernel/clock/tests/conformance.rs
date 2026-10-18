use onlyalpha_clock::OnlyVirtualClock;
use std::sync::{Arc, Mutex};

#[test]
fn independent_common_vectors_preserve_exact_order_and_magnitude() {
    for line in include_str!("../../../../test-data/clock/timers-v1.tsv").lines() {
        if line.starts_with('#') {
            continue;
        }
        let fields: Vec<_> = line.split('\t').collect();
        let mut clock = OnlyVirtualClock::new(fields[1].parse().unwrap());
        let observed = Arc::new(Mutex::new(Vec::new()));
        for timer in fields[3].split(';') {
            let timer: Vec<_> = timer.split(',').collect();
            let output = observed.clone();
            let callback: onlyalpha_clock::VirtualCallback = Box::new(move |_, event| {
                output.lock().unwrap().push(format!(
                    "{},{},{},{}",
                    event.id, event.deadline_ns, event.sequence, event.fire_count
                ));
                Ok(())
            });
            if timer[1] == "ONCE" {
                clock
                    .schedule_at(timer[0], timer[2].parse().unwrap(), callback)
                    .unwrap();
            } else {
                clock
                    .schedule_every(
                        timer[0],
                        timer[3].parse().unwrap(),
                        Some(timer[2].parse().unwrap()),
                        callback,
                    )
                    .unwrap();
            }
        }
        clock.advance_to(fields[2].parse().unwrap()).unwrap();
        assert_eq!(
            observed.lock().unwrap().join(";"),
            fields[4],
            "{}",
            fields[0]
        );
    }
}

fn recording(output: Arc<Mutex<Vec<String>>>) -> onlyalpha_clock::VirtualCallback {
    Box::new(move |_, event| {
        output.lock().unwrap().push(format!(
            "{},{},{},{}",
            event.id, event.deadline_ns, event.sequence, event.fire_count
        ));
        Ok(())
    })
}
#[test]
fn independent_common_lifecycle_vectors() {
    for line in include_str!("../../../../test-data/clock/lifecycle-v1.tsv").lines() {
        if line.starts_with('#') {
            continue;
        }
        let fields: Vec<_> = line.split('\t').collect();
        let first: num_bigint::BigInt = fields[1].parse().unwrap();
        let second: num_bigint::BigInt = fields[2].parse().unwrap();
        let target: num_bigint::BigInt = fields[3].parse().unwrap();
        let mut clock = OnlyVirtualClock::new(0.into());
        let observed = Arc::new(Mutex::new(Vec::new()));
        match fields[0] {
            "restore" => {
                clock
                    .schedule_every("first", first, None, recording(observed.clone()))
                    .unwrap();
                clock.advance_to(second).unwrap();
                let snapshot = clock.snapshot().unwrap();
                let mut recovered = OnlyVirtualClock::new(0.into());
                recovered
                    .restore_fresh(
                        snapshot,
                        [("first".parse().unwrap(), recording(observed.clone()))].into(),
                    )
                    .unwrap();
                clock = recovered;
            }
            "failure" => {
                let mut record = recording(observed.clone());
                clock
                    .schedule_every(
                        "first",
                        first,
                        None,
                        Box::new(move |current, event| {
                            record(current, event)?;
                            Err("controlled callback failure".into())
                        }),
                    )
                    .unwrap();
                clock
                    .schedule_at("second", second, recording(observed.clone()))
                    .unwrap();
            }
            "register" => {
                let output = observed.clone();
                let mut record = recording(observed.clone());
                clock
                    .schedule_at(
                        "first",
                        first,
                        Box::new(move |current, event| {
                            record(current, event)?;
                            current.cancel("second")?;
                            current.schedule_at(
                                "child",
                                event.deadline_ns.clone(),
                                recording(output.clone()),
                            )?;
                            Ok(())
                        }),
                    )
                    .unwrap();
                clock
                    .schedule_at("second", second, recording(observed.clone()))
                    .unwrap();
            }
            "cancel" => {
                clock
                    .schedule_at("first", first, recording(observed.clone()))
                    .unwrap();
                clock
                    .schedule_at("second", second, recording(observed.clone()))
                    .unwrap();
                clock.cancel("second").unwrap();
            }
            "close" => {
                clock
                    .schedule_at("first", first, recording(observed.clone()))
                    .unwrap();
                clock.close().unwrap();
            }
            kind => panic!("unknown lifecycle vector {kind}"),
        }
        if fields[0] != "close" {
            clock.advance_to(target.clone()).unwrap();
        }
        let output = observed.lock().unwrap().join(";");
        assert_eq!(
            if output.is_empty() { "-" } else { &output },
            fields[4],
            "{}",
            fields[0]
        );
        assert_eq!(clock.timestamp_ns().unwrap(), target);
        assert_eq!(
            clock.failures().unwrap().len(),
            fields[5].parse::<usize>().unwrap()
        );
        assert_eq!(clock.has_timer("first").unwrap(), fields[6] == "true");
    }
}
