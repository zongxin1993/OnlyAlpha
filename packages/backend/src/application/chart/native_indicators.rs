//! Rust-owned registration and execution for versioned fixed-scale indicators.

use super::{
    ChartQuery, Definition, Entry, Error, Result, TypeDeclaration, WORK, fp, manifest, remaining,
    text,
};
use bigdecimal::BigDecimal;
use onlyalpha_indicators::{
    ATR, Bollinger, EMA, FinancialValue, MACD, MACDCross, OBV, ROC, RSI, RSIZone,
    RollingVolatility, SMA, Stochastic, UtcSessionVWAP, WMA, ZScore,
};
use serde_json::{Map, Value, json};
use std::{num::NonZeroUsize, time::Instant};

#[derive(Clone, Copy, PartialEq, Eq)]
#[allow(clippy::upper_case_acronyms)]
pub(super) enum Indicator {
    SMA,
    WMA,
    ROC,
    RollingReturn,
    EMA,
    RSI,
    ATR,
    MACD,
    Bollinger,
    RollingVolatility,
    ZScore,
    OBV,
    VWAP,
    Stochastic,
}

impl Indicator {
    pub(super) const ALL: [Self; 14] = [
        Self::SMA,
        Self::WMA,
        Self::ROC,
        Self::RollingReturn,
        Self::EMA,
        Self::RSI,
        Self::ATR,
        Self::MACD,
        Self::Bollinger,
        Self::RollingVolatility,
        Self::ZScore,
        Self::OBV,
        Self::VWAP,
        Self::Stochastic,
    ];

    fn identity(self) -> (&'static str, &'static str, &'static str, &'static str) {
        match self {
            Self::SMA => (
                SMA::TYPE_ID,
                SMA::SEMANTIC_VERSION,
                "SMA",
                "onlyalpha_indicators::SMA",
            ),
            Self::WMA => (
                WMA::TYPE_ID,
                WMA::SEMANTIC_VERSION,
                "WMA",
                "onlyalpha_indicators::WMA",
            ),
            Self::ROC => (
                "onlyalpha.indicator.roc",
                "2",
                "ROC",
                "onlyalpha_indicators::ROC",
            ),
            Self::RollingReturn => (
                "onlyalpha.indicator.rolling_return",
                "2",
                "滚动收益率",
                "onlyalpha_indicators::ROC",
            ),
            Self::EMA => (
                "onlyalpha.indicator.ema",
                "2",
                "EMA",
                "onlyalpha_indicators::EMA",
            ),
            Self::RSI => (
                "onlyalpha.indicator.rsi",
                "3",
                "RSI",
                "onlyalpha_indicators::RSI",
            ),
            Self::ATR => (
                "onlyalpha.indicator.atr",
                "4",
                "ATR",
                "onlyalpha_indicators::ATR",
            ),
            Self::MACD => (
                "onlyalpha.indicator.macd",
                "3",
                "MACD",
                "onlyalpha_indicators::MACD",
            ),
            Self::Bollinger => (
                "onlyalpha.indicator.bollinger",
                "2",
                "布林带",
                "onlyalpha_indicators::Bollinger",
            ),
            Self::RollingVolatility => (
                "onlyalpha.indicator.rolling_volatility",
                "2",
                "价格波动率",
                "onlyalpha_indicators::RollingVolatility",
            ),
            Self::ZScore => (
                "onlyalpha.indicator.zscore",
                "2",
                "Z-Score",
                "onlyalpha_indicators::ZScore",
            ),
            Self::OBV => (
                "onlyalpha.indicator.obv",
                "2",
                "OBV",
                "onlyalpha_indicators::OBV",
            ),
            Self::VWAP => (
                "onlyalpha.indicator.vwap",
                "3",
                "VWAP · UTC交易日",
                "onlyalpha_indicators::UtcSessionVWAP",
            ),
            Self::Stochastic => (
                "onlyalpha.indicator.stochastic",
                "3",
                "Stochastic · 慢速",
                "onlyalpha_indicators::Stochastic::slow",
            ),
        }
    }

    fn from_record(record: &Value) -> Option<Self> {
        Self::ALL.into_iter().find(|indicator| {
            let (type_id, version, _, _) = indicator.identity();
            record["type_id"] == type_id && record["semantic_version"] == version
        })
    }

    fn partial(self) -> bool {
        matches!(
            self,
            Self::SMA
                | Self::EMA
                | Self::MACD
                | Self::Bollinger
                | Self::RollingVolatility
                | Self::ZScore
        )
    }

    fn overlay(self) -> bool {
        matches!(
            self,
            Self::SMA | Self::WMA | Self::EMA | Self::Bollinger | Self::VWAP
        )
    }

    fn unit(self) -> &'static str {
        match self {
            Self::ROC | Self::RollingReturn => "RATIO",
            Self::RSI | Self::ZScore | Self::Stochastic => "SCALAR",
            Self::OBV => "VOLUME",
            _ => "PRICE",
        }
    }

    fn inputs(self) -> &'static [&'static str] {
        match self {
            Self::ATR | Self::Stochastic => &["close", "high", "low"],
            Self::VWAP => &["close", "high", "low", "start_ns", "volume"],
            Self::OBV => &["close", "volume"],
            _ => &["value"],
        }
    }

    fn outputs(self) -> &'static [(&'static str, &'static str, bool, bool)] {
        // Name, data type, nullable, and chart visibility.
        match self {
            Self::ROC => &[("roc", "DECIMAL", true, true)],
            Self::WMA | Self::RollingReturn => &[("value", "DECIMAL", true, true)],
            Self::RSI => &[
                ("value", "DECIMAL", true, true),
                ("zone", "STRING", false, false),
            ],
            Self::ATR => &[
                ("atr", "DECIMAL", true, true),
                ("normalized_atr", "DECIMAL", true, false),
            ],
            Self::MACD => &[
                ("dif", "DECIMAL", false, true),
                ("dea", "DECIMAL", false, true),
                ("histogram", "DECIMAL", false, true),
                ("cross_state", "STRING", false, false),
            ],
            Self::Bollinger => &[
                ("middle", "DECIMAL", false, true),
                ("upper", "DECIMAL", false, true),
                ("lower", "DECIMAL", false, true),
            ],
            Self::OBV => &[("obv", "DECIMAL", true, true)],
            Self::VWAP => &[("vwap", "DECIMAL", true, true)],
            Self::Stochastic => &[("k", "DECIMAL", true, true), ("d", "DECIMAL", true, true)],
            _ => &[("value", "DECIMAL", false, true)],
        }
    }

    fn parameters(self) -> Vec<Value> {
        let integers: &[(&str, u64)] = match self {
            Self::OBV | Self::VWAP => &[],
            Self::Stochastic => &[("k_period", 14), ("smooth_k", 3), ("d_period", 3)],
            Self::MACD => &[
                ("fast_period", 12),
                ("slow_period", 26),
                ("signal_period", 9),
                ("warmup_bars", 34),
            ],
            Self::RSI | Self::ATR => &[("period", 14)],
            _ => &[("period", 20)],
        };
        let mut parameters = integers.iter().map(|(name, default)| {
            json!({"name":name,"parameter_type":"INTEGER","required":false,"default":default,"minimum":1,"maximum":10000,"enum_values":[],"uppercase":false})
        }).collect::<Vec<_>>();
        if self.inputs() == ["value"] {
            parameters.push(json!({"name":"price_field","parameter_type":"STRING","required":false,"default":"CLOSE","minimum":null,"maximum":null,"enum_values":["CLOSE"],"uppercase":true}));
        }
        if self == Self::Bollinger {
            parameters.push(json!({"name":"standard_deviations","parameter_type":"DECIMAL","required":false,"default":"2","minimum":"0.000000000001","maximum":null,"enum_values":[],"uppercase":false}));
        }
        parameters
    }
}

fn typed_value(kind: &Value, value: &Value) -> Value {
    json!({"type":if value.is_null() { json!("NULL") } else { kind.clone() },"value":value})
}

fn port(name: &str, data_type: &str, nullable: bool) -> Value {
    json!({"name":name,"data_type":data_type,"nullable":nullable,"dimensions":["TIME"],"semantic_type":"SCALAR","unit":null})
}

pub(super) fn entry(invocation: &Value, indicator: Indicator) -> Result<((String, String), Entry)> {
    let (type_id, version, label, implementation_entrypoint) = indicator.identity();
    let quantum = "0.000000000001";
    let numeric = json!({"representation":"DECIMAL","precision":38,"output_quantum":quantum,"rounding":"ROUND_HALF_EVEN"});
    let parameters = indicator.parameters();
    let defaults = parameters
        .iter()
        .map(|p| (p["name"].as_str().unwrap().to_owned(), p["default"].clone()))
        .collect::<Map<_, _>>();
    let parameter_values = parameters.iter().map(|p| {
        let kind = &p["parameter_type"];
        let choices = p["enum_values"].as_array().unwrap().iter().map(|v| typed_value(kind, v)).collect::<Vec<_>>();
        json!({"default":typed_value(kind,&p["default"]),"minimum":typed_value(kind,&p["minimum"]),"maximum":typed_value(kind,&p["maximum"]),"enum_values":choices})
    }).collect::<Vec<_>>();
    let inputs = indicator
        .inputs()
        .iter()
        .map(|name| {
            port(
                name,
                if *name == "start_ns" {
                    "INTEGER"
                } else {
                    "DECIMAL"
                },
                false,
            )
        })
        .collect::<Vec<_>>();
    let outputs = indicator
        .outputs()
        .iter()
        .map(|(name, data_type, nullable, _)| port(name, data_type, *nullable))
        .collect::<Vec<_>>();
    let bounds = indicator
        .outputs()
        .iter()
        .map(|(name, _, _, _)| ((*name).into(), Value::Null))
        .collect::<Map<_, _>>();
    let descriptor = json!({"kind":"INDICATOR","type_id":type_id,"semantic_version":version,"parameters":parameters,"inputs":inputs,"outputs":outputs,"missing_values":"FAIL","timestamp":"EVENT_TIME","numeric":numeric,"factor_kind":null,"execution_shape":"TIME_SERIES","semantic_bounds":bounds});
    let declaration = TypeDeclaration::from_record(
        &json!({
            "schema_version":1,"descriptor":descriptor,"parameter_values":parameter_values,
        }),
        WORK,
    )
    .map_err(|_| Error::Unavailable)?;
    let core_policy = json!({"domain":"onlyalpha.decimal.fixed-scale","schema_version":1,"output_quantum":quantum});
    let policy_fingerprint = fp(&core_policy)?;
    let implementation = manifest(
        json!({"kind":"INDICATOR","type_id":type_id,"semantic_version":version}),
        invocation["resources"].clone(),
        json!([{"dependency_id":"onlyalpha.decimal.fixed-scale","semantic_version":"1","artifact_fingerprint":policy_fingerprint}]),
        implementation_entrypoint,
    )?;
    let numeric_binding = json!({"domain":"onlyalpha.chart-study.decimal-binding","schema_version":1,"resolution_policy":"FIXED_SCALE_HALF_EVEN_V1","declared_rounding":"ROUND_HALF_EVEN","effective_rounding":"ROUND_HALF_EVEN","representation":"DECIMAL","precision":38,"output_quantum":quantum,"core_policy":core_policy,"core_policy_fingerprint":policy_fingerprint});
    let provider = json!({"schema_version":1,"provider_id":"onlyalpha.indicator.native","provider_version":env!("CARGO_PKG_VERSION"),"kind":"INDICATOR","source":{"kind":"NATIVE_DISTRIBUTION","distribution_name":"onlyalpha-backend","distribution_version":env!("CARGO_PKG_VERSION")}});
    let colors = ["#2962ff", "#f59e0b", "#14b8a6"];
    let mut members = Vec::new();
    let series = indicator.outputs().iter().filter(|(_, _, _, visible)| *visible).enumerate().map(|(index, (name, _, _, _))| {
        members.push((*name).into());
        json!({"output_name":name,"label":if matches!(indicator, Indicator::MACD | Indicator::Stochastic) { name.to_ascii_uppercase() } else { label.to_owned() },"kind":if *name == "histogram" {"HISTOGRAM"} else {"LINE"},"unit":indicator.unit(),"color":colors[index],"default_visible":true})
    }).collect::<Vec<_>>();
    let support = json!({
        "display_name":label,
        "category":if indicator.overlay() {"趋势"} else {"动量 / 波动"},
        "default_parameters":defaults,"series":series,
        "placement":if indicator.overlay() {"PRICE_OVERLAY"} else {"SEPARATE_PANE"},
        "fill":if indicator == Indicator::Bollinger { json!(["upper","lower"]) } else { Value::Null },
        "preview_supported":true,"default_variant":true
    });
    let row = json!({"descriptor":descriptor,"implementation":implementation,"implementation_fingerprint":implementation["implementation_fingerprint"],"numeric_binding":numeric_binding,"support":support});
    let content = fp(
        &json!({"provider_manifest":provider,"registration":row,"declaration":declaration.to_record()}),
    )?;
    let generation = fp(&json!({"domain":"onlyalpha.chart.installed-catalog","provider":content}))?;
    let capability = ChartQuery::project_capability(
        invocation,
        &row,
        &provider,
        &content,
        &generation,
        &members,
    )?;
    Ok((
        (type_id.into(), version.into()),
        Entry {
            declaration,
            capability,
        },
    ))
}

pub(super) fn resolve(entry: &Entry, parameters: &Value) -> Result<Definition> {
    let descriptor = entry.declaration.descriptor();
    let indicator = Indicator::from_record(&descriptor).ok_or(Error::Unavailable)?;
    let mut typed = Map::new();
    for spec in indicator.parameters() {
        let name = spec["name"].as_str().ok_or(Error::Unavailable)?;
        let raw = parameters.get(name).unwrap_or(&spec["default"]);
        let value = if spec["uppercase"] == true {
            json!(raw.as_str().ok_or(Error::Invalid)?.to_ascii_uppercase())
        } else {
            raw.clone()
        };
        typed.insert(name.into(), typed_value(&spec["parameter_type"], &value));
    }
    if indicator == Indicator::MACD && parameters.get("warmup_bars").is_none() {
        let warmup = period_value(&typed, "slow_period").ok_or(Error::Invalid)?
            + period_value(&typed, "signal_period").ok_or(Error::Invalid)?
            - 1;
        typed.insert(
            "warmup_bars".into(),
            json!({"type":"INTEGER","value":warmup}),
        );
    }
    let get = |name| period_value(&typed, name).ok_or(Error::Invalid);
    let minimum_observations = match indicator {
        Indicator::OBV | Indicator::VWAP => 1,
        Indicator::Stochastic => get("k_period")? + get("smooth_k")? + get("d_period")? - 2,
        Indicator::MACD => {
            let slow = get("slow_period")?;
            let warmup = get("warmup_bars")?;
            if get("fast_period")? >= slow || warmup < slow {
                return Err(Error::Invalid);
            }
            warmup
        }
        Indicator::ROC | Indicator::RollingReturn | Indicator::RSI => get("period")? + 1,
        _ => get("period")?,
    };
    if minimum_observations > 10000 {
        return Err(Error::Invalid);
    }
    if indicator == Indicator::Bollinger {
        let multiplier = typed["standard_deviations"]["value"]
            .as_str()
            .ok_or(Error::Invalid)?;
        Bollinger::new(
            NonZeroUsize::MIN,
            &source_decimal(multiplier).map_err(|_| Error::Invalid)?,
        )
        .map_err(|_| Error::Invalid)?;
    }
    let mut bindings = Map::new();
    for &name in indicator.inputs() {
        let source = match (
            name,
            typed.get("price_field").and_then(|v| v["value"].as_str()),
        ) {
            ("value", Some("CLOSE")) => "bar.close".to_owned(),
            ("value", _) => return Err(Error::Invalid),
            _ => format!("bar.{name}"),
        };
        bindings.insert(
            name.into(),
            json!({"node_fingerprint":null,"output_name":name,"source":source}),
        );
    }
    let candidate = json!({
        "schema_version":2,"kind":descriptor["kind"],"type_id":descriptor["type_id"],"semantic_version":descriptor["semantic_version"],
        "parameters":typed,"inputs":descriptor["inputs"],"input_bindings":bindings,
        "outputs":descriptor["outputs"],"warmup":{"minimum_observations":minimum_observations,"ready_condition":"samples >= minimum_observations","pre_ready_output":if indicator.partial() {"PARTIAL"} else {"NULL"},"initialization":if matches!(indicator, Indicator::EMA | Indicator::MACD) {"FIRST_VALUE_EMA_SEED"} else {"PARTIAL_WINDOW"}},
        "missing_values":descriptor["missing_values"],"timestamp":descriptor["timestamp"],"numeric":descriptor["numeric"],"factor_kind":null,"extensions":{}
    });
    entry
        .declaration
        .validate_candidate(&candidate, WORK)
        .map_err(|_| Error::Invalid)
}

fn period_value(parameters: &Map<String, Value>, name: &str) -> Option<usize> {
    parameters.get(name)?["value"]
        .as_u64()
        .filter(|value| (1..=10000).contains(value))
        .map(|value| value as usize)
}

#[allow(clippy::upper_case_acronyms)]
enum Kernel {
    SMA(SMA),
    WMA(WMA),
    Lagged(ROC),
    EMA(EMA),
    RSI(RSI),
    ATR(ATR),
    MACD(MACD),
    Bollinger(Bollinger),
    RollingVolatility(RollingVolatility),
    ZScore(ZScore),
    OBV(OBV),
    VWAP(UtcSessionVWAP),
    Stochastic(Stochastic),
}

fn calculation_error<T>(value: std::result::Result<T, impl std::error::Error>) -> Result<T> {
    value.map_err(|_| Error::Unavailable)
}

impl Kernel {
    fn new(indicator: Indicator, definition: &Value) -> Result<Self> {
        let parameters = definition["parameters"]
            .as_object()
            .ok_or(Error::Unavailable)?;
        let period = |name| {
            period_value(parameters, name)
                .and_then(NonZeroUsize::new)
                .ok_or(Error::Unavailable)
        };
        Ok(match indicator {
            Indicator::SMA => Self::SMA(SMA::new(period("period")?)),
            Indicator::WMA => Self::WMA(WMA::new(period("period")?)),
            Indicator::ROC | Indicator::RollingReturn => Self::Lagged(ROC::new(period("period")?)),
            Indicator::EMA => Self::EMA(EMA::new(period("period")?)),
            Indicator::RSI => Self::RSI(RSI::new(period("period")?)),
            Indicator::ATR => Self::ATR(ATR::new(period("period")?)),
            Indicator::MACD => Self::MACD(
                MACD::new(
                    period("fast_period")?,
                    period("slow_period")?,
                    period("signal_period")?,
                )
                .ok_or(Error::Unavailable)?,
            ),
            Indicator::Bollinger => Self::Bollinger(calculation_error(Bollinger::new(
                period("period")?,
                &source_decimal(text(&parameters["standard_deviations"]["value"])?)?,
            ))?),
            Indicator::RollingVolatility => {
                Self::RollingVolatility(RollingVolatility::new(period("period")?))
            }
            Indicator::ZScore => Self::ZScore(ZScore::new(period("period")?)),
            Indicator::OBV => Self::OBV(OBV::new()),
            Indicator::VWAP => Self::VWAP(UtcSessionVWAP::new()),
            Indicator::Stochastic => Self::Stochastic(Stochastic::slow(
                period("k_period")?,
                period("smooth_k")?,
                period("d_period")?,
            )),
        })
    }

    fn push(&mut self, input: &[String], ready: bool) -> Result<Vec<Sample>> {
        let sample = |value| Sample::reported(Some(value), ready);
        let [first, ..] = input else {
            return Err(Error::Unavailable);
        };
        Ok(match self {
            Self::SMA(kernel) => vec![sample(calculation_error(kernel.push(first))?.value)],
            Self::WMA(kernel) => vec![Sample::reported(
                calculation_error(kernel.push(first))?,
                ready,
            )],
            Self::Lagged(kernel) => vec![Sample::reported(
                calculation_error(kernel.push(Some(first)))?,
                ready,
            )],
            Self::EMA(kernel) => vec![sample(calculation_error(kernel.push(first))?.value)],
            Self::RSI(kernel) => {
                let point = calculation_error(kernel.push(first))?;
                let zone = match point.zone {
                    RSIZone::Oversold => "OVERSOLD",
                    RSIZone::Neutral => "NEUTRAL",
                    RSIZone::Overbought => "OVERBOUGHT",
                };
                vec![Sample::financial(point.value)?, sample(zone.into())]
            }
            Self::ATR(kernel) => {
                let [close, high, low] = input else {
                    return Err(Error::Unavailable);
                };
                let point = calculation_error(kernel.push(high, low, close))?;
                vec![
                    Sample::financial(point.atr)?,
                    Sample::financial(point.normalized_atr)?,
                ]
            }
            Self::MACD(kernel) => {
                let point = calculation_error(kernel.push(first))?;
                let cross = match point.cross {
                    MACDCross::None => "NONE",
                    MACDCross::Golden => "GOLDEN_CROSS",
                    MACDCross::Death => "DEATH_CROSS",
                };
                vec![
                    sample(point.dif),
                    sample(point.dea),
                    sample(point.histogram),
                    sample(cross.into()),
                ]
            }
            Self::Bollinger(kernel) => {
                let point = calculation_error(kernel.push(first))?;
                vec![
                    sample(point.middle),
                    sample(point.upper),
                    sample(point.lower),
                ]
            }
            Self::RollingVolatility(kernel) => {
                vec![sample(calculation_error(kernel.push(first))?.value)]
            }
            Self::ZScore(kernel) => vec![sample(calculation_error(kernel.push(first))?.value)],
            Self::OBV(kernel) => {
                let [close, volume] = input else {
                    return Err(Error::Unavailable);
                };
                vec![Sample::financial(calculation_error(
                    kernel.push(Some(close), Some(volume)),
                )?)?]
            }
            Self::VWAP(kernel) => {
                let [close, high, low, start_ns, volume] = input else {
                    return Err(Error::Unavailable);
                };
                let start_ns = start_ns.parse().map_err(|_| Error::Unavailable)?;
                vec![Sample::financial(calculation_error(
                    kernel.push(start_ns, high, low, close, volume),
                )?)?]
            }
            Self::Stochastic(kernel) => {
                let [close, high, low] = input else {
                    return Err(Error::Unavailable);
                };
                let point = calculation_error(kernel.push(Some(high), Some(low), Some(close)))?;
                vec![Sample::financial(point.k)?, Sample::financial(point.d)?]
            }
        })
    }
}

struct Sample {
    value: Option<String>,
    state: &'static str,
    reason: &'static str,
}

impl Sample {
    fn reported(value: Option<String>, ready: bool) -> Self {
        let (state, reason) = match (ready, value.is_some()) {
            (false, _) => ("PARTIAL", "WARMUP_INCOMPLETE"),
            (true, true) => ("READY", "NONE"),
            (true, false) => ("READY", "VALUE_UNDEFINED"),
        };
        Self {
            value,
            state,
            reason,
        }
    }

    fn financial(value: FinancialValue) -> Result<Self> {
        Ok(match value {
            FinancialValue::Warmup => Self::reported(None, false),
            FinancialValue::Undefined => Self::reported(None, true),
            FinancialValue::Ready(value) => Self::reported(Some(value), true),
            FinancialValue::Missing | FinancialValue::OutOfRange => return Err(Error::Unavailable),
        })
    }
}

#[derive(Default, serde::Serialize)]
struct Output {
    values: Vec<Option<String>>,
    states: Vec<&'static str>,
    reasons: Vec<&'static str>,
}

fn evaluate(definition: &Value, columns: &Map<String, Value>, end: Instant) -> Result<Value> {
    let indicator = Indicator::from_record(definition).ok_or(Error::Unavailable)?;
    let mut kernel = Kernel::new(indicator, definition)?;
    let minimum = definition["warmup"]["minimum_observations"]
        .as_u64()
        .ok_or(Error::Unavailable)?;
    let inputs = indicator
        .inputs()
        .iter()
        .map(|name| {
            columns
                .get(*name)
                .and_then(Value::as_array)
                .map(|column| (*name, column))
                .ok_or(Error::Unavailable)
        })
        .collect::<Result<Vec<_>>>()?;
    let count = inputs.first().ok_or(Error::Unavailable)?.1.len();
    if count > 2001 || inputs.iter().any(|(_, column)| column.len() != count) {
        return Err(Error::Unavailable);
    }
    let mut outputs = indicator
        .outputs()
        .iter()
        .map(|(name, _, _, _)| (*name, Output::default()))
        .collect::<Vec<_>>();
    for index in 0..count {
        remaining(end)?;
        let row = inputs
            .iter()
            .map(|(name, column)| {
                if *name == "start_ns" {
                    column[index]
                        .as_u64()
                        .map(|value| value.to_string())
                        .ok_or(Error::Unavailable)
                } else {
                    source_decimal(text(&column[index])?)
                }
            })
            .collect::<Result<Vec<_>>>()?;
        let samples = kernel.push(&row, (index as u64 + 1) >= minimum)?;
        if samples.len() != outputs.len() {
            return Err(Error::Unavailable);
        }
        for ((_, output), sample) in outputs.iter_mut().zip(samples) {
            output.values.push(sample.value);
            output.states.push(sample.state);
            output.reasons.push(sample.reason);
        }
    }
    remaining(end)?;
    serde_json::to_value(
        outputs
            .into_iter()
            .collect::<std::collections::BTreeMap<_, _>>(),
    )
    .map_err(|_| Error::Unavailable)
}

fn source_decimal(value: &str) -> Result<String> {
    let decimal = value
        .parse::<BigDecimal>()
        .map_err(|_| Error::Unavailable)?
        .normalized();
    let (coefficient, scale) = decimal.as_bigint_and_exponent();
    if !(-25..=12).contains(&scale)
        || coefficient.to_str_radix(10).trim_start_matches('-').len() as i64 - scale > 26
    {
        return Err(Error::Unavailable);
    }
    Ok(decimal.to_plain_string())
}

pub(super) fn worker_invocation(mut executable: &std::fs::File) -> Result<Value> {
    use sha2::{Digest, Sha256};
    use std::io::Read;

    let mut digest = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = executable
            .read(&mut buffer)
            .map_err(|_| Error::Unavailable)?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    let digest = digest
        .finalize()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    manifest(
        json!({"kind":"INDICATOR","type_id":"onlyalpha.chart-study.invocation","semantic_version":"5"}),
        json!([{"relative_path":"native-product-executable","byte_sha256":digest}]),
        json!([{"dependency_id":"onlyalpha.indicator.native","semantic_version":"1","artifact_fingerprint":digest}]),
        "onlyalpha_backend::application::chart::run_native_worker",
    )
}

type Entries = std::collections::BTreeMap<(String, String), Entry>;

pub(super) fn entries(invocation: &Value) -> Result<Entries> {
    Indicator::ALL
        .into_iter()
        .map(|indicator| entry(invocation, indicator))
        .collect()
}

pub(super) fn catalog(entries: &Entries) -> Value {
    json!({"schema_version":1,"isolation":super::worker_sandbox::POLICY,"capabilities":entries.values().map(|entry| &entry.capability).collect::<Vec<_>>()})
}

/// Private process entrypoint. It receives only authorized, bounded input
/// columns and has no Product session, database configuration, or Source grant.
pub fn run_worker() -> Result<()> {
    let executable = std::fs::File::open("/proc/self/exe").map_err(|_| Error::Unavailable)?;
    let invocation = worker_invocation(&executable)?;
    drop(executable);
    limit_worker()?;
    super::worker_sandbox::restrict()?;
    let artifact = text(&invocation["resources"][0]["byte_sha256"])?;
    let entries = entries(&invocation)?;
    let observed = catalog(&entries);
    onlyalpha_calculation_bridge::serve_chart(
        &mut std::io::stdin().lock(),
        &mut std::io::stdout().lock(),
        artifact,
        |request| {
            if request == json!({"op":"CATALOG"}) {
                return Some(observed.clone());
            }
            super::exact(
                &request,
                &[
                    "op",
                    "type_id",
                    "semantic_version",
                    "parameters",
                    "implementation_fingerprint",
                    "inputs",
                    "input_fingerprint",
                ],
            )
            .ok()?;
            if request["op"] != "EXECUTE" {
                return None;
            }
            let key = (
                request["type_id"].as_str()?.into(),
                request["semantic_version"].as_str()?.into(),
            );
            let entry = entries.get(&key)?;
            if request["implementation_fingerprint"]
                != entry.capability["implementation_fingerprint"]
            {
                return None;
            }
            super::sha(&request["input_fingerprint"]).ok()?;
            let definition = resolve(entry, &request["parameters"]).ok()?;
            let record = definition.to_record();
            let outputs = evaluate(
                &record,
                request["inputs"].as_object()?,
                Instant::now() + std::time::Duration::from_secs(10),
            )
            .ok()?;
            Some(json!({
                "type_declaration":entry.declaration.to_record(),
                "artifact_fingerprint":artifact,
                "input_fingerprint":request["input_fingerprint"],
                "definition":record,
                "definition_fingerprint":definition.fingerprint(),
                "implementation_fingerprint":entry.capability["implementation_fingerprint"],
                "outputs":outputs
            }))
        },
    )
    .map_err(|_| Error::Unavailable)
}

#[cfg(target_os = "linux")]
fn limit_worker() -> Result<()> {
    use rustix::process::{Resource, Rlimit, getrlimit, setrlimit};

    for (resource, limit) in [
        (Resource::Cpu, 10),
        (Resource::As, 512 * 1024 * 1024),
        (Resource::Core, 0),
        (Resource::Fsize, 0),
        (Resource::Nofile, 3),
        (Resource::Nproc, 1),
    ] {
        let limit = getrlimit(resource)
            .maximum
            .map_or(limit, |maximum| maximum.min(limit));
        setrlimit(
            resource,
            Rlimit {
                current: Some(limit),
                maximum: Some(limit),
            },
        )
        .map_err(|_| Error::Unavailable)?;
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn limit_worker() -> Result<()> {
    Err(Error::Unavailable)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn each_native_family_projects_and_executes_its_declared_outputs() {
        let invocation = manifest(
            json!({"kind":"INDICATOR","type_id":"onlyalpha.chart-study.invocation","semantic_version":"3"}),
            json!([{"relative_path":"native-product-executable","byte_sha256":"a".repeat(64)}]),
            json!([]),
            "chart fixture",
        ).unwrap();
        let deadline = Instant::now() + std::time::Duration::from_secs(10);
        let mut keys = std::collections::BTreeSet::new();
        for indicator in Indicator::ALL {
            let (key, entry) = entry(&invocation, indicator).unwrap();
            assert!(keys.insert(key.clone()));
            serde_json::from_value::<crate::transport::wire::ChartStudyCapabilityDto>(
                entry.capability.clone(),
            )
            .unwrap_or_else(|error| panic!("{key:?}: {error}"));
            let definition = resolve(&entry, &json!({})).unwrap().to_record();
            let columns = indicator
                .inputs()
                .iter()
                .map(|&name| {
                    let values = (0..64)
                        .map(|index| match name {
                            "start_ns" => json!(index * 60_000_000_000_u64),
                            "high" => json!((index + 3).to_string()),
                            "low" => json!((index + 1).to_string()),
                            _ => json!((index + 2).to_string()),
                        })
                        .collect::<Vec<_>>();
                    (name.into(), json!(values))
                })
                .collect::<Map<_, _>>();
            let result = evaluate(&definition, &columns, deadline).unwrap();
            super::super::validate_outputs(&definition, &result, 64).unwrap();
            for member in entry.capability["output_members"].as_array().unwrap() {
                let output = member.as_str().unwrap();
                assert_eq!(result[output]["states"][63], "READY", "{key:?}/{output}");
                assert!(result[output]["values"][63].is_string(), "{key:?}/{output}");
            }
        }
        assert_eq!(keys.len(), 14);
    }

    #[test]
    fn lagged_registrations_have_distinct_identities_and_report_undefined_reference() {
        let invocation = manifest(
            json!({"kind":"INDICATOR","type_id":"onlyalpha.chart-study.invocation","semantic_version":"3"}),
            json!([{"relative_path":"native-product-executable","byte_sha256":"a".repeat(64)}]),
            json!([]),
            "chart fixture",
        ).unwrap();
        let (_, roc) = entry(&invocation, Indicator::ROC).unwrap();
        let (_, rolling_return) = entry(&invocation, Indicator::RollingReturn).unwrap();
        assert_ne!(
            roc.capability["implementation_fingerprint"],
            rolling_return.capability["implementation_fingerprint"]
        );
        for (entry, output) in [(roc, "roc"), (rolling_return, "value")] {
            serde_json::from_value::<crate::transport::wire::ChartStudyCapabilityDto>(
                entry.capability.clone(),
            )
            .unwrap();
            let definition = resolve(&entry, &json!({"period":2})).unwrap().to_record();
            assert_eq!(definition["warmup"]["minimum_observations"], 3);
            assert!(resolve(&entry, &json!({"period":9999})).is_ok());
            assert!(resolve(&entry, &json!({"period":10000})).is_err());
            assert!(resolve(&entry, &json!({"price_field":"VOLUME"})).is_err());
            let columns = json!({"value":["4","0","5","7"]});
            let deadline = Instant::now() + std::time::Duration::from_secs(10);
            let result = evaluate(&definition, columns.as_object().unwrap(), deadline).unwrap();
            super::super::validate_outputs(&definition, &result, 4).unwrap();
            assert_eq!(
                result[output],
                json!({
                    "values":[null,null,"0.250000000000",null],
                    "states":["PARTIAL","PARTIAL","READY","READY"],
                    "reasons":["WARMUP_INCOMPLETE","WARMUP_INCOMPLETE","NONE","VALUE_UNDEFINED"]
                })
            );
        }
    }

    #[test]
    fn exact_native_registration_resolves_parameters_and_executes() {
        let invocation = manifest(
            json!({"kind":"INDICATOR","type_id":"onlyalpha.chart-study.invocation","semantic_version":"3"}),
            json!([{"relative_path":"native-product-executable","byte_sha256":"a".repeat(64)}]),
            json!([]),
            "chart fixture",
        ).unwrap();
        let (key, entry) = entry(&invocation, Indicator::SMA).unwrap();
        assert_eq!(key, ("onlyalpha.indicator.sma".into(), "2".into()));
        serde_json::from_value::<crate::transport::wire::ChartStudyCapabilityDto>(
            entry.capability.clone(),
        )
        .unwrap();
        let mut invalid_binding = entry.capability["numeric_execution_binding"].clone();
        invalid_binding["precision"] = json!(28);
        assert!(
            serde_json::from_value::<crate::transport::wire::ChartStudyNumericBindingDto>(
                invalid_binding
            )
            .is_err()
        );
        assert_eq!(
            entry.capability["numeric_execution_binding"]["precision"],
            38
        );
        assert_eq!(
            entry.capability["capability_projection"]["implementation"]["resources"],
            invocation["resources"]
        );
        let definition = resolve(&entry, &json!({"period":2,"price_field":"close"}))
            .unwrap()
            .to_record();
        assert_eq!(definition["input_bindings"]["value"]["source"], "bar.close");
        let deadline = Instant::now() + std::time::Duration::from_secs(10);
        let columns = json!({"value":["9999999999999999.999999999999","9999999999999999.999999999999","0.000000000001"]});
        let result = evaluate(&definition, columns.as_object().unwrap(), deadline).unwrap();
        assert_eq!(
            result["value"]["values"],
            json!([
                "9999999999999999.999999999999",
                "9999999999999999.999999999999",
                "5000000000000000.000000000000"
            ])
        );
        assert_eq!(
            result["value"]["states"],
            json!(["PARTIAL", "READY", "READY"])
        );
        super::super::validate_outputs(&definition, &result, 3).unwrap();
        let invalid = json!({"value":["0.0000000000001"]});
        assert!(evaluate(&definition, invalid.as_object().unwrap(), deadline).is_err());
        assert!(resolve(&entry, &json!({"period":10001})).is_err());
        assert_eq!(source_decimal("1E-8").unwrap(), "0.00000001");
        assert_eq!(
            source_decimal("1E+25").unwrap(),
            "10000000000000000000000000"
        );
        assert_eq!(
            source_decimal("0.000000000001000").unwrap(),
            "0.000000000001"
        );
        assert!(source_decimal("1E+26").is_err());
        assert!(source_decimal("1E-13").is_err());
    }
}
