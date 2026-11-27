use onlyalpha_calculation::factor_expr::{FactorExpr, PanelDagState};
use onlyalpha_operators::algebra::Decimal;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};

const DEFINITIONS: [&str; 158] = [
    include_str!("../../../examples/factor/qlib/alpha158/KMID.json"),
    include_str!("../../../examples/factor/qlib/alpha158/KLEN.json"),
    include_str!("../../../examples/factor/qlib/alpha158/KMID2.json"),
    include_str!("../../../examples/factor/qlib/alpha158/KUP.json"),
    include_str!("../../../examples/factor/qlib/alpha158/KUP2.json"),
    include_str!("../../../examples/factor/qlib/alpha158/KLOW.json"),
    include_str!("../../../examples/factor/qlib/alpha158/KLOW2.json"),
    include_str!("../../../examples/factor/qlib/alpha158/KSFT.json"),
    include_str!("../../../examples/factor/qlib/alpha158/KSFT2.json"),
    include_str!("../../../examples/factor/qlib/alpha158/OPEN0.json"),
    include_str!("../../../examples/factor/qlib/alpha158/HIGH0.json"),
    include_str!("../../../examples/factor/qlib/alpha158/LOW0.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VWAP0.json"),
    include_str!("../../../examples/factor/qlib/alpha158/ROC5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/ROC10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/ROC20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/ROC30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/ROC60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MA5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MA10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MA20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MA30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MA60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/STD5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/STD10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/STD20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/STD30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/STD60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/BETA5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/BETA10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/BETA20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/BETA30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/BETA60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RSQR5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RSQR10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RSQR20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RSQR30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RSQR60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RESI5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RESI10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RESI20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RESI30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RESI60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MAX5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MAX10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MAX20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MAX30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MAX60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MIN5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MIN10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MIN20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MIN30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/MIN60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/QTLU5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/QTLU10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/QTLU20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/QTLU30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/QTLU60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/QTLD5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/QTLD10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/QTLD20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/QTLD30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/QTLD60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RANK5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RANK10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RANK20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RANK30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RANK60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RSV5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RSV10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RSV20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RSV30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/RSV60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMAX5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMAX10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMAX20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMAX30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMAX60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMIN5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMIN10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMIN20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMIN30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMIN60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMXD5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMXD10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMXD20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMXD30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/IMXD60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CORR5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CORR10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CORR20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CORR30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CORR60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CORD5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CORD10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CORD20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CORD30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CORD60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTP5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTP10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTP20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTP30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTP60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTN5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTN10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTN20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTN30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTN60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTD5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTD10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTD20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTD30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/CNTD60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMP5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMP10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMP20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMP30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMP60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMN5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMN10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMN20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMN30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMN60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMD5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMD10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMD20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMD30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/SUMD60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VMA5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VMA10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VMA20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VMA30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VMA60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSTD5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSTD10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSTD20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSTD30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSTD60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/WVMA5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/WVMA10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/WVMA20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/WVMA30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/WVMA60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMP5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMP10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMP20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMP30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMP60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMN5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMN10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMN20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMN30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMN60.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMD5.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMD10.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMD20.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMD30.json"),
    include_str!("../../../examples/factor/qlib/alpha158/VSUMD60.json"),
];

const PERIODS: usize = 69;
const CHECKPOINT: usize = 61;
type Column = Vec<Option<Decimal>>;
type Instrument = BTreeMap<String, Column>;
type Event = Vec<BTreeMap<String, Option<Decimal>>>;

fn column(values: &Value) -> Column {
    values
        .as_array()
        .unwrap()
        .iter()
        .map(|cell| match cell {
            Value::Null => None,
            Value::String(s) => Some(s.parse().unwrap()),
            _ => panic!("expected a decimal string or null, got {cell}"),
        })
        .collect()
}

fn check_batch(name: &str, expr: &FactorExpr, panel: &[Instrument], golden: &[Column], len: usize) {
    let actual = expr
        .evaluate_panel(panel)
        .unwrap_or_else(|e| panic!("{name} batch prefix {len}: {e}"));
    assert_eq!(actual.len(), golden.len(), "{name} batch instruments");
    for (i, values) in actual.iter().enumerate() {
        assert_eq!(values.len(), len, "{name} batch instrument {i}");
        for (t, value) in values.iter().enumerate() {
            assert_eq!(
                value, &golden[i][t],
                "{name} batch prefix {len}, i={i} t={t}"
            );
        }
    }
}

fn check_events(name: &str, expr: &FactorExpr, events: &[Event], golden: &[Column]) {
    let mut live = expr.panel_event_executor(golden.len()).unwrap();
    let mut resumed = None;
    for (t, event) in events.iter().enumerate() {
        if t == CHECKPOINT {
            let state = live.capture_state().to_record();
            let decoded = PanelDagState::from_record(&state)
                .unwrap_or_else(|e| panic!("{name} checkpoint t={t}: {e}"));
            let mut fresh = expr.panel_event_executor(golden.len()).unwrap();
            fresh
                .restore_state(decoded)
                .unwrap_or_else(|e| panic!("{name} restore t={t}: {e}"));
            resumed = Some(fresh);
        }
        for (mode, executor) in Some(("event", &mut live))
            .into_iter()
            .chain(resumed.as_mut().map(|executor| ("restored", executor)))
        {
            let values = executor
                .step(event)
                .unwrap_or_else(|e| panic!("{name} {mode} t={t}: {e}"));
            assert_eq!(values.len(), golden.len(), "{name} {mode} t={t}");
            for (i, value) in values.iter().enumerate() {
                assert_eq!(value, &golden[i][t], "{name} {mode} i={i} t={t}");
            }
        }
    }
}

#[test]
fn alpha158_public_definitions_match_frozen_decimal_results() {
    let manifest: Value = serde_json::from_str(include_str!(
        "../../../examples/factor/qlib/alpha158/manifest.json"
    ))
    .unwrap();
    assert_eq!(manifest["factor_set"], "onlyalpha.alpha158");
    assert_eq!(manifest["factor_set_version"], "1");
    assert_eq!(manifest["expression_language"], "factor_expr");
    let features = manifest["features"].as_array().unwrap();
    assert_eq!(features.len(), 158);
    let mut records = include_str!("fixtures/alpha158/expected.jsonl")
        .lines()
        .map(|s| serde_json::from_str::<Value>(s).unwrap());
    let header = records.next().unwrap();
    let fields: BTreeSet<_> = ["open", "high", "low", "close", "volume", "vwap"]
        .map(str::to_owned)
        .into_iter()
        .collect();
    let panel: Vec<Instrument> = header["panel"]
        .as_array()
        .unwrap()
        .iter()
        .map(|instrument| {
            let mut columns = Instrument::new();
            for (field, values) in instrument.as_object().unwrap() {
                let values = column(values);
                assert_eq!(values.len(), PERIODS, "{field} fixture length");
                columns.insert(field.clone(), values);
            }
            assert_eq!(columns.keys().cloned().collect::<BTreeSet<_>>(), fields);
            columns
        })
        .collect();
    assert_eq!(panel.len(), 2);
    let events: Vec<Event> = (0..PERIODS)
        .map(|t| {
            panel
                .iter()
                .map(|inst| {
                    inst.iter()
                        .map(|(k, v)| (k.clone(), v[t].clone()))
                        .collect()
                })
                .collect()
        })
        .collect();
    let prefixes = [5, 60, 66].map(|len| {
        let prefix: Vec<Instrument> = panel
            .iter()
            .map(|inst| {
                inst.iter()
                    .map(|(k, v)| (k.clone(), v[..len].to_vec()))
                    .collect()
            })
            .collect();
        (len, prefix)
    });
    let mut filenames = BTreeSet::new();
    for (item, definition) in features.iter().zip(DEFINITIONS) {
        let record = records.next().expect("missing Alpha158 golden");
        let name = record["name"].as_str().unwrap();
        let file = item["file"].as_str().unwrap();
        assert_eq!(file, format!("{name}.json"), "manifest order or filename");
        assert!(filenames.insert(file.to_owned()), "duplicate {file}");
        let hash: String = Sha256::digest(definition.as_bytes())
            .iter()
            .map(|b| format!("{b:02x}"))
            .collect();
        assert_eq!(
            item["sha256"].as_str(),
            Some(hash.as_str()),
            "{name} SHA-256"
        );
        let factor: Value = serde_json::from_str(definition).unwrap();
        assert_eq!(factor["factor_set"], manifest["factor_set"], "{name}");
        assert_eq!(
            factor["factor_set_version"], manifest["factor_set_version"],
            "{name}"
        );
        assert_eq!(factor["name"], name);
        let expr = FactorExpr::compile_with_allowed_fields(
            factor["expression"].as_str().unwrap(),
            &fields,
        )
        .unwrap_or_else(|e| panic!("{name} compile: {e}"));
        let golden: Vec<_> = record["values"]
            .as_array()
            .unwrap()
            .iter()
            .map(column)
            .collect();
        assert_eq!(golden.len(), panel.len(), "{name}");
        assert!(
            golden.iter().all(|values| values.len() == PERIODS),
            "{name}"
        );
        assert!(
            golden[0][60..].iter().all(Option::is_some),
            "{name} incomplete warm fixture"
        );
        check_batch(name, &expr, &panel, &golden, PERIODS);
        for (len, prefix) in &prefixes {
            check_batch(name, &expr, prefix, &golden, *len);
        }
        check_events(name, &expr, &events, &golden);
    }
    assert!(records.next().is_none(), "unexpected additional golden");
}
