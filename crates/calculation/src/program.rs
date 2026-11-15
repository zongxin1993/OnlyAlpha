//! Bounded typed factor bytecode, independent of Python, storage and readiness.
//! Decoding proves structure/types only; it never grants certification or admission.
pub use crate::program_execution::{ProgramInput, ProgramInstance, ProgramValue, evaluate_batch};
use crate::{
    Result,
    record::{err, hash, object},
};
use onlyalpha_operators::algebra::{
    Decimal, Kernel, MAX_CELLS, MAX_INPUT_DIGITS, MAX_INPUT_SCALE, MAX_WINDOW, Operator, Parameters,
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, num::NonZeroUsize, str::FromStr, sync::Arc};
pub const NUMERIC_POLICY: &str = "DECIMAL28_HALF_EVEN_Q12_V1";
pub const MAX_PROGRAM_BYTES: usize = 1024 * 1024;
pub const MAX_NODES: usize = 1024;
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Type {
    Integer,
    Decimal,
    Boolean,
}
impl Type {
    fn is_numeric(self) -> bool {
        matches!(self, Self::Integer | Self::Decimal)
    }
    fn common(self, other: Self) -> Option<Self> {
        if self == other {
            Some(self)
        } else if self.is_numeric() && other.is_numeric() {
            Some(Self::Decimal)
        } else {
            None
        }
    }
}
#[derive(Clone, Debug)]
pub(crate) enum Instruction {
    Input(String),
    Parameter(String),
    Literal(ProgramValue),
    Numeric(Kernel, Vec<usize>),
    Window(Operator, usize, Value),
    Logic(String, Vec<usize>),
}
#[derive(Clone, Debug)]
pub struct Program {
    pub(crate) record: Value,
    pub(crate) fingerprint: String,
    pub(crate) inputs: BTreeMap<String, Type>,
    pub(crate) parameter_schema: Value,
    pub(crate) nodes: Vec<Instruction>,
    pub(crate) outputs: BTreeMap<String, usize>,
    pub(crate) types: Vec<Type>,
}
#[derive(Clone, Debug)]
pub struct ResolvedParameters {
    schema: String,
    pub(crate) record: Value,
}
impl ResolvedParameters {
    pub fn record(&self) -> &Value {
        &self.record
    }
    pub fn fingerprint(&self) -> String {
        hash(&self.record)
    }
}
#[derive(Clone, Debug)]
pub struct BoundProgram {
    pub(crate) program: Arc<Program>,
    pub(crate) parameters: ResolvedParameters,
    pub(crate) parameter_values: BTreeMap<String, ProgramValue>,
    pub(crate) kernels: Vec<Option<Kernel>>,
    pub(crate) fingerprint: String,
    pub(crate) history: usize,
}
impl BoundProgram {
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn program(&self) -> &Program {
        &self.program
    }
    pub fn parameters(&self) -> &ResolvedParameters {
        &self.parameters
    }
    pub fn max_history(&self) -> usize {
        self.history
    }
    pub fn certification_work(&self, rows: usize) -> Option<usize> {
        self.kernels
            .iter()
            .map(|k| k.as_ref().map_or(1, Kernel::history_limit))
            .try_fold(0usize, |n, w| n.checked_add(w))
            .and_then(|w| w.checked_mul(rows))
    }
}
pub(crate) fn decimal(raw: &str) -> Result<Decimal> {
    if raw.len() > 512
        || raw.is_empty()
        || !raw
            .bytes()
            .all(|b| b.is_ascii_digit() || b"+-.eE".contains(&b))
    {
        return Err(err("PROGRAM_DECIMAL_INVALID"));
    }
    let d = Decimal::from_str(raw).map_err(|_| err("PROGRAM_DECIMAL_INVALID"))?;
    let (_, scale) = d.as_bigint_and_exponent();
    if d.digits() > MAX_INPUT_DIGITS || scale.unsigned_abs() > MAX_INPUT_SCALE as u64 {
        return Err(err("PROGRAM_NUMERIC_BUDGET"));
    }
    Ok(d)
}
pub(crate) fn integer(raw: &str) -> Result<bigdecimal::num_bigint::BigInt> {
    if raw.len() > MAX_INPUT_DIGITS as usize + 1 {
        return Err(err("PROGRAM_NUMERIC_BUDGET"));
    }
    let value = bigdecimal::num_bigint::BigInt::from_str(raw)
        .map_err(|_| err("PROGRAM_INTEGER_REQUIRED"))?;
    if value.to_string().trim_start_matches('-').len() as u64 > MAX_INPUT_DIGITS {
        return Err(err("PROGRAM_NUMERIC_BUDGET"));
    }
    Ok(value)
}
pub(crate) fn ident(v: &Value) -> Result<String> {
    let s = v.as_str().ok_or_else(|| err("PROGRAM_NAME"))?;
    if s.is_empty() || s.len() > 64 || !s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_') {
        return Err(err("PROGRAM_NAME"));
    }
    Ok(s.into())
}
fn data_type(v: &Value) -> Result<Type> {
    match v.as_str() {
        Some("INTEGER") => Ok(Type::Integer),
        Some("DECIMAL") => Ok(Type::Decimal),
        Some("BOOLEAN") => Ok(Type::Boolean),
        _ => Err(err("PROGRAM_TYPE")),
    }
}
fn args(v: &Value, count: usize, at: usize) -> Result<Vec<usize>> {
    let a = v.as_array().ok_or_else(|| err("PROGRAM_ARGS"))?;
    if a.len() != count {
        return Err(err("PROGRAM_ARITY"));
    }
    a.iter()
        .map(|v| {
            v.as_u64()
                .and_then(|n| usize::try_from(n).ok())
                .filter(|n| *n < at)
                .ok_or_else(|| err("PROGRAM_FORWARD_REFERENCE"))
        })
        .collect()
}
fn numeric(op: &str) -> Option<Operator> {
    use Operator::*;
    Some(match op {
        "add" => Add,
        "sub" => Subtract,
        "mul" => Multiply,
        "div" => Divide,
        "abs" => Abs,
        "sign" => Sign,
        "log" => Log,
        _ => return None,
    })
}
fn window(op: &str) -> Option<Operator> {
    use Operator::*;
    Some(match op {
        "delay" => Delay,
        "delta" => Delta,
        "rolling_mean" => RollingMean,
        "rolling_sum" => RollingSum,
        "rolling_min" => RollingMin,
        "rolling_max" => RollingMax,
        "rolling_std" => RollingStd,
        "rolling_var" => RollingVar,
        "ts_rank" => TSRank,
        "decay_linear" => DecayLinear,
        _ => return None,
    })
}
impl Program {
    pub fn decode(canonical: &[u8]) -> Result<Self> {
        if canonical.len() > MAX_PROGRAM_BYTES {
            return Err(err("PROGRAM_BYTE_BUDGET"));
        }
        let r: Value = serde_json::from_slice(canonical).map_err(|_| err("PROGRAM_JSON"))?;
        if r.to_string().as_bytes() != canonical {
            return Err(err("PROGRAM_NONCANONICAL"));
        }
        object(
            &r,
            &[
                "schema_version",
                "numeric_policy",
                "inputs",
                "parameters",
                "nodes",
                "outputs",
            ],
        )?;
        if r["schema_version"] != 1 || r["numeric_policy"] != NUMERIC_POLICY {
            return Err(err("PROGRAM_VERSION"));
        }
        let input_map = r["inputs"]
            .as_object()
            .filter(|v| v.len() <= 128)
            .ok_or_else(|| err("PROGRAM_INPUT_BUDGET"))?;
        let mut inputs = BTreeMap::new();
        for (name, spec) in input_map {
            ident(&json!(name))?;
            object(spec, &["type", "role"])?;
            if !matches!(spec["role"].as_str(), Some("MARKET" | "FACTOR")) {
                return Err(err("PROGRAM_FUTURE_INPUT"));
            }
            inputs.insert(name.clone(), data_type(&spec["type"])?);
        }
        let schema = crate::parameters::schema(&r["parameters"])?;
        if schema != r["parameters"] {
            return Err(err("PROGRAM_PARAMETER_SCHEMA_NONCANONICAL"));
        }
        let mut parameter_types = BTreeMap::new();
        for spec in schema.as_array().expect("validated schema") {
            let name = ident(&spec["name"])?;
            parameter_types.insert(name, data_type(&spec["parameter_type"])?);
        }
        let raw_nodes = r["nodes"]
            .as_array()
            .filter(|v| !v.is_empty() && v.len() <= MAX_NODES)
            .ok_or_else(|| err("PROGRAM_NODE_BUDGET"))?;
        let (mut nodes, mut types) = (Vec::new(), Vec::<Type>::new());
        for (i, v) in raw_nodes.iter().enumerate() {
            let op = v["op"].as_str().ok_or_else(|| err("PROGRAM_OPCODE"))?;
            let (node, t) = match op {
                "input" => {
                    object(v, &["op", "name"])?;
                    let n = ident(&v["name"])?;
                    let t = *inputs.get(&n).ok_or_else(|| err("PROGRAM_INPUT"))?;
                    (Instruction::Input(n), t)
                }
                "parameter" => {
                    object(v, &["op", "name"])?;
                    let n = ident(&v["name"])?;
                    let t = *parameter_types
                        .get(&n)
                        .ok_or_else(|| err("PROGRAM_PARAMETER"))?;
                    (Instruction::Parameter(n), t)
                }
                "literal" => {
                    object(v, &["op", "type", "value"])?;
                    let t = data_type(&v["type"])?;
                    let cell = if v["value"].is_null() {
                        ProgramValue::Missing
                    } else {
                        match t {
                            Type::Integer => ProgramValue::Integer(integer(
                                v["value"]
                                    .as_str()
                                    .ok_or_else(|| err("PROGRAM_INTEGER_LITERAL"))?,
                            )?),
                            Type::Decimal => ProgramValue::Decimal(decimal(
                                v["value"]
                                    .as_str()
                                    .ok_or_else(|| err("PROGRAM_DECIMAL_LITERAL"))?,
                            )?),
                            Type::Boolean => ProgramValue::Boolean(
                                v["value"]
                                    .as_bool()
                                    .ok_or_else(|| err("PROGRAM_BOOL_LITERAL"))?,
                            ),
                        }
                    };
                    (Instruction::Literal(cell), t)
                }
                _ => {
                    if let Some(n) = numeric(op) {
                        object(v, &["op", "args"])?;
                        let a = args(&v["args"], n.input_count(), i)?;
                        if a.iter().any(|n| !types[*n].is_numeric()) {
                            return Err(err("PROGRAM_NUMERIC_TYPE"));
                        }
                        (
                            Instruction::Numeric(
                                Kernel::new(n, Parameters::default())
                                    .map_err(|_| err("PROGRAM_NUMERIC"))?,
                                a,
                            ),
                            Type::Decimal,
                        )
                    } else if let Some(n) = window(op) {
                        object(v, &["op", "args", "period"])?;
                        let a = args(&v["args"], 1, i)?;
                        if !types[a[0]].is_numeric() {
                            return Err(err("PROGRAM_WINDOW_TYPE"));
                        }
                        if let Some(p) = v["period"].as_u64() {
                            if p == 0 || p > MAX_WINDOW as u64 {
                                return Err(err("PROGRAM_WINDOW_BUDGET"));
                            }
                        } else {
                            object(&v["period"], &["parameter"])?;
                            let key = ident(&v["period"]["parameter"])?;
                            if !schema
                                .as_array()
                                .unwrap()
                                .iter()
                                .any(|s| s["name"] == key && s["parameter_type"] == "INTEGER")
                            {
                                return Err(err("PROGRAM_PERIOD_TYPE"));
                            }
                        }
                        (
                            Instruction::Window(n, a[0], v["period"].clone()),
                            Type::Decimal,
                        )
                    } else {
                        object(v, &["op", "args"])?;
                        let count = match op {
                            "negate" | "not_" | "is_missing" | "to_decimal" => 1,
                            "where" => 3,
                            "eq" | "ne" | "lt" | "le" | "gt" | "ge" | "min" | "max" | "and_"
                            | "or_" | "coalesce" => 2,
                            _ => return Err(err("PROGRAM_OPCODE")),
                        };
                        let a = args(&v["args"], count, i)?;
                        let t = types[a[0]];
                        let valid = match op {
                            "is_missing" => true,
                            "not_" | "and_" | "or_" => a.iter().all(|n| types[*n] == Type::Boolean),
                            "where" => {
                                types[a[0]] == Type::Boolean
                                    && types[a[1]].common(types[a[2]]).is_some()
                            }
                            "negate" | "to_decimal" => t.is_numeric(),
                            "lt" | "le" | "gt" | "ge" | "min" | "max" => {
                                a.iter().all(|n| types[*n].is_numeric())
                            }
                            _ => t.common(types[a[1]]).is_some(),
                        };
                        if !valid {
                            return Err(err("PROGRAM_LOGIC_TYPE"));
                        }
                        let out = match op {
                            "where" => types[a[1]].common(types[a[2]]).expect("validated branches"),
                            "min" | "max" | "coalesce" => {
                                t.common(types[a[1]]).expect("validated arguments")
                            }
                            "negate" | "to_decimal" => Type::Decimal,
                            _ => Type::Boolean,
                        };
                        (Instruction::Logic(op.into(), a), out)
                    }
                }
            };
            nodes.push(node);
            types.push(t);
        }
        let output_map = r["outputs"]
            .as_object()
            .filter(|m| !m.is_empty() && m.len() <= 128)
            .ok_or_else(|| err("PROGRAM_OUTPUT_BUDGET"))?;
        let mut outputs = BTreeMap::new();
        for (k, v) in output_map {
            ident(&json!(k))?;
            let n = v
                .as_u64()
                .and_then(|v| usize::try_from(v).ok())
                .filter(|v| *v < nodes.len())
                .ok_or_else(|| err("PROGRAM_OUTPUT"))?;
            outputs.insert(k.clone(), n);
        }
        Ok(Self {
            fingerprint: hash(&r),
            record: r,
            inputs,
            parameter_schema: schema,
            nodes,
            outputs,
            types,
        })
    }
    pub fn record(&self) -> &Value {
        &self.record
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
    pub fn output_types(&self) -> BTreeMap<&str, &str> {
        self.outputs
            .iter()
            .map(|(name, n)| {
                (
                    name.as_str(),
                    match self.types[*n] {
                        Type::Integer => "INTEGER",
                        Type::Decimal => "DECIMAL",
                        Type::Boolean => "BOOLEAN",
                    },
                )
            })
            .collect()
    }
    pub fn resolve_parameters(&self, input: &Value) -> Result<ResolvedParameters> {
        Ok(ResolvedParameters {
            schema: hash(&self.parameter_schema),
            record: crate::parameters::parameters(&self.parameter_schema, input)?,
        })
    }
    pub fn bind(&self, parameters: &ResolvedParameters) -> Result<BoundProgram> {
        if parameters.schema != hash(&self.parameter_schema) {
            return Err(err("PROGRAM_PARAMETER_BINDING"));
        }
        let mut parameter_values = BTreeMap::new();
        for (name, v) in parameters
            .record
            .as_object()
            .ok_or_else(|| err("PROGRAM_PARAMETERS"))?
        {
            let value = match v["type"].as_str() {
                Some("INTEGER") => ProgramValue::Integer(integer(&v["value"].to_string())?),
                Some("DECIMAL") => ProgramValue::Decimal(decimal(
                    v["value"]
                        .as_str()
                        .ok_or_else(|| err("PROGRAM_PARAMETER_VALUE"))?,
                )?),
                Some("BOOLEAN") => ProgramValue::Boolean(
                    v["value"]
                        .as_bool()
                        .ok_or_else(|| err("PROGRAM_PARAMETER_VALUE"))?,
                ),
                _ => return Err(err("PROGRAM_PARAMETER_TYPE")),
            };
            parameter_values.insert(name.clone(), value);
        }
        let mut kernels = Vec::new();
        let mut cells = 0usize;
        for n in &self.nodes {
            let k = if let Instruction::Window(op, _, p) = n {
                let count = if let Some(n) = p.as_u64() {
                    n
                } else {
                    parameters.record[p["parameter"].as_str().unwrap()]["value"]
                        .as_u64()
                        .ok_or_else(|| err("PROGRAM_PERIOD_VALUE"))?
                };
                let count = usize::try_from(count)
                    .ok()
                    .and_then(NonZeroUsize::new)
                    .ok_or_else(|| err("PROGRAM_PERIOD_VALUE"))?;
                let k = Kernel::new(
                    *op,
                    Parameters {
                        period: Some(count),
                        ..Default::default()
                    },
                )
                .map_err(|_| err("PROGRAM_WINDOW_BUDGET"))?;
                cells = cells
                    .checked_add(k.history_limit())
                    .filter(|n| *n <= MAX_CELLS)
                    .ok_or_else(|| err("PROGRAM_STATE_BUDGET"))?;
                Some(k)
            } else {
                None
            };
            kernels.push(k);
        }
        let mut prefix: Vec<usize> = Vec::with_capacity(self.nodes.len());
        for (i, n) in self.nodes.iter().enumerate() {
            let distance = match n {
                Instruction::Numeric(_, args) | Instruction::Logic(_, args) => {
                    args.iter().map(|n| prefix[*n]).max().unwrap_or(0)
                }
                Instruction::Window(_, n, _) => {
                    let h = kernels[i].as_ref().unwrap().history_limit();
                    let distance = h.saturating_sub(1);
                    prefix[*n]
                        .checked_add(distance)
                        .ok_or_else(|| err("PROGRAM_HISTORY_BUDGET"))?
                }
                _ => 0,
            };
            prefix.push(distance);
        }
        let history = self
            .outputs
            .values()
            .map(|n| prefix[*n])
            .max()
            .unwrap_or(0)
            .checked_add(1)
            .ok_or_else(|| err("PROGRAM_HISTORY_BUDGET"))?;
        Ok(BoundProgram {
            program: Arc::new(self.clone()),
            parameters: parameters.clone(),
            parameter_values,
            kernels,
            history,
            fingerprint: hash(&json!({"program":self.fingerprint,"parameters":parameters.record})),
        })
    }
}
