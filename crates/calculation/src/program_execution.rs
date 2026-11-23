use crate::program::{BoundProgram, Instruction, Type, decimal, integer};
use crate::{
    Result,
    record::{err, object},
};
use onlyalpha_operators::algebra::{
    Decimal, Kernel, MAX_INPUT_DIGITS, MAX_INPUT_SCALE, Operator, Parameters, Stream,
};
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc};
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ProgramValue {
    Missing,
    Integer(bigdecimal::num_bigint::BigInt),
    Decimal(Decimal),
    Boolean(bool),
}
impl ProgramValue {
    pub fn record(&self) -> Value {
        match self {
            Self::Missing => Value::Null,
            Self::Integer(n) => serde_json::from_str(&n.to_string()).expect("exact integer JSON"),
            Self::Decimal(d) => json!(d.to_plain_string()),
            Self::Boolean(b) => json!(b),
        }
    }
    fn number(&self) -> Result<Option<Decimal>> {
        match self {
            Self::Missing => Ok(None),
            Self::Integer(n) => Ok(Some(Decimal::from(n.clone()))),
            Self::Decimal(d) => Ok(Some(d.clone())),
            _ => Err(err("PROGRAM_VALUE_TYPE")),
        }
    }
    fn checked(&self) -> Result<()> {
        if let Self::Integer(n) = self
            && n.to_string().trim_start_matches('-').len() as u64 > MAX_INPUT_DIGITS
        {
            return Err(err("PROGRAM_NUMERIC_BUDGET"));
        }
        if let Self::Decimal(d) = self {
            let (_, scale) = d.as_bigint_and_exponent();
            if d.digits() > MAX_INPUT_DIGITS || scale.unsigned_abs() > MAX_INPUT_SCALE as u64 {
                return Err(err("PROGRAM_NUMERIC_BUDGET"));
            }
        }
        Ok(())
    }
    fn conform(&self, kind: Type) -> Result<Self> {
        Ok(match (kind, self) {
            (_, Self::Missing) => Self::Missing,
            (Type::Integer, Self::Integer(n)) => Self::Integer(n.clone()),
            (Type::Integer, Self::Decimal(n)) if n.is_integer() => {
                Self::Integer(integer(&n.with_scale(0).to_plain_string())?)
            }
            (Type::Decimal, Self::Integer(n)) => Self::Decimal(Decimal::from(n.clone())),
            (Type::Decimal, Self::Decimal(n)) => Self::Decimal(n.clone()),
            (Type::Boolean, Self::Boolean(n)) => Self::Boolean(*n),
            _ => return Err(err("PROGRAM_INPUT_TYPE")),
        })
    }
}
#[derive(Clone, Debug)]
pub struct ProgramInput {
    instrument: String,
    sequence: u64,
    values: BTreeMap<String, ProgramValue>,
}
impl ProgramInput {
    pub fn new(
        instrument: &str,
        sequence: u64,
        values: BTreeMap<String, ProgramValue>,
    ) -> Result<Self> {
        if instrument.is_empty()
            || instrument.len() > 256
            || instrument.chars().any(char::is_control)
            || values.len() > 128
        {
            return Err(err("PROGRAM_INPUT_BUDGET"));
        }
        for v in values.values() {
            v.checked()?;
        }
        Ok(Self {
            instrument: instrument.into(),
            sequence,
            values,
        })
    }
    pub fn values(&self) -> &BTreeMap<String, ProgramValue> {
        &self.values
    }
}
#[derive(Clone)]
pub struct ProgramInstance {
    program: Arc<BoundProgram>,
    streams: Vec<Option<Stream>>,
    instrument: Option<String>,
    next_sequence: u64,
}
fn numeric(k: &Kernel, values: &[ProgramValue]) -> Result<ProgramValue> {
    let columns = values
        .iter()
        .map(|v| Ok(vec![v.number()?]))
        .collect::<Result<Vec<_>>>()?;
    Ok(k.evaluate(&columns)
        .map_err(|_| err("PROGRAM_NUMERIC_FAILURE"))?
        .pop()
        .flatten()
        .map_or(ProgramValue::Missing, ProgramValue::Decimal))
}
fn logic(op: &str, a: &[ProgramValue]) -> Result<ProgramValue> {
    use ProgramValue::*;
    if op == "is_missing" {
        return Ok(Boolean(a[0] == Missing));
    }
    if op == "coalesce" {
        return Ok(if a[0] == Missing {
            a[1].clone()
        } else {
            a[0].clone()
        });
    }
    if op == "where" {
        return match a[0] {
            Boolean(true) => Ok(a[1].clone()),
            Boolean(false) => Ok(a[2].clone()),
            Missing => Ok(Missing),
            _ => Err(err("PROGRAM_CONDITION")),
        };
    }
    if op == "and_" {
        return Ok(if a.contains(&Boolean(false)) {
            Boolean(false)
        } else if a.contains(&Missing) {
            Missing
        } else {
            Boolean(true)
        });
    }
    if op == "or_" {
        return Ok(if a.contains(&Boolean(true)) {
            Boolean(true)
        } else if a.contains(&Missing) {
            Missing
        } else {
            Boolean(false)
        });
    }
    if a.contains(&Missing) {
        return Ok(Missing);
    }
    if op == "not_" {
        return match a[0] {
            Boolean(b) => Ok(Boolean(!b)),
            _ => Err(err("PROGRAM_CONDITION")),
        };
    }
    if op == "negate" {
        return numeric(
            &Kernel::new(Operator::Subtract, Parameters::default())
                .map_err(|_| err("PROGRAM_KERNEL"))?,
            &[Decimal(0.into()), a[0].clone()],
        );
    }
    if op == "to_decimal" {
        return Ok(a[0].number()?.map_or(Missing, Decimal));
    }
    if op == "eq" || op == "ne" {
        let equal = match (&a[0], &a[1]) {
            (Boolean(x), Boolean(y)) => x == y,
            _ => a[0].number()? == a[1].number()?,
        };
        return Ok(Boolean(equal == (op == "eq")));
    }
    let (Some(x), Some(y)) = (a[0].number()?, a[1].number()?) else {
        return Err(err("PROGRAM_COMPARE_TYPE"));
    };
    Ok(match op {
        "lt" => Boolean(x < y),
        "le" => Boolean(x <= y),
        "gt" => Boolean(x > y),
        "ge" => Boolean(x >= y),
        "min" => Decimal(x.min(y)),
        "max" => Decimal(x.max(y)),
        _ => return Err(err("PROGRAM_OPCODE")),
    })
}
impl ProgramInstance {
    pub fn new(program: Arc<BoundProgram>) -> Self {
        let streams = program
            .kernels
            .iter()
            .map(|k| {
                k.clone()
                    .map(|k| Stream::new(k).expect("validated non-cross-section kernel"))
            })
            .collect();
        Self {
            program,
            streams,
            instrument: None,
            next_sequence: 0,
        }
    }
    pub fn step(&mut self, input: &ProgramInput) -> Result<BTreeMap<String, ProgramValue>> {
        if input.sequence != self.next_sequence
            || self
                .instrument
                .as_ref()
                .is_some_and(|i| i != &input.instrument)
        {
            return Err(err("PROGRAM_INPUT_POSITION"));
        }
        let next = self
            .next_sequence
            .checked_add(1)
            .ok_or_else(|| err("PROGRAM_POSITION_OVERFLOW"))?;
        let p = &self.program.program;
        if input.values.keys().ne(p.inputs.keys()) {
            return Err(err("PROGRAM_INPUT_MEMBERS"));
        }
        let mut input_values = BTreeMap::new();
        for (k, v) in &input.values {
            v.checked()?;
            input_values.insert(k.clone(), v.conform(p.inputs[k])?);
        }
        let mut streams = self.streams.clone();
        let mut values: Vec<ProgramValue> = Vec::with_capacity(p.nodes.len());
        for (i, node) in p.nodes.iter().enumerate() {
            let result = match node {
                Instruction::Input(n) => input_values[n].clone(),
                Instruction::Literal(v) => v.clone(),
                Instruction::Parameter(n) => self.program.parameter_values[n].clone(),
                Instruction::Numeric(k, a) => {
                    numeric(k, &a.iter().map(|n| values[*n].clone()).collect::<Vec<_>>())?
                }
                Instruction::Window(_, n, _) => streams[i]
                    .as_mut()
                    .expect("bound window")
                    .push(&[values[*n].number()?])
                    .map_err(|_| err("PROGRAM_NUMERIC_FAILURE"))?
                    .map_or(ProgramValue::Missing, ProgramValue::Decimal),
                Instruction::Logic(op, a) => logic(
                    op,
                    &a.iter().map(|n| values[*n].clone()).collect::<Vec<_>>(),
                )?,
            };
            values.push(result);
        }
        let normalize = Kernel::new(Operator::Scale, Parameters::default())
            .map_err(|_| err("PROGRAM_KERNEL"))?;
        let mut outputs = BTreeMap::new();
        for (k, n) in &p.outputs {
            let v = values[*n].conform(p.types[*n])?;
            let v = match v {
                ProgramValue::Decimal(_) => numeric(&normalize, &[v])?,
                v => v,
            };
            outputs.insert(k.clone(), v);
        }
        self.streams = streams;
        self.instrument = Some(input.instrument.clone());
        self.next_sequence = next;
        Ok(outputs)
    }
    pub fn capture(&self) -> Value {
        json!({"schema_version":1,"bound_program":self.program.fingerprint,"instrument":self.instrument,"next_sequence":self.next_sequence,"windows":self.streams.iter().map(|s|s.as_ref().map(|s|s.checkpoint().iter().map(|col|col.iter().map(|v|v.as_ref().map(ToString::to_string)).collect::<Vec<_>>()).collect::<Vec<_>>())).collect::<Vec<_>>()})
    }
    pub fn restore(&mut self, v: &Value) -> Result<()> {
        if v.to_string().len() > 128 * 1024 * 1024 {
            return Err(err("PROGRAM_STATE_BUDGET"));
        }
        object(
            v,
            &[
                "schema_version",
                "bound_program",
                "instrument",
                "next_sequence",
                "windows",
            ],
        )?;
        if v["schema_version"] != 1 || v["bound_program"] != self.program.fingerprint {
            return Err(err("PROGRAM_STATE_BINDING"));
        }
        let next = v["next_sequence"]
            .as_u64()
            .ok_or_else(|| err("PROGRAM_STATE_POSITION"))?;
        let instrument = if next == 0 {
            if !v["instrument"].is_null() {
                return Err(err("PROGRAM_STATE_POSITION"));
            }
            None
        } else {
            Some(
                ProgramInput::new(
                    v["instrument"]
                        .as_str()
                        .ok_or_else(|| err("PROGRAM_STATE_INSTRUMENT"))?,
                    0,
                    BTreeMap::new(),
                )?
                .instrument,
            )
        };
        let raw = v["windows"]
            .as_array()
            .filter(|a| a.len() == self.streams.len())
            .ok_or_else(|| err("PROGRAM_STATE_WINDOWS"))?;
        let mut streams = Self::new(self.program.clone()).streams;
        for (i, (s, raw)) in streams.iter_mut().zip(raw).enumerate() {
            if let Some(s) = s {
                let cols = raw
                    .as_array()
                    .filter(|a| a.len() == 1)
                    .ok_or_else(|| err("PROGRAM_STATE_COLUMNS"))?;
                let count = next
                    .min(self.program.kernels[i].as_ref().unwrap().history_limit() as u64)
                    as usize;
                let mut columns = Vec::new();
                for col in cols {
                    let a = col
                        .as_array()
                        .filter(|a| a.len() == count)
                        .ok_or_else(|| err("PROGRAM_STATE_LENGTH"))?;
                    columns.push(
                        a.iter()
                            .map(|v| {
                                if v.is_null() {
                                    Ok(None)
                                } else {
                                    decimal(v.as_str().ok_or_else(|| err("PROGRAM_STATE_DECIMAL"))?)
                                        .map(Some)
                                }
                            })
                            .collect::<Result<Vec<_>>>()?,
                    );
                }
                s.restore(columns)
                    .map_err(|_| err("PROGRAM_STATE_INVALID"))?;
            } else if !raw.is_null() {
                return Err(err("PROGRAM_STATE_NONWINDOW"));
            }
        }
        self.streams = streams;
        self.instrument = instrument;
        self.next_sequence = next;
        Ok(())
    }
}
pub fn evaluate_batch(
    program: &BoundProgram,
    inputs: &[ProgramInput],
) -> Result<Vec<BTreeMap<String, ProgramValue>>> {
    if inputs.len() > 1_000_000 {
        return Err(err("PROGRAM_BATCH_BUDGET"));
    }
    let mut instance = ProgramInstance::new(Arc::new(program.clone()));
    inputs.iter().map(|i| instance.step(i)).collect()
}
