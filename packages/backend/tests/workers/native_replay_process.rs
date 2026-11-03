//! Fresh-process fault fixture over the installed numeric/native model owners.
//! It cannot create a Product Run, admission, or Evidence publication.
use super::*;
use std::io::{BufRead, Write};

fn setup(
    mutate: impl FnOnce(&mut Value),
) -> Result<(RunSpec, Inputs, Trading<InstalledTradingNodes>)> {
    use onlyalpha_domain::value::OnlyQuantity;
    use onlyalpha_plugin_binance::spot_simulation::SpotSimulationPolicy;
    let case = fixture()?;
    let artifact = std::env::var("ONLYALPHA_TRADING_TEST_ARTIFACT")?;
    let installation = Arc::new(ChartInstallation::open(
        Path::new(&std::env::var("ONLYALPHA_TRADING_TEST_INSTALLATION")?),
        &artifact,
    )?);
    let (_, program, definitions) = product_setup(&case, &artifact)?;
    let configuration = execution_configuration(&program);
    let inputs = vector_inputs(
        &case["base"],
        program.source(),
        48,
        "controlled-native-fault-v1",
        &"1".repeat(64),
        &"2".repeat(64),
    )?;
    let rules = rules()?;
    let instrument = rules.model_instrument()?.to_record();
    let quantity = OnlyQuantity::new(
        "0.01".parse()?,
        u8::try_from(
            instrument["quantity_precision"]
                .as_u64()
                .ok_or("quantity precision")?,
        )?,
    )?;
    let start = at("2025-01-03T00:00:00Z")?;
    let end = OnlyTimestamp::from_unix_nanos(start.to_unix_nanos() + 28 * BAR_NS);
    let mut settings = json!({"schema_version":2,"execution":configuration,"instrument":instrument,"policy":{"schema_version":1,"kind":"NEXT_OPEN_LONG_ONLY_V1","quantity":quantity.to_record(),"buy_multiplier":"1.0002","sell_multiplier":"0.9998","start_ns":start.to_unix_nanos().to_string(),"end_ns":end.to_unix_nanos().to_string()}});
    mutate(&mut settings);
    let policy = SpotSimulationPolicy::new(rules, configuration.clone())?;
    let kernel = fingerprint(&std::fs::read(std::env::current_exe()?)?);
    let initial_ns = at("2025-01-02T23:40:00Z")?.to_unix_nanos();
    let kind = inputs.records()[0].bar().bar_type().clone();
    let preparation =
        installed_preparation(&case, installation, program, definitions, kind, &kernel)?;
    let participants = Trading::next_open(
        preparation,
        settings,
        onlyalpha_backend::workers::backtest::next_open_policy(policy),
        initial_ns.clone(),
    )?;
    Ok((
        RunSpec {
            work_id: "technical-native-next-open-faults".into(),
            configuration,
            kernel_artifact: kernel.clone(),
            driver_artifact: kernel,
            initial_ns,
        },
        inputs,
        participants,
    ))
}

#[test]
fn foreign_instrument_context_is_refused_before_market_or_order_processing() -> Result<()> {
    assert!(
        setup(
            |settings| settings["instrument"]["instrument_id"]["symbol"]["value"] =
                json!("ETHUSDT")
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn process_writer() -> Result<()> {
    let Ok(root) = std::env::var("OA_REPLAY_PROCESS_ROOT") else {
        return Ok(());
    };
    let root = Path::new(&root);
    let mode = std::env::var("OA_REPLAY_PROCESS_MODE")?;
    if mode == "MUTATE" {
        journal_fault(root, std::env::var("OA_REPLAY_MUTATION")?.parse()?);
        return Ok(());
    }
    let (spec, inputs, trading) = setup(|_| {})?;
    if matches!(mode.as_str(), "REFUSE" | "REFUSE_RELATION") {
        if mode == "REFUSE_RELATION" {
            let runtime = onlyalpha_runtime_persistence::Runtime::open(
                root,
                spec.configuration.clone(),
                &spec.kernel_artifact,
            )?;
            runtime.replay_steps().expect("rehashed relation fault must preserve original canonical Execution and structural journal integrity");
        }
        assert!(RunLoop::open(root, spec, inputs, trading).is_err());
        println!("REFUSED");
        return Ok(());
    }
    let mut run = if root.join("runtime.sqlite3").is_file() {
        RunLoop::open(root, spec, inputs, trading)?
    } else {
        assert!(
            matches!(
                mode.as_str(),
                "BASELINE" | "RUN" | "CANCELLED" | "UNKNOWN" | "FAILED" | "INCOMPLETE"
            ),
            "resume cannot create missing history"
        );
        RunLoop::create(root, spec, inputs, trading)?
    };
    let cut = std::env::var("OA_REPLAY_CUT").unwrap_or_default();
    let barrier = |phase: &str,
                   step: u64,
                   count: u64|
     -> std::result::Result<(), onlyalpha_backtest::Error> {
        if cut == format!("{phase}:{step}:{count}") {
            println!("\nBARRIER");
            std::io::stdout().flush().unwrap();
            let mut line = String::new();
            std::io::stdin().lock().read_line(&mut line).unwrap();
            panic!("barrier must be killed");
        }
        Ok(())
    };
    if matches!(
        mode.as_str(),
        "CANCELLED" | "UNKNOWN" | "FAILED" | "INCOMPLETE"
    ) {
        // A real filled prefix with an unsent closing signal: stop must preserve
        // the actual position/cash and cannot infer cancellation or full drain.
        for _ in 0..44 {
            assert!(run.step()?);
        }
        let before = run.state()?;
        let preparation = run.trace_metadata()?["state"]["participants"].clone();
        assert_eq!(preparation["native"]["pending"]["side"], "SELL");
        run.terminate(&mode, Some("EXPLICIT_OPERATOR_OUTCOME"))?;
        assert_eq!(run.state()?, before);
        assert_eq!(run.trace_metadata()?["state"]["participants"], preparation);
        let result = run.result()?;
        assert_eq!(result["outcome"]["status"], mode);
        assert_eq!(
            result["status"],
            if mode == "UNKNOWN" {
                "INCOMPLETE"
            } else {
                mode.as_str()
            }
        );
        assert_eq!(result["drained"], false);
        assert_eq!(
            result["execution_result"]["trades"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        std::fs::write(
            root.join("result.json"),
            json!({"result":result,"trace":run.trace()?,"state":run.state()?}).to_string(),
        )?;
        return Ok(());
    }
    let measured = std::time::Instant::now();
    eprintln!("NATIVE_REPLAY_PHASE market_start");
    if cut.is_empty() || cut == "DELIVERY:0:0" {
        let mut count = 0;
        while run.step()? {
            count += 1;
            if count % 128 == 0 {
                eprintln!(
                    "NATIVE_REPLAY_PHASE step={count} elapsed={:?}",
                    measured.elapsed()
                );
            }
        }
    } else {
        while run.step_observed(&mut |phase, step, count| barrier(phase, step, count))? {}
    }
    eprintln!(
        "NATIVE_REPLAY_PHASE market_complete elapsed={:?}",
        measured.elapsed()
    );
    run.close_input()?;
    eprintln!(
        "NATIVE_REPLAY_PHASE input_closed elapsed={:?}",
        measured.elapsed()
    );
    let mut events = vec![];
    run.deliver(|event| {
        events.push(event["event_id"].clone());
        barrier("DELIVERY", 0, 0)
    })?;
    eprintln!(
        "NATIVE_REPLAY_PHASE delivered elapsed={:?}",
        measured.elapsed()
    );
    run.finish_input()?;
    eprintln!(
        "NATIVE_REPLAY_PHASE terminated elapsed={:?}",
        measured.elapsed()
    );
    let result = run.result()?;
    eprintln!(
        "NATIVE_REPLAY_PHASE result elapsed={:?}",
        measured.elapsed()
    );
    assert_eq!(
        decimal(&result["execution_result"]["final_account"]["cash"]),
        "9994.60119940".parse()?
    );
    assert_eq!(
        decimal(&result["execution_result"]["final_account"]["fees"]),
        "1.99900060".parse()?
    );
    assert_eq!(
        result["execution_result"]["trades"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
    std::fs::write(
        root.join("result.json"),
        json!({"result":result,"trace":run.trace()?,"events":events,"state":run.state()?})
            .to_string(),
    )?;
    Ok(())
}
