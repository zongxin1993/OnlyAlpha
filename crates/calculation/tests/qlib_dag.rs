use onlyalpha_calculation::qlib::{
    DagState, FactorExpr, MAX_EXPR_BYTES, MAX_EXPR_DEPTH, PanelDagState, TargetExpr,
};
use onlyalpha_operators::algebra::Decimal;
use std::collections::{BTreeMap, BTreeSet};
use std::str::FromStr;

fn dec(s: &str) -> Decimal {
    Decimal::from_str(s).unwrap()
}

fn col(values: &[Option<&str>]) -> Vec<Option<Decimal>> {
    values.iter().map(|v| v.map(dec)).collect()
}

fn series(entries: &[(&str, &[Option<&str>])]) -> BTreeMap<String, Vec<Option<Decimal>>> {
    entries
        .iter()
        .map(|(k, v)| ((*k).to_owned(), col(v)))
        .collect()
}

fn slice_row(
    data: &BTreeMap<String, Vec<Option<Decimal>>>,
    index: usize,
) -> BTreeMap<String, Option<Decimal>> {
    data.iter()
        .map(|(k, v)| (k.clone(), v[index].clone()))
        .collect()
}

fn run_event(
    expr: &FactorExpr,
    data: &BTreeMap<String, Vec<Option<Decimal>>>,
    len: usize,
) -> Vec<Option<Decimal>> {
    let mut exec = expr.event_executor().unwrap();
    (0..len)
        .map(|t| exec.step(&slice_row(data, t)).unwrap())
        .collect()
}

fn run_panel_event(
    expr: &FactorExpr,
    panel: &[BTreeMap<String, Vec<Option<Decimal>>>],
    len: usize,
) -> Vec<Vec<Option<Decimal>>> {
    let n = panel.len();
    let mut exec = expr.panel_event_executor(n).unwrap();
    let mut out = vec![Vec::with_capacity(len); n];
    for t in 0..len {
        let cohort: Vec<_> = panel.iter().map(|inst| slice_row(inst, t)).collect();
        let step = exec.step(&cohort).unwrap();
        for (i, cell) in step.into_iter().enumerate() {
            out[i].push(cell);
        }
    }
    out
}

#[test]
fn factor_expr_statically_rejects_every_lookahead_construct() {
    let forbidden = [
        "Ref($close, -1)",
        "Ref($close, -5)",
        "delay($close, -2)",
        "Lead($close, 1)",
        "lead($close, 3)",
        "Ref($close, -(2))",
        "Mean(Ref($close, -1), 5)",
        "Ref(Ref($close, -1), 1)",
        "Where($close > 0, Ref($close, -2), $close)",
        "Corr($close, Ref($volume, -1), 5)",
        "Delta($close, -1)",
        "Mean($close, -3)",
        "Std($close, -2)",
        "WMA($close, -4)",
        "EMA($close, -5)",
        "RMA($close, -5)",
        "Slope($close, -3)",
        "Cov($close, $volume, -3)",
        "Rank($close, -3)",
    ];
    for source in forbidden {
        let err = FactorExpr::compile(source)
            .expect_err(&format!("FactorExpr MUST reject look-ahead `{source}`"));
        assert!(
            err.to_string().contains("QLIB_LOOKAHEAD_FORBIDDEN"),
            "expected QLIB_LOOKAHEAD_FORBIDDEN for `{source}`, got `{err}`"
        );
    }
}

#[test]
fn factor_expr_statically_rejects_account_execution_and_nondeterministic_inputs() {
    let forbidden = [
        "$cash",
        "$position",
        "$position_qty",
        "$positions",
        "$account",
        "$account_equity",
        "$fill_price",
        "$fills",
        "$order_size",
        "$execution_cost",
        "$portfolio_value",
        "$balance",
        "$pnl",
        "$margin_ratio",
        "$fee",
        "$commission",
        "$slippage",
        "$broker_id",
        "$venue_time",
        "$clock",
        "$now",
        "$random",
        "$env_seed",
        "$future_ret",
        "$target",
        "$label_5d",
        "Mean($close, 5) + $cash",
        // camelCase, PascalCase, acronym, digit-suffixed, and plural variants MUST also be rejected.
        "$cashBalance",
        "$accountId",
        "$accountEquity",
        "$positionQty",
        "$fillPrice",
        "$filledQty",
        "$orderSize",
        "$portfolioValue",
        "$futureClose",
        "$targetReturn",
        "$label5d",
        "$cash1",
        "$position0",
        "$target1",
        "$USDPosition",
        "$accounts",
        "$fees",
        "$commissions",
        "$margins",
        "$brokers",
        "$venues",
        "$clocks",
        "$executions",
        "$portfolios",
        "$equities",
        "$balances",
        "$cashes",
        "$futures",
        "$targets",
        "$labels",
    ];
    for source in forbidden {
        let err = FactorExpr::compile(source).expect_err(&format!(
            "FactorExpr MUST reject forbidden input `{source}`"
        ));
        assert!(
            err.to_string().contains("QLIB_FORBIDDEN_INPUT"),
            "expected QLIB_FORBIDDEN_INPUT for `{source}`, got `{err}`"
        );
    }

    // Legitimate camelCase market-data fields remain allowed.
    assert!(FactorExpr::compile("Mean($adjClose, 3) + $openInterest").is_ok());

    let allowed = BTreeSet::from(["close".to_owned(), "volume".to_owned()]);
    assert!(
        FactorExpr::compile_with_allowed_fields("Mean($close, 3) / Log($volume + 1)", &allowed)
            .is_ok()
    );
    let err = FactorExpr::compile_with_allowed_fields("$open - $close", &allowed).unwrap_err();
    assert!(err.to_string().contains("QLIB_UNDECLARED_INPUT"));

    // Even if a caller mistakenly lists `cash` as allowed, the forbidden namespace still wins.
    let bad_allowed = BTreeSet::from(["cash".to_owned()]);
    let err = FactorExpr::compile_with_allowed_fields("$cash", &bad_allowed).unwrap_err();
    assert!(err.to_string().contains("QLIB_FORBIDDEN_INPUT"));
}

#[test]
fn target_expr_supports_bounded_lookahead_and_is_domain_separated_from_factor_expr() {
    let target = TargetExpr::compile("Ref($close, -2) / $close - 1").unwrap();
    assert_eq!(target.max_lookahead(), 2);
    assert_eq!(target.minimum_observations(), 1);
    let data = series(&[(
        "close",
        &[
            Some("100"),
            Some("110"),
            Some("120"),
            Some("132"),
            Some("120"),
        ],
    )]);
    let out = target.evaluate_vector(&data).unwrap();
    // t=0: 120/100 - 1 = 0.2; t=1: 132/110 - 1 = 0.2; t=2: 120/120 - 1 = 0; t=3,4: None
    assert_eq!(
        out,
        col(&[
            Some("0.200000000000"),
            Some("0.200000000000"),
            Some("0.000000000000"),
            None,
            None,
        ])
    );

    // Lead alias compiles to identical canonical DAG and fingerprint.
    let lead_target = TargetExpr::compile("Lead($close, 2) / $close - 1").unwrap();
    assert_eq!(target.canonical(), lead_target.canonical());
    assert_eq!(target.fingerprint(), lead_target.fingerprint());

    // Nested look-ahead accumulates exact horizon and warmup independently.
    let nested = TargetExpr::compile("Mean(Ref($close, -2), 2)").unwrap();
    assert_eq!(nested.max_lookahead(), 2);
    assert_eq!(nested.minimum_observations(), 2);
    let nested_out = nested.evaluate_vector(&data).unwrap();
    // Ref($close, -2) = [120, 132, 120, None, None]
    // Mean(..., 2)    = [None, 126, 126, None, None]
    assert_eq!(
        nested_out,
        col(&[
            None,
            Some("126.000000000000"),
            Some("126.000000000000"),
            None,
            None,
        ])
    );

    // Cross-section target label over panel works for Research.
    let cs_target = TargetExpr::compile("CSRank(Ref($close, -1) / $close - 1)").unwrap();
    assert!(cs_target.has_cross_section());
    assert!(cs_target.evaluate_vector(&data).is_err());
    let panel = vec![
        series(&[("close", &[Some("100"), Some("110"), Some("121")])]), // +10%, +10%, None
        series(&[("close", &[Some("100"), Some("120"), Some("108")])]), // +20%, -10%, None
    ];
    let cs_out = cs_target.evaluate_panel(&panel).unwrap();
    assert_eq!(
        cs_out[0],
        col(&[Some("0.000000000000"), Some("1.000000000000"), None])
    );
    assert_eq!(
        cs_out[1],
        col(&[Some("1.000000000000"), Some("0.000000000000"), None])
    );

    // Same causal expression compiled as FactorExpr vs TargetExpr has distinct domain-separated fingerprint.
    let f = FactorExpr::compile("Mean($close, 3)").unwrap();
    let t = TargetExpr::compile("Mean($close, 3)").unwrap();
    assert_ne!(f.fingerprint(), t.fingerprint());
    assert_eq!(f.canonical(), t.canonical());
}

#[test]
fn independent_goldens_for_qlib_formulas_arithmetic_comparisons_and_cse() {
    // 1. ADR 0152 example 1: Mean($close, 3) / Std($close, 3)
    // For [10, 12, 14]: mean = 12, var = ((2^2 + 0 + 2^2)/3) = 8/3, std = sqrt(8/3) = 1.632993161855
    // mean / std = 12 / 1.632993161855 = 7.348469228352 (verified with Python Decimal prec=28 HALF_EVEN)
    let sharpe_like = FactorExpr::compile("Mean($close, 3) / Std($close, 3)").unwrap();
    assert_eq!(sharpe_like.minimum_observations(), 3);
    assert_eq!(sharpe_like.inputs(), &BTreeSet::from(["close".to_owned()]));
    let data = series(&[("close", &[Some("10"), Some("12"), Some("14"), Some("14")])]);
    let vec_out = sharpe_like.evaluate_vector(&data).unwrap();
    let evt_out = run_event(&sharpe_like, &data, 4);
    assert_eq!(vec_out, evt_out);
    assert_eq!(vec_out[0], None);
    assert_eq!(vec_out[1], None);
    assert_eq!(vec_out[2], Some(dec("7.348469228352")));
    // [12, 14, 14]: mean = 40/3 = 13.333333333333, var = 8/9, std = 0.942809041582
    // 13.333333333333 / 0.942809041582 = 14.142135623732
    assert_eq!(vec_out[3], Some(dec("14.142135623732")));

    // 2. ADR 0152 example 2: Corr($close, Log($volume + 1), 3)
    let corr_expr = FactorExpr::compile("Corr($close, Log($volume + 1), 3)").unwrap();
    assert_eq!(corr_expr.minimum_observations(), 3);
    let data2 = series(&[
        ("close", &[Some("10"), Some("20"), Some("30"), Some("40")]),
        ("volume", &[Some("1"), Some("3"), Some("7"), Some("15")]),
    ]);
    let vec_corr = corr_expr.evaluate_vector(&data2).unwrap();
    let evt_corr = run_event(&corr_expr, &data2, 4);
    assert_eq!(vec_corr, evt_corr);
    assert!(vec_corr[0].is_none() && vec_corr[1].is_none());
    // volume+1 = [2, 4, 8, 16] => log(volume+1) is strictly linear in [1,2,3,4]*ln(2),
    // and close is strictly linear [10,20,30,40] => correlation is 1.000000000000!
    assert_eq!(vec_corr[2], Some(dec("1.000000000000")));
    assert_eq!(vec_corr[3], Some(dec("1.000000000000")));

    // 3. Arithmetic precedence, unary minus, comparisons, logical ops, Where/If, Greater/Less
    let logic_expr = FactorExpr::compile(
        "If($close > $open && !($volume == 0), -$open + $close * 2, Less($open, $close))",
    )
    .unwrap();
    let data3 = series(&[
        ("open", &[Some("10"), Some("10"), Some("15"), None]),
        ("close", &[Some("12"), Some("12"), Some("10"), Some("10")]),
        ("volume", &[Some("5"), Some("0"), Some("3"), Some("1")]),
    ]);
    let vec_logic = logic_expr.evaluate_vector(&data3).unwrap();
    let evt_logic = run_event(&logic_expr, &data3, 4);
    assert_eq!(vec_logic, evt_logic);
    // t=0: 12>10 && !(5==0) => true => -10 + 24 = 14
    // t=1: 12>10 && !(0==0) => false => Less(10, 12) = 10
    // t=2: 10>15 => false => Less(15, 10) = 10
    // t=3: open is None => None
    assert_eq!(
        vec_logic,
        col(&[
            Some("14.000000000000"),
            Some("10.000000000000"),
            Some("10.000000000000"),
            None,
        ])
    );

    // 4. CSE deduplication: repeated Mean($close, 3) shares a single operator node.
    let single = FactorExpr::compile("Mean($close, 3)").unwrap();
    let reused =
        FactorExpr::compile("(Mean($close, 3) - Ref(Mean($close, 3), 1)) + Mean($close, 3)")
            .unwrap();
    let mean_nodes = reused
        .instructions()
        .iter()
        .filter(|inst| format!("{inst:?}").contains("RollingMean"))
        .count();
    assert_eq!(mean_nodes, 1);
    assert!(reused.node_count() < single.node_count() * 3 + 3);
    assert!(reused.canonical().contains("let v"));
}

#[test]
fn vector_event_equivalence_and_multi_prefix_causality_hold_for_diverse_factor_dags() {
    let formulas = [
        "$close",
        "Ref($close, 0)",
        "Ref($close, 2)",
        "Delta($close, 2) / Ref($close, 2)",
        "Mean($close, 3) / Std($close, 3)",
        "($close - Mean($close, 3)) / Where(Std($close, 3), Std($close, 3), 1)",
        "Corr($close, Log($volume + 1), 3)",
        "Cov($high - $low, $volume, 3)",
        "WMA($close, 3) - EMA($close, 3)",
        "RMA(Abs(Delta($close, 1)), 3)",
        "Slope($close, 4)",
        "Rank($close, 3)",
        "CumSum(Sign(Delta($close, 1)) * $volume)",
        "Scale(Max($high, 3) - Min($low, 3), 0.5)",
        "Greater($high, Ref($close, 1)) - Less($low, Ref($close, 1))",
        "($close >= $open || $volume > 10) && !($low == 0)",
    ];

    let full = series(&[
        (
            "open",
            &[
                Some("10.0"),
                Some("11.0"),
                Some("10.5"),
                None,
                Some("12.0"),
                Some("12.0"),
                Some("11.5"),
                Some("13.0"),
                Some("12.5"),
                Some("14.0"),
            ],
        ),
        (
            "high",
            &[
                Some("11.0"),
                Some("12.0"),
                Some("11.5"),
                Some("12.5"),
                Some("13.0"),
                Some("12.5"),
                Some("12.0"),
                Some("14.0"),
                Some("13.5"),
                Some("15.0"),
            ],
        ),
        (
            "low",
            &[
                Some("9.5"),
                Some("10.5"),
                Some("10.0"),
                Some("11.0"),
                Some("11.5"),
                Some("11.5"),
                Some("11.0"),
                Some("12.5"),
                Some("12.0"),
                Some("13.5"),
            ],
        ),
        (
            "close",
            &[
                Some("10.5"),
                Some("11.5"),
                Some("10.0"),
                Some("12.0"),
                Some("12.0"),
                Some("12.0"),
                None,
                Some("13.5"),
                Some("13.0"),
                Some("14.5"),
            ],
        ),
        (
            "volume",
            &[
                Some("100"),
                Some("0"),
                Some("250"),
                Some("150"),
                Some("300"),
                Some("300"),
                Some("50"),
                None,
                Some("400"),
                Some("500"),
            ],
        ),
    ]);
    let len = 10;

    for source in formulas {
        let expr = FactorExpr::compile(source).unwrap();
        assert!(expr.supports_event_execution());
        assert!(!expr.has_cross_section());
        assert_eq!(expr.resource_budget().max_lookahead, 0);

        let vec_out = expr.evaluate_vector(&full).unwrap();
        let evt_out = run_event(&expr, &full, len);
        assert_eq!(vec_out, evt_out, "Vector == Event mismatch for `{source}`");

        // Multi-prefix causality: mutating future bars t+1..len must never change outputs[0..=t].
        for prefix_len in 1..len {
            let prefix_data: BTreeMap<String, Vec<Option<Decimal>>> = full
                .iter()
                .map(|(k, v)| (k.clone(), v[..prefix_len].to_vec()))
                .collect();
            let prefix_out = expr.evaluate_vector(&prefix_data).unwrap();
            assert_eq!(
                prefix_out,
                vec_out[..prefix_len],
                "prefix causality violated at prefix {prefix_len} for `{source}`"
            );

            // Also mutate future values drastically in a full-length series.
            let mut mutated = full.clone();
            for col in mutated.values_mut() {
                for cell in &mut col[prefix_len..] {
                    *cell = Some(dec("999999.123456"));
                }
            }
            let mutated_out = expr.evaluate_vector(&mutated).unwrap();
            assert_eq!(
                mutated_out[..prefix_len],
                vec_out[..prefix_len],
                "future mutation leaked into prefix {prefix_len} for `{source}`"
            );
        }
    }
}

#[test]
fn cross_section_panel_equivalence_causality_and_single_series_guard() {
    // Includes ADR 0152 example 3: Rank(Delta($close, 5)) (using period 2 for compact golden)
    let formulas = [
        "Rank(Delta($close, 2))",
        "CSRank(Delta($close, 2))",
        "CSZScore(Mean($close, 2))",
        "CSDemean($close)",
        "CSPercentile($close, 1)",
        "CSPercentile($close, -1)",
        "Rank(Mean($close, 2)) - CSDemean($volume)",
        "CSCorr($close, $volume)",
    ];

    let panel = vec![
        series(&[
            (
                "close",
                &[Some("10"), Some("12"), Some("15"), Some("14"), Some("18")],
            ),
            (
                "volume",
                &[
                    Some("100"),
                    Some("200"),
                    Some("150"),
                    Some("300"),
                    Some("250"),
                ],
            ),
        ]),
        series(&[
            (
                "close",
                &[Some("20"), Some("21"), Some("22"), Some("25"), Some("24")],
            ),
            (
                "volume",
                &[
                    Some("300"),
                    Some("100"),
                    Some("250"),
                    Some("200"),
                    Some("150"),
                ],
            ),
        ]),
        series(&[
            (
                "close",
                &[Some("30"), Some("28"), Some("27"), None, Some("33")],
            ),
            (
                "volume",
                &[
                    Some("200"),
                    Some("200"),
                    Some("200"),
                    Some("200"),
                    Some("200"),
                ],
            ),
        ]),
    ];
    let len = 5;

    for source in formulas {
        let expr = FactorExpr::compile(source).unwrap();
        assert!(expr.has_cross_section());
        assert!(!expr.supports_event_execution());

        // Single-series execution MUST fail-closed (never mix timestamps across a cross-section!).
        assert!(
            expr.evaluate_vector(&panel[0])
                .unwrap_err()
                .to_string()
                .contains("QLIB_CROSS_SECTION_REQUIRES_PANEL")
        );
        assert!(
            expr.event_executor()
                .unwrap_err()
                .to_string()
                .contains("QLIB_RESEARCH_ONLY_OPERATOR")
        );

        let batch = expr.evaluate_panel(&panel).unwrap();
        let stream = run_panel_event(&expr, &panel, len);
        assert_eq!(batch, stream, "panel batch != panel event for `{source}`");

        // Multi-prefix causality across the aligned panel.
        for prefix_len in 1..len {
            let prefix_panel: Vec<_> = panel
                .iter()
                .map(|inst| {
                    inst.iter()
                        .map(|(k, v)| (k.clone(), v[..prefix_len].to_vec()))
                        .collect()
                })
                .collect();
            let prefix_out = expr.evaluate_panel(&prefix_panel).unwrap();
            for i in 0..panel.len() {
                assert_eq!(
                    prefix_out[i],
                    batch[i][..prefix_len],
                    "panel causality violated at prefix {prefix_len}, inst {i} for `{source}`"
                );
            }
        }
    }

    // Verify independent golden for Rank(Delta($close, 2)) at t=2:
    // inst0: 15 - 10 = 5; inst1: 22 - 20 = 2; inst2: 27 - 30 = -3
    // CrossSectionRank (sorted ascending [-3, 2, 5] => [0, 0.5, 1]):
    // inst0 -> 1, inst1 -> 0.5, inst2 -> 0
    let rank_delta = FactorExpr::compile("Rank(Delta($close, 2))").unwrap();
    assert_eq!(rank_delta.minimum_observations(), 3);
    let out = rank_delta.evaluate_panel(&panel).unwrap();
    assert_eq!(out[0][0], None);
    assert_eq!(out[0][1], None);
    assert_eq!(out[0][2], Some(dec("1.000000000000")));
    assert_eq!(out[1][2], Some(dec("0.500000000000")));
    assert_eq!(out[2][2], Some(dec("0.000000000000")));
}

#[test]
fn warmup_and_all_null_boundaries_match_compiled_contract() {
    let cases = [
        ("Mean($close, 4)", 4usize),
        ("Delta($close, 3)", 4usize),
        ("Mean(Delta($close, 2), 3)", 5usize),
        ("Ref(Mean($close, 3), 2)", 5usize),
        ("RMA(Delta($close, 1), 3)", 4usize),
        ("EMA($close, 5)", 1usize),
        ("CumSum($close)", 1usize),
    ];
    let clean = series(&[(
        "close",
        &[
            Some("10"),
            Some("11"),
            Some("13"),
            Some("12"),
            Some("15"),
            Some("16"),
            Some("18"),
        ],
    )]);
    let all_null = series(&[("close", &[None, None, None, None, None, None, None])]);

    for (source, expected_min) in cases {
        let expr = FactorExpr::compile(source).unwrap();
        assert_eq!(
            expr.minimum_observations(),
            expected_min,
            "minimum_observations mismatch for `{source}`"
        );
        let out = expr.evaluate_vector(&clean).unwrap();
        for (i, cell) in out.iter().enumerate() {
            if i + 1 < expected_min {
                assert!(
                    cell.is_none(),
                    "expected warmup None at index {i} for `{source}`, got {cell:?}"
                );
            } else {
                assert!(
                    cell.is_some(),
                    "expected Ready Some at index {i} for `{source}`"
                );
            }
        }
        let null_out = expr.evaluate_vector(&all_null).unwrap();
        assert!(
            null_out.iter().all(Option::is_none),
            "all-null input must yield all-null output for `{source}`"
        );
        let null_evt = run_event(&expr, &all_null, 7);
        assert_eq!(null_out, null_evt);
    }
}

#[test]
fn checkpoint_restore_and_json_roundtrip_preserve_every_suffix_and_reject_tampering() {
    let expr = FactorExpr::compile(
        "(Mean($close, 3) - EMA($close, 3)) / Where(Std($close, 3), Std($close, 3), 1) + CumSum(Delta($close, 1))",
    )
    .unwrap();
    let data = series(&[(
        "close",
        &[
            Some("10"),
            Some("12"),
            Some("11"),
            Some("15"),
            None,
            Some("14"),
            Some("17"),
            Some("16"),
        ],
    )]);
    let len = 8;
    let expected = expr.evaluate_vector(&data).unwrap();

    for split in 0..=len {
        let mut first = expr.event_executor().unwrap();
        let mut prefix_out = Vec::new();
        for t in 0..split {
            prefix_out.push(first.step(&slice_row(&data, t)).unwrap());
        }
        let state = first.capture_state();
        assert_eq!(state.step_count, split as u64);

        // Round-trip through canonical JSON checkpoint record.
        let record = state.to_record();
        let decoded = DagState::from_record(&record).unwrap();
        assert_eq!(decoded, state);

        let mut restored = expr.event_executor().unwrap();
        restored.restore_state(decoded).unwrap();
        assert_eq!(restored.step_count(), split as u64);

        let mut suffix_out = Vec::new();
        for t in split..len {
            suffix_out.push(restored.step(&slice_row(&data, t)).unwrap());
        }
        prefix_out.extend(suffix_out);
        assert_eq!(
            prefix_out, expected,
            "checkpoint restore diverged at split {split}"
        );
    }

    // Panel checkpoint/restore + JSON round-trip.
    let panel_expr = FactorExpr::compile("Rank(Delta($close, 2)) + EMA($close, 2)").unwrap();
    let panel = vec![
        series(&[(
            "close",
            &[Some("10"), Some("12"), Some("14"), Some("13"), Some("16")],
        )]),
        series(&[(
            "close",
            &[Some("20"), Some("19"), Some("21"), Some("25"), Some("22")],
        )]),
    ];
    let panel_expected = panel_expr.evaluate_panel(&panel).unwrap();
    for split in 0..=5 {
        let mut exec = panel_expr.panel_event_executor(2).unwrap();
        let mut out = vec![Vec::new(); 2];
        for t in 0..split {
            let cohort: Vec<_> = panel.iter().map(|i| slice_row(i, t)).collect();
            let step = exec.step(&cohort).unwrap();
            for (i, c) in step.into_iter().enumerate() {
                out[i].push(c);
            }
        }
        let state = exec.capture_state();
        let decoded = PanelDagState::from_record(&state.to_record()).unwrap();
        assert_eq!(decoded, state);

        let mut restored = panel_expr.panel_event_executor(2).unwrap();
        restored.restore_state(decoded).unwrap();
        for t in split..5 {
            let cohort: Vec<_> = panel.iter().map(|i| slice_row(i, t)).collect();
            let step = restored.step(&cohort).unwrap();
            for (i, c) in step.into_iter().enumerate() {
                out[i].push(c);
            }
        }
        assert_eq!(
            out, panel_expected,
            "panel restore diverged at split {split}"
        );
    }

    // Fail-closed restore rejection without mutating live executor.
    let mut live = expr.event_executor().unwrap();
    live.step(&slice_row(&data, 0)).unwrap();
    live.step(&slice_row(&data, 1)).unwrap();
    let before = live.capture_state();

    let other = FactorExpr::compile("Mean($close, 3)").unwrap();
    let wrong_fp = other.event_executor().unwrap().capture_state();
    assert!(
        live.restore_state(wrong_fp)
            .unwrap_err()
            .to_string()
            .contains("QLIB_STATE_BINDING")
    );
    assert_eq!(live.capture_state(), before);

    let mut truncated = before.clone();
    truncated.operator_states.pop();
    assert!(
        live.restore_state(truncated)
            .unwrap_err()
            .to_string()
            .contains("QLIB_STATE_LAYOUT")
    );
    assert_eq!(live.capture_state(), before);

    // Next step after rejected restores still matches golden.
    let next = live.step(&slice_row(&data, 2)).unwrap();
    assert_eq!(next, expected[2]);
}

#[test]
fn checkpoint_rejects_step_count_desync_and_survives_long_ema_decay_and_extreme_scales() {
    // 1. Truncated window, understated step_count, cross-operator desync, and premature RMA seed.
    let mean_expr = FactorExpr::compile("Mean($close, 5)").unwrap();
    let mut exec = mean_expr.event_executor().unwrap();
    for v in ["10", "11", "12", "13", "14"] {
        exec.step(&BTreeMap::from([("close".to_owned(), Some(dec(v)))]))
            .unwrap();
    }
    let full_state = exec.capture_state();
    // Understated step_count (0 with full 5-row window)
    let mut understated = full_state.clone();
    understated.step_count = 0;
    assert!(
        exec.restore_state(understated)
            .unwrap_err()
            .to_string()
            .contains("QLIB_STATE_INCONSISTENT")
    );
    // Truncated window (step_count = 100 with 1 row)
    let mut truncated = full_state.clone();
    truncated.step_count = 100;
    truncated.operator_states[0][0].truncate(1);
    assert!(
        exec.restore_state(truncated)
            .unwrap_err()
            .to_string()
            .contains("QLIB_STATE_INCONSISTENT")
    );
    // Prematurely seeded RMA at step_count = 2 for period 14
    let rma_expr = FactorExpr::compile("RMA($close, 14)").unwrap();
    let mut rma_exec = rma_expr.event_executor().unwrap();
    let mut bad_rma = rma_exec.capture_state();
    bad_rma.step_count = 2;
    bad_rma.operator_states = vec![vec![vec![Some(dec("1")), Some(dec("100"))]]];
    assert!(
        rma_exec
            .restore_state(bad_rma)
            .unwrap_err()
            .to_string()
            .contains("QLIB_STATE_INCONSISTENT")
    );
    // Cross-operator desync: Mean($close, 3) has 1 row while Mean($close, 5) has 5 rows.
    let dual_expr = FactorExpr::compile("Mean($close, 3) + Mean($close, 5)").unwrap();
    let mut dual_exec = dual_expr.event_executor().unwrap();
    for v in ["10", "11", "12", "13", "14"] {
        dual_exec
            .step(&BTreeMap::from([("close".to_owned(), Some(dec(v)))]))
            .unwrap();
    }
    let mut cross_op = dual_exec.capture_state();
    cross_op.operator_states[0][0].truncate(1);
    assert!(
        dual_exec
            .restore_state(cross_op)
            .unwrap_err()
            .to_string()
            .contains("QLIB_STATE_INCONSISTENT")
    );
    // Cross-instrument desync in PanelEventExecutor.
    let panel_expr = FactorExpr::compile("Rank(Mean($close, 3))").unwrap();
    let mut panel_exec = panel_expr.panel_event_executor(2).unwrap();
    for v in ["10", "11", "12"] {
        panel_exec
            .step(&[
                BTreeMap::from([("close".to_owned(), Some(dec(v)))]),
                BTreeMap::from([("close".to_owned(), Some(dec(v)))]),
            ])
            .unwrap();
    }
    let mut cross_inst = panel_exec.capture_state();
    cross_inst.instrument_states[1][0][0].clear();
    assert!(
        panel_exec
            .restore_state(cross_inst)
            .unwrap_err()
            .to_string()
            .contains("QLIB_STATE_INCONSISTENT")
    );

    // 2. Long EMA(2) zero-decay checkpoint self-recovers through both memory and JSON record.
    let ema_expr = FactorExpr::compile("EMA($close, 2)").unwrap();
    let mut ema_exec = ema_expr.event_executor().unwrap();
    ema_exec
        .step(&BTreeMap::from([("close".to_owned(), Some(dec("1")))]))
        .unwrap();
    for _ in 0..2300 {
        ema_exec
            .step(&BTreeMap::from([("close".to_owned(), Some(dec("0")))]))
            .unwrap();
    }
    let state = ema_exec.capture_state();
    let record = state.to_record();
    let decoded = DagState::from_record(&record).unwrap();
    let mut ema_restored = ema_expr.event_executor().unwrap();
    ema_restored.restore_state(decoded).unwrap();
    assert_eq!(
        ema_restored
            .step(&BTreeMap::from([("close".to_owned(), Some(dec("3")))]))
            .unwrap(),
        Some(dec("2.000000000000"))
    );

    // 3. Valid in-budget extreme-scale decimal (1e-600) round-trips through JSON record.
    let ref_expr = FactorExpr::compile("Ref($close, 2)").unwrap();
    let mut ref_exec = ref_expr.event_executor().unwrap();
    ref_exec
        .step(&BTreeMap::from([("close".to_owned(), Some(dec("1e-600")))]))
        .unwrap();
    let ref_state = ref_exec.capture_state();
    let ref_decoded = DagState::from_record(&ref_state.to_record()).unwrap();
    assert_eq!(ref_decoded, ref_state);
    let mut ref_restored = ref_expr.event_executor().unwrap();
    ref_restored.restore_state(ref_decoded).unwrap();
}

#[test]
fn parser_budgets_canonical_fingerprints_and_syntax_guards() {
    // Whitespace and alias invariance.
    let a = FactorExpr::compile("Mean($close, 20) / Std($close, 20)").unwrap();
    let b =
        FactorExpr::compile("  rolling_mean( $close , 20 ) / rolling_std($close, 20) ").unwrap();
    assert_eq!(a.canonical(), b.canonical());
    assert_eq!(a.fingerprint(), b.fingerprint());

    // Adversarial DAG sharing does not cause exponential canonical formatting blowup.
    let mut nested = "$close".to_owned();
    for _ in 0..8 {
        nested = format!("({nested} + {nested})");
    }
    let shared = FactorExpr::compile(&nested).unwrap();
    assert!(shared.node_count() <= 16);
    assert!(shared.canonical().len() < 1024);

    // Budget and syntax rejections.
    let huge = "1 + ".repeat(MAX_EXPR_BYTES / 3);
    assert!(
        FactorExpr::compile(&huge)
            .unwrap_err()
            .to_string()
            .contains("QLIB_BYTE_BUDGET")
    );

    let deep = format!(
        "{}$close{}",
        "(".repeat(MAX_EXPR_DEPTH + 2),
        ")".repeat(MAX_EXPR_DEPTH + 2)
    );
    assert!(
        FactorExpr::compile(&deep)
            .unwrap_err()
            .to_string()
            .contains("QLIB_DEPTH_BUDGET")
    );

    // Long binary-operator chains MUST also enforce MAX_EXPR_DEPTH instead of recursing deeply.
    let deep_chain = format!("1{}", "+1".repeat(8000));
    assert!(
        FactorExpr::compile(&deep_chain)
            .unwrap_err()
            .to_string()
            .contains("QLIB_DEPTH_BUDGET")
    );

    // PanelEventExecutor::new MUST fail-closed on unbounded instrument_count without panicking.
    let panel_expr = FactorExpr::compile("Rank(Mean($close, 100))").unwrap();
    assert!(
        panel_expr
            .panel_event_executor(usize::MAX)
            .unwrap_err()
            .to_string()
            .contains("QLIB_RESOURCE_BUDGET")
    );
    assert!(
        panel_expr
            .panel_event_executor(50_000)
            .unwrap_err()
            .to_string()
            .contains("QLIB_RESOURCE_BUDGET")
    );

    // ResourceEstimate::stateful_op_count counts only Checkpointable operators.
    let stateless = FactorExpr::compile("($close + $open) * 2").unwrap();
    assert_eq!(stateless.resource_budget().stateful_op_count, 0);
    assert_eq!(stateless.resource_budget().max_state_cells, 0);
    let stateful = FactorExpr::compile("Mean($close, 5) + $open").unwrap();
    assert_eq!(stateful.resource_budget().stateful_op_count, 1);
    assert_eq!(stateful.resource_budget().max_state_cells, 5);

    let invalid_cases = [
        ("", "QLIB_EMPTY_EXPRESSION"),
        ("   ", "QLIB_EMPTY_EXPRESSION"),
        ("$close $open", "QLIB_TRAILING_TOKENS"),
        ("Mean($close, $volume)", "QLIB_CONSTANT_PARAM_REQUIRED"),
        ("Mean($close, 2.5)", "QLIB_INTEGER_PARAM_REQUIRED"),
        ("Mean($close, 0)", "QLIB_INVALID_PARAMETER"),
        ("Eval($close)", "QLIB_UNKNOWN_OPERATOR"),
        ("close", "QLIB_BARE_IDENTIFIER"),
        ("Mean($close)", "QLIB_ARITY"),
        ("($close + 1", "QLIB_UNCLOSED_PAREN"),
        ("$123", "QLIB_INVALID_FIELD"),
        ("1.2.3", "QLIB_INVALID_NUMBER"),
        ("Mean($close, 100001)", "QLIB_WINDOW_BUDGET"),
    ];
    for (source, expected_code) in invalid_cases {
        let err =
            FactorExpr::compile(source).expect_err(&format!("expected failure for `{source}`"));
        assert!(
            err.to_string().contains(expected_code),
            "expected `{expected_code}` for `{source}`, got `{err}`"
        );
    }
}
