use onlyalpha_indicators::{
    ComposedIndicator, Decimal, IndicatorError, IndicatorState, MACDCross, RSIZone, UtcSessionVWAP,
    atr, bollinger, ema, macd, obv, roc, rolling_volatility, rsi, sma, stochastic, vwap, wma,
    zscore,
};
use std::num::NonZeroUsize;
use std::str::FromStr;

type Cell = Option<Decimal>;

fn p(n: usize) -> NonZeroUsize {
    NonZeroUsize::new(n).unwrap()
}

fn d(text: &str) -> Decimal {
    Decimal::from_str(text).unwrap()
}

fn values(items: &[&str]) -> Vec<Cell> {
    items
        .iter()
        .map(|item| if *item == "null" { None } else { Some(d(item)) })
        .collect()
}

fn step_all(indicator: &ComposedIndicator, columns: &[Vec<Cell>]) -> Vec<Vec<Cell>> {
    let mut stream = indicator.event_stream().unwrap();
    let len = columns[0].len();
    let mut outputs = vec![Vec::with_capacity(len); indicator.output_count()];
    for i in 0..len {
        let row: Vec<Cell> = columns.iter().map(|col| col[i].clone()).collect();
        let stepped = stream.step(&row).unwrap();
        for (out, cell) in outputs.iter_mut().zip(stepped) {
            out.push(cell);
        }
    }
    outputs
}

fn assert_indicator(indicator: &ComposedIndicator, columns: &[Vec<Cell>], expected: &[&[&str]]) {
    let vector = indicator.evaluate_vector(columns).unwrap();
    let event = step_all(indicator, columns);
    assert_eq!(vector, event, "vector and event outputs must match");
    assert_eq!(vector.len(), expected.len());
    for (actual, exp) in vector.iter().zip(expected) {
        assert_eq!(*actual, values(exp));
    }
}

fn every_composed_indicator() -> Vec<(&'static str, ComposedIndicator)> {
    vec![
        ("sma", sma(p(3)).unwrap()),
        ("wma", wma(p(3)).unwrap()),
        ("roc", roc(p(2)).unwrap()),
        ("ema", ema(p(3)).unwrap()),
        ("rolling_volatility", rolling_volatility(p(3)).unwrap()),
        ("zscore", zscore(p(3)).unwrap()),
        ("bollinger", bollinger(p(3), d("2")).unwrap()),
        ("macd", macd(p(2), p(4), p(2)).unwrap()),
        ("rsi", rsi(p(2)).unwrap()),
        ("atr", atr(p(2)).unwrap()),
        ("obv", obv().unwrap()),
        ("vwap", vwap(p(3)).unwrap()),
        ("stochastic", stochastic(p(2), p(2), p(2)).unwrap()),
    ]
}

fn systematic_inputs(input_count: usize) -> Vec<Vec<Cell>> {
    match input_count {
        1 => vec![values(&[
            "10", "12", "11", "11", "15", "null", "14", "10", "18",
        ])],
        2 => vec![
            values(&["10", "12", "11", "11", "15", "null", "14", "10", "18"]),
            values(&["0", "2", "3", "0", "4", "1", "0", "5", "2"]),
        ],
        3 => vec![
            values(&["12", "14", "13", "13", "17", "null", "16", "12", "20"]),
            values(&["8", "10", "11", "13", "12", "null", "13", "8", "14"]),
            values(&["10", "12", "12", "13", "15", "null", "14", "10", "18"]),
        ],
        _ => unreachable!(),
    }
}

fn complete_inputs(input_count: usize) -> Vec<Vec<Cell>> {
    match input_count {
        1 => vec![values(&["10", "12", "11", "14", "13", "16", "15", "18"])],
        2 => vec![
            values(&["10", "12", "11", "14", "13", "16", "15", "18"]),
            values(&["1", "2", "3", "4", "5", "6", "7", "8"]),
        ],
        3 => vec![
            values(&["12", "14", "13", "16", "15", "18", "17", "20"]),
            values(&["8", "10", "9", "12", "11", "14", "13", "16"]),
            values(&["10", "12", "11", "14", "13", "16", "15", "18"]),
        ],
        _ => unreachable!(),
    }
}

#[test]
fn moving_average_return_and_volatility_goldens_are_independently_derived() {
    assert_indicator(
        &sma(p(3)).unwrap(),
        &[values(&["1", "2", "3", "4", "5"])],
        &[&["null", "null", "2", "3", "4"]],
    );
    assert_indicator(
        &wma(p(3)).unwrap(),
        &[values(&["1", "2", "3", "4"])],
        &[&["null", "null", "2.333333333333", "3.333333333333"]],
    );
    assert_indicator(
        &roc(p(2)).unwrap(),
        &[values(&["4", "0", "5", "null", "4", "7"])],
        &[&["null", "null", "0.25", "null", "-0.2", "null"]],
    );
    assert_indicator(
        &ema(p(3)).unwrap(),
        &[values(&["10", "14", "10", "18"])],
        &[&["10", "12", "11", "14.5"]],
    );
    assert_indicator(
        &rolling_volatility(p(3)).unwrap(),
        &[values(&["3", "1", "2", "2", "5"])],
        &[&[
            "null",
            "null",
            "0.816496580928",
            "0.471404520791",
            "1.414213562373",
        ]],
    );
    assert_indicator(
        &zscore(p(2)).unwrap(),
        &[values(&["2", "2", "0", "4"])],
        &[&["null", "0", "-1", "1"]],
    );
    assert_indicator(
        &bollinger(p(2), d("2")).unwrap(),
        &[values(&["10", "12", "14"])],
        &[
            &["null", "11", "13"],
            &["null", "13", "15"],
            &["null", "9", "11"],
        ],
    );
}

#[test]
fn oscillator_range_and_volume_goldens_are_independently_derived() {
    let macd_ind = macd(p(1), p(3), p(3)).unwrap();
    assert_indicator(
        &macd_ind,
        &[values(&["10", "14", "10"])],
        &[&["0", "2", "-1"], &["0", "1", "0"], &["0", "1", "-1"]],
    );
    let hist = macd_ind
        .evaluate_vector(&[values(&["10", "14", "10"])])
        .unwrap()[2]
        .clone();
    assert_eq!(
        MACDCross::from_histograms(None, hist[0].as_ref()),
        MACDCross::None
    );
    assert_eq!(
        MACDCross::from_histograms(hist[0].as_ref(), hist[1].as_ref()),
        MACDCross::Golden
    );
    assert_eq!(
        MACDCross::from_histograms(hist[1].as_ref(), hist[2].as_ref()),
        MACDCross::Death
    );

    assert_indicator(
        &rsi(p(2)).unwrap(),
        &[values(&["10", "12", "11", "10"])],
        &[&["null", "null", "66.6666666667", "40"]],
    );
    let rsi_edge = rsi(p(1)).unwrap();
    let edge_out = rsi_edge
        .evaluate_vector(&[values(&["5", "5", "6", "5"])])
        .unwrap()[0]
        .clone();
    assert_eq!(edge_out, values(&["null", "50", "100", "0"]));
    assert_eq!(RSIZone::from_value(edge_out[1].as_ref()), RSIZone::Neutral);
    assert_eq!(
        RSIZone::from_value(edge_out[2].as_ref()),
        RSIZone::Overbought
    );
    assert_eq!(RSIZone::from_value(edge_out[3].as_ref()), RSIZone::Oversold);

    assert_indicator(
        &atr(p(2)).unwrap(),
        &[
            values(&["10", "16", "16", "1"]),
            values(&["8", "14", "14", "0"]),
            values(&["9", "15", "15", "0"]),
        ],
        &[
            &["null", "null", "4.5", "9.75"],
            &["null", "null", "0.3", "null"],
        ],
    );

    assert_indicator(
        &obv().unwrap(),
        &[
            values(&["10", "11", "11", "9"]),
            values(&["100", "50", "20", "30"]),
        ],
        &[&["null", "50", "50", "20"]],
    );

    assert_indicator(
        &vwap(p(2)).unwrap(),
        &[
            values(&["10", "20", "30", "40"]),
            values(&["0", "0", "1", "3"]),
        ],
        &[&["null", "null", "30", "37.5"]],
    );

    assert_indicator(
        &stochastic(p(2), p(2), p(2)).unwrap(),
        &[
            values(&["10", "12", "14", "16"]),
            values(&["0", "2", "4", "6"]),
            values(&["2", "6", "14", "13"]),
        ],
        &[
            &["null", "null", "75", "87.5"],
            &["null", "null", "null", "81.25"],
        ],
    );
}

#[test]
fn stochastic_recovers_after_a_flat_price_range() {
    assert_indicator(
        &stochastic(p(2), p(2), p(2)).unwrap(),
        &[
            values(&["4", "4", "4", "4", "8", "8", "8"]),
            values(&["4", "4", "4", "4", "4", "4", "4"]),
            values(&["4", "4", "4", "4", "6", "8", "4"]),
        ],
        &[
            &["null", "null", "null", "null", "null", "75", "50"],
            &["null", "null", "null", "null", "null", "null", "62.5"],
        ],
    );
}

#[test]
fn every_composed_indicator_has_vector_event_equivalence_and_prefix_causality() {
    for (name, indicator) in every_composed_indicator() {
        let columns = systematic_inputs(indicator.input_count());
        let full = indicator.evaluate_vector(&columns).unwrap();
        let event = step_all(&indicator, &columns);
        assert_eq!(full, event, "{name} vector == event");

        for len in 1..=columns[0].len() {
            let prefix: Vec<Vec<Cell>> = columns.iter().map(|c| c[..len].to_vec()).collect();
            let vec_prefix = indicator.evaluate_vector(&prefix).unwrap();
            let evt_prefix = step_all(&indicator, &prefix);
            for (out_idx, full_col) in full.iter().enumerate() {
                assert_eq!(
                    vec_prefix[out_idx],
                    full_col[..len],
                    "{name} vector causality prefix {len} output {out_idx}"
                );
                assert_eq!(
                    evt_prefix[out_idx],
                    full_col[..len],
                    "{name} event causality prefix {len} output {out_idx}"
                );
            }
        }
    }
}

#[test]
fn warmup_and_all_null_boundaries_match_every_indicator_contract() {
    for (name, indicator) in every_composed_indicator() {
        let complete = complete_inputs(indicator.input_count());
        let outputs = indicator.evaluate_vector(&complete).unwrap();
        let minimum = indicator.minimum_observations();
        let last_output = outputs.last().unwrap();
        for (index, cell) in last_output.iter().enumerate().take(minimum - 1) {
            assert!(
                cell.is_none(),
                "{name} must remain null during warmup at index {index}"
            );
        }
        assert!(
            last_output[minimum - 1].is_some(),
            "{name} must emit at minimum_observations - 1 ({})",
            minimum - 1
        );

        let all_null = vec![vec![None; 6]; indicator.input_count()];
        let null_out = indicator.evaluate_vector(&all_null).unwrap();
        for col in null_out {
            assert!(col.iter().all(Option::is_none), "{name} all-null output");
        }
    }
}

#[test]
fn checkpoint_and_restore_preserve_every_suffix_for_every_indicator() {
    for (name, indicator) in every_composed_indicator() {
        let columns = systematic_inputs(indicator.input_count());
        let expected = indicator.evaluate_vector(&columns).unwrap();
        let total = columns[0].len();

        for cut in 0..=total {
            let mut left = indicator.event_stream().unwrap();
            for i in 0..cut {
                let row: Vec<Cell> = columns.iter().map(|c| c[i].clone()).collect();
                left.step(&row).unwrap();
            }
            let state = left.capture_state();

            let mut restored = indicator.event_stream().unwrap();
            restored.restore_state(state).unwrap();

            for i in cut..total {
                let row: Vec<Cell> = columns.iter().map(|c| c[i].clone()).collect();
                let actual = restored.step(&row).unwrap();
                for (out_idx, cell) in actual.iter().enumerate() {
                    assert_eq!(
                        cell, &expected[out_idx][i],
                        "{name} restore at cut {cut}, step {i}, output {out_idx}"
                    );
                }
            }
        }
    }
}

#[test]
fn utc_session_vwap_matches_golden_equivalence_causality_and_restore() {
    let midnight = 86_400_000_000_000_u64;
    let ts = [midnight - 2, midnight - 1, midnight, midnight + 1];
    let high = values(&["12", "15", "20", "24"]);
    let low = values(&["9", "12", "20", "21"]);
    let close = values(&["10", "15", "20", "21"]);
    let vol = values(&["2", "1", "0", "1"]);

    let batch = UtcSessionVWAP::evaluate_vector(&ts, &high, &low, &close, &vol).unwrap();
    assert_eq!(
        batch,
        values(&["10.333333333333", "11.555555555556", "null", "22"])
    );

    let mut stream = UtcSessionVWAP::new();
    let event: Vec<Cell> = (0..ts.len())
        .map(|i| {
            stream
                .step(
                    ts[i],
                    high[i].clone(),
                    low[i].clone(),
                    close[i].clone(),
                    vol[i].clone(),
                )
                .unwrap()
        })
        .collect();
    assert_eq!(batch, event);

    assert_eq!(
        stream.step(
            midnight + 1,
            Some(d("24")),
            Some(d("21")),
            Some(d("21")),
            Some(d("1"))
        ),
        Err(IndicatorError::InvalidInputs)
    );

    for cut in 0..=ts.len() {
        let prefix = UtcSessionVWAP::evaluate_vector(
            &ts[..cut],
            &high[..cut],
            &low[..cut],
            &close[..cut],
            &vol[..cut],
        )
        .unwrap();
        assert_eq!(prefix, batch[..cut], "session vwap prefix {cut}");
        let mut left = UtcSessionVWAP::new();
        for i in 0..cut {
            left.step(
                ts[i],
                high[i].clone(),
                low[i].clone(),
                close[i].clone(),
                vol[i].clone(),
            )
            .unwrap();
        }
        let state = left.capture_state();
        let mut restored = UtcSessionVWAP::new();
        restored.restore_state(state).unwrap();
        for i in cut..ts.len() {
            let actual = restored
                .step(
                    ts[i],
                    high[i].clone(),
                    low[i].clone(),
                    close[i].clone(),
                    vol[i].clone(),
                )
                .unwrap();
            assert_eq!(actual, batch[i], "session vwap restore cut {cut} step {i}");
        }
    }
}

#[test]
fn invalid_parameters_and_corrupted_checkpoints_are_rejected_without_mutation() {
    assert_eq!(
        bollinger(p(2), d("-1")).unwrap_err(),
        IndicatorError::InvalidParameters
    );
    assert_eq!(
        macd(p(3), p(3), p(2)).unwrap_err(),
        IndicatorError::InvalidParameters
    );

    let indicator = sma(p(2)).unwrap();
    let mut stream = indicator.event_stream().unwrap();
    assert_eq!(stream.step(&[Some(d("10"))]).unwrap(), vec![None]);
    let saved = stream.capture_state();
    assert_eq!(saved.step_count(), 1);

    assert_eq!(
        stream.restore_state(IndicatorState::from_parts(1, vec![])),
        Err(IndicatorError::InvalidInputs)
    );
    // Tampered step_count (truncated window or understated step_count) MUST fail-closed.
    assert_eq!(
        stream.restore_state(IndicatorState::from_parts(0, saved.as_slice().to_vec())),
        Err(IndicatorError::InvalidInputs)
    );
    assert_eq!(
        stream.restore_state(IndicatorState::from_parts(5, saved.as_slice().to_vec())),
        Err(IndicatorError::InvalidInputs)
    );
    assert_eq!(stream.capture_state(), saved);
    assert_eq!(stream.step(&[Some(d("20"))]).unwrap(), vec![Some(d("15"))]);

    // Cross-stream desync in multi-operator indicator MUST fail-closed.
    let bb = bollinger(p(3), d("2")).unwrap();
    let mut bb_stream = bb.event_stream().unwrap();
    for v in ["10", "12", "14"] {
        bb_stream.step(&[Some(d(v))]).unwrap();
    }
    let mut desynced = bb_stream.capture_state().as_slice().to_vec();
    desynced[0][0].pop(); // truncate RollingMean window while leaving RollingStd full
    assert_eq!(
        bb_stream.restore_state(IndicatorState::from_parts(3, desynced)),
        Err(IndicatorError::InvalidInputs)
    );

    // UtcSessionVWAP rejects inconsistent previous_start vs stream step_count,
    // and ignores volume on partially-null price bars.
    let mut vwap_stream = UtcSessionVWAP::new();
    let empty_state = vwap_stream.capture_state();
    vwap_stream
        .step(
            100,
            Some(d("12")),
            Some(d("9")),
            Some(d("10")),
            Some(d("2")),
        )
        .unwrap();
    let active_state = vwap_stream.capture_state();
    assert_eq!(
        vwap_stream.restore_state(onlyalpha_indicators::UtcSessionVwapState {
            previous_start: None,
            stream_state: active_state.stream_state.clone(),
        }),
        Err(IndicatorError::InvalidInputs)
    );
    assert_eq!(
        vwap_stream.restore_state(onlyalpha_indicators::UtcSessionVwapState {
            previous_start: Some(100),
            stream_state: empty_state.stream_state,
        }),
        Err(IndicatorError::InvalidInputs)
    );
    // Partially-null price row with non-null volume must not skew denominator.
    let vwap_partial = UtcSessionVWAP::evaluate_vector(
        &[100, 200, 300],
        &values(&["12", "null", "15"]),
        &values(&["9", "10", "12"]),
        &values(&["10", "10", "15"]),
        &values(&["2", "100", "1"]),
    )
    .unwrap();
    assert_eq!(
        vwap_partial,
        values(&["10.333333333333", "null", "11.555555555556"])
    );
}
