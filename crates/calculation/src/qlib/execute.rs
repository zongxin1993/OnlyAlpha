//! Dual-mode (vector batch & incremental event) DAG executor for compiled Qlib expressions.

use crate::qlib::compile::{CompareOp, CompiledDag, Instruction};
use crate::{
    Result,
    record::{err, object},
};
use onlyalpha_operators::algebra::{
    Columns, Decimal, Error as OpError, Kernel, MAX_CELLS, MAX_INPUT_DIGITS, MAX_INPUT_SCALE,
    MAX_WINDOW_WORK, Operator, Parameters, Stream,
};
use onlyalpha_operators::execution::{EventKernel, VectorKernel};
use onlyalpha_operators::registry::ExecutionShape;
use serde_json::{Value, json};
use std::collections::BTreeMap;
use std::str::FromStr;
use std::sync::Arc;

const MAX_STATE_RECORD_BYTES: usize = 64 * 1024 * 1024;

fn map_op_error(error: OpError) -> crate::CalculationError {
    match error {
        OpError::InvalidParameters => err("QLIB_INVALID_PARAMETER"),
        OpError::InvalidInputs => err("QLIB_INVALID_INPUTS"),
        OpError::BudgetExceeded => err("QLIB_RESOURCE_BUDGET"),
        OpError::NumericFailure => err("QLIB_NUMERIC_FAILURE"),
        OpError::ResearchOnly => err("QLIB_RESEARCH_ONLY_OPERATOR"),
        OpError::Interrupted => err("QLIB_INTERRUPTED"),
    }
}

fn validate_cell(value: &Option<Decimal>) -> Result<()> {
    if let Some(d) = value {
        let (_, scale) = d.as_bigint_and_exponent();
        if d.digits() > MAX_INPUT_DIGITS || scale.unsigned_abs() > MAX_INPUT_SCALE as u64 {
            return Err(err("QLIB_NUMERIC_BUDGET"));
        }
    }
    Ok(())
}

fn compare_cell(op: CompareOp, lhs: &Option<Decimal>, rhs: &Option<Decimal>) -> Option<Decimal> {
    let (Some(a), Some(b)) = (lhs, rhs) else {
        return None;
    };
    let passed = match op {
        CompareOp::Lt => a < b,
        CompareOp::Le => a <= b,
        CompareOp::Gt => a > b,
        CompareOp::Ge => a >= b,
        CompareOp::Eq => a == b,
        CompareOp::Ne => a != b,
    };
    Some(Decimal::from(if passed { 1 } else { 0 }))
}

fn normalize_kernel() -> Result<Kernel> {
    Kernel::new(Operator::Scale, Parameters::default()).map_err(map_op_error)
}

fn normalize_column(
    dag: &CompiledDag,
    column: Vec<Option<Decimal>>,
) -> Result<Vec<Option<Decimal>>> {
    if matches!(dag.instructions[dag.output], Instruction::Op { .. }) {
        return Ok(column);
    }
    let kernel = normalize_kernel()?;
    VectorKernel::evaluate(&kernel, &[column]).map_err(map_op_error)
}

pub(crate) fn evaluate_vector(
    dag: &CompiledDag,
    inputs: &BTreeMap<String, Vec<Option<Decimal>>>,
) -> Result<Vec<Option<Decimal>>> {
    if dag.has_cross_section {
        return Err(err("QLIB_CROSS_SECTION_REQUIRES_PANEL"));
    }
    let len = validate_series_inputs(dag, inputs)?;
    let work = len
        .checked_mul(dag.budget.work_per_row)
        .ok_or_else(|| err("QLIB_RESOURCE_BUDGET"))?;
    if len > MAX_CELLS || work > MAX_WINDOW_WORK {
        return Err(err("QLIB_RESOURCE_BUDGET"));
    }
    let mut values: Vec<Vec<Option<Decimal>>> = Vec::with_capacity(dag.instructions.len());
    for inst in &dag.instructions {
        let col = match inst {
            Instruction::Input(name) => {
                let col = &inputs[name];
                for cell in col {
                    validate_cell(cell)?;
                }
                col.clone()
            }
            Instruction::Constant(val) => vec![Some(val.clone()); len],
            Instruction::Compare { op, lhs, rhs } => values[*lhs]
                .iter()
                .zip(&values[*rhs])
                .map(|(a, b)| compare_cell(*op, a, b))
                .collect(),
            Instruction::Op { kernel, inputs, .. } => {
                let args: Vec<Vec<Option<Decimal>>> =
                    inputs.iter().map(|&id| values[id].clone()).collect();
                VectorKernel::evaluate(kernel, &args).map_err(map_op_error)?
            }
            Instruction::Lead { input, offset } => {
                let src = &values[*input];
                let shift = offset.get();
                (0..len)
                    .map(|i| src.get(i.saturating_add(shift)).cloned().flatten())
                    .collect()
            }
        };
        values.push(col);
    }
    normalize_column(dag, values.swap_remove(dag.output))
}

pub(crate) fn evaluate_panel(
    dag: &CompiledDag,
    instruments: &[BTreeMap<String, Vec<Option<Decimal>>>],
) -> Result<Vec<Vec<Option<Decimal>>>> {
    let n = instruments.len();
    if n == 0 {
        return Ok(Vec::new());
    }
    let mut expected_len: Option<usize> = None;
    for series in instruments {
        let len = validate_series_inputs(dag, series)?;
        match expected_len {
            None => expected_len = Some(len),
            Some(existing) if existing != len => return Err(err("QLIB_INPUT_LENGTH_MISMATCH")),
            Some(_) => {}
        }
    }
    let len = expected_len.unwrap_or(0);
    let cells = n
        .checked_mul(len)
        .ok_or_else(|| err("QLIB_RESOURCE_BUDGET"))?;
    let work = cells
        .checked_mul(dag.budget.work_per_row)
        .ok_or_else(|| err("QLIB_RESOURCE_BUDGET"))?;
    if cells > MAX_CELLS || work > MAX_WINDOW_WORK {
        return Err(err("QLIB_RESOURCE_BUDGET"));
    }

    let mut values: Vec<Vec<Vec<Option<Decimal>>>> = Vec::with_capacity(dag.instructions.len());
    for inst in &dag.instructions {
        let panel = match inst {
            Instruction::Input(name) => {
                let mut out = Vec::with_capacity(n);
                for series in instruments {
                    let col = &series[name];
                    for cell in col {
                        validate_cell(cell)?;
                    }
                    out.push(col.clone());
                }
                out
            }
            Instruction::Constant(val) => vec![vec![Some(val.clone()); len]; n],
            Instruction::Compare { op, lhs, rhs } => (0..n)
                .map(|inst_idx| {
                    values[*lhs][inst_idx]
                        .iter()
                        .zip(&values[*rhs][inst_idx])
                        .map(|(a, b)| compare_cell(*op, a, b))
                        .collect()
                })
                .collect(),
            Instruction::Lead { input, offset } => {
                let shift = offset.get();
                (0..n)
                    .map(|inst_idx| {
                        let src = &values[*input][inst_idx];
                        (0..len)
                            .map(|t| src.get(t.saturating_add(shift)).cloned().flatten())
                            .collect()
                    })
                    .collect()
            }
            Instruction::Op { kernel, inputs, .. } => {
                if kernel.operator().spec().shape == ExecutionShape::CrossSection {
                    let mut out = vec![vec![None; len]; n];
                    for t in 0..len {
                        let plane_args: Vec<Vec<Option<Decimal>>> = inputs
                            .iter()
                            .map(|&id| {
                                (0..n)
                                    .map(|inst_idx| values[id][inst_idx][t].clone())
                                    .collect()
                            })
                            .collect();
                        let plane_out =
                            VectorKernel::evaluate(kernel, &plane_args).map_err(map_op_error)?;
                        for (inst_idx, cell) in plane_out.into_iter().enumerate() {
                            out[inst_idx][t] = cell;
                        }
                    }
                    out
                } else {
                    (0..n)
                        .map(|inst_idx| {
                            let args: Vec<Vec<Option<Decimal>>> = inputs
                                .iter()
                                .map(|&id| values[id][inst_idx].clone())
                                .collect();
                            VectorKernel::evaluate(kernel, &args).map_err(map_op_error)
                        })
                        .collect::<Result<Vec<_>>>()?
                }
            }
        };
        values.push(panel);
    }

    let raw = values.swap_remove(dag.output);
    let mut normalized = Vec::with_capacity(n);
    for col in raw {
        normalized.push(normalize_column(dag, col)?);
    }
    Ok(normalized)
}

fn validate_series_inputs(
    dag: &CompiledDag,
    inputs: &BTreeMap<String, Vec<Option<Decimal>>>,
) -> Result<usize> {
    if dag.inputs.is_empty() {
        let mut len: Option<usize> = None;
        for col in inputs.values() {
            match len {
                None => len = Some(col.len()),
                Some(existing) if existing != col.len() => {
                    return Err(err("QLIB_INPUT_LENGTH_MISMATCH"));
                }
                Some(_) => {}
            }
        }
        return Ok(len.unwrap_or(0));
    }
    let mut len: Option<usize> = None;
    for field in &dag.inputs {
        let col = inputs.get(field).ok_or_else(|| err("QLIB_MISSING_INPUT"))?;
        match len {
            None => len = Some(col.len()),
            Some(existing) if existing != col.len() => {
                return Err(err("QLIB_INPUT_LENGTH_MISMATCH"));
            }
            Some(_) => {}
        }
    }
    Ok(len.unwrap_or(0))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct DagState {
    pub fingerprint: String,
    pub step_count: u64,
    pub operator_states: Vec<Columns>,
}

impl DagState {
    pub fn to_record(&self) -> Value {
        json!({
            "schema_version": 1,
            "fingerprint": self.fingerprint,
            "step_count": self.step_count,
            "operator_states": columns_list_to_json(&self.operator_states),
        })
    }

    pub fn from_record(value: &Value) -> Result<Self> {
        if value.to_string().len() > MAX_STATE_RECORD_BYTES {
            return Err(err("QLIB_STATE_BUDGET"));
        }
        object(
            value,
            &[
                "schema_version",
                "fingerprint",
                "step_count",
                "operator_states",
            ],
        )?;
        if value["schema_version"] != 1 {
            return Err(err("QLIB_STATE_VERSION"));
        }
        let fingerprint = value["fingerprint"]
            .as_str()
            .filter(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
            .ok_or_else(|| err("QLIB_STATE_BINDING"))?
            .to_owned();
        let step_count = value["step_count"]
            .as_u64()
            .ok_or_else(|| err("QLIB_STATE_POSITION"))?;
        let operator_states = columns_list_from_json(&value["operator_states"])?;
        Ok(Self {
            fingerprint,
            step_count,
            operator_states,
        })
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PanelDagState {
    pub fingerprint: String,
    pub instrument_count: usize,
    pub step_count: u64,
    pub instrument_states: Vec<Vec<Columns>>,
}

impl PanelDagState {
    pub fn to_record(&self) -> Value {
        json!({
            "schema_version": 1,
            "fingerprint": self.fingerprint,
            "instrument_count": self.instrument_count,
            "step_count": self.step_count,
            "instrument_states": self.instrument_states.iter().map(|s| columns_list_to_json(s)).collect::<Vec<_>>(),
        })
    }

    pub fn from_record(value: &Value) -> Result<Self> {
        if value.to_string().len() > MAX_STATE_RECORD_BYTES {
            return Err(err("QLIB_STATE_BUDGET"));
        }
        object(
            value,
            &[
                "schema_version",
                "fingerprint",
                "instrument_count",
                "step_count",
                "instrument_states",
            ],
        )?;
        if value["schema_version"] != 1 {
            return Err(err("QLIB_STATE_VERSION"));
        }
        let fingerprint = value["fingerprint"]
            .as_str()
            .filter(|s| s.len() == 64 && s.bytes().all(|b| b.is_ascii_hexdigit()))
            .ok_or_else(|| err("QLIB_STATE_BINDING"))?
            .to_owned();
        let instrument_count = value["instrument_count"]
            .as_u64()
            .and_then(|n| usize::try_from(n).ok())
            .ok_or_else(|| err("QLIB_STATE_LAYOUT"))?;
        let step_count = value["step_count"]
            .as_u64()
            .ok_or_else(|| err("QLIB_STATE_POSITION"))?;
        let raw_list = value["instrument_states"]
            .as_array()
            .filter(|a| a.len() == instrument_count)
            .ok_or_else(|| err("QLIB_STATE_LAYOUT"))?;
        let mut instrument_states = Vec::with_capacity(instrument_count);
        for item in raw_list {
            instrument_states.push(columns_list_from_json(item)?);
        }
        Ok(Self {
            fingerprint,
            instrument_count,
            step_count,
            instrument_states,
        })
    }
}

fn encode_state_decimal(d: &Decimal) -> String {
    let (_, scale) = d.as_bigint_and_exponent();
    if scale.unsigned_abs() <= 64 {
        d.to_plain_string()
    } else {
        d.to_scientific_notation()
    }
}

fn columns_list_to_json(states: &[Columns]) -> Value {
    Value::Array(
        states
            .iter()
            .map(|cols| {
                Value::Array(
                    cols.iter()
                        .map(|col| {
                            Value::Array(
                                col.iter()
                                    .map(|cell| match cell {
                                        None => Value::Null,
                                        Some(d) => Value::String(encode_state_decimal(d)),
                                    })
                                    .collect(),
                            )
                        })
                        .collect(),
                )
            })
            .collect(),
    )
}

fn columns_list_from_json(value: &Value) -> Result<Vec<Columns>> {
    let list = value.as_array().ok_or_else(|| err("QLIB_STATE_LAYOUT"))?;
    let mut states = Vec::with_capacity(list.len());
    for op_state in list {
        let cols_raw = op_state
            .as_array()
            .ok_or_else(|| err("QLIB_STATE_LAYOUT"))?;
        let mut cols = Vec::with_capacity(cols_raw.len());
        for col_raw in cols_raw {
            let cells_raw = col_raw.as_array().ok_or_else(|| err("QLIB_STATE_LAYOUT"))?;
            let mut col = Vec::with_capacity(cells_raw.len());
            for cell_raw in cells_raw {
                if cell_raw.is_null() {
                    col.push(None);
                } else {
                    let s = cell_raw.as_str().ok_or_else(|| err("QLIB_STATE_DECIMAL"))?;
                    if s.len() > 512 {
                        return Err(err("QLIB_NUMERIC_BUDGET"));
                    }
                    let d = Decimal::from_str(s).map_err(|_| err("QLIB_STATE_DECIMAL"))?;
                    validate_cell(&Some(d.clone()))?;
                    col.push(Some(d));
                }
            }
            cols.push(col);
        }
        states.push(cols);
    }
    Ok(states)
}

#[derive(Clone, Debug)]
pub struct EventExecutor {
    dag: Arc<CompiledDag>,
    streams: Vec<Option<Stream>>,
    normalizer: Stream,
    step_count: u64,
}

impl EventExecutor {
    pub(crate) fn new(dag: Arc<CompiledDag>) -> Result<Self> {
        if dag.has_cross_section {
            return Err(err("QLIB_RESEARCH_ONLY_OPERATOR"));
        }
        let mut streams = Vec::with_capacity(dag.instructions.len());
        for inst in &dag.instructions {
            match inst {
                Instruction::Op { kernel, .. } => {
                    streams.push(Some(Stream::new(kernel.clone()).map_err(map_op_error)?));
                }
                Instruction::Lead { .. } => return Err(err("QLIB_LOOKAHEAD_FORBIDDEN")),
                Instruction::Input(_) | Instruction::Constant(_) | Instruction::Compare { .. } => {
                    streams.push(None);
                }
            }
        }
        let normalizer = Stream::new(normalize_kernel()?).map_err(map_op_error)?;
        Ok(Self {
            dag,
            streams,
            normalizer,
            step_count: 0,
        })
    }

    pub fn fingerprint(&self) -> &str {
        &self.dag.fingerprint
    }

    pub fn step_count(&self) -> u64 {
        self.step_count
    }

    pub fn step(&mut self, inputs: &BTreeMap<String, Option<Decimal>>) -> Result<Option<Decimal>> {
        let next = self
            .step_count
            .checked_add(1)
            .ok_or_else(|| err("QLIB_POSITION_OVERFLOW"))?;
        for field in &self.dag.inputs {
            let cell = inputs.get(field).ok_or_else(|| err("QLIB_MISSING_INPUT"))?;
            validate_cell(cell)?;
        }
        let mut candidate = self.streams.clone();
        let mut cells: Vec<Option<Decimal>> = Vec::with_capacity(self.dag.instructions.len());
        for (idx, inst) in self.dag.instructions.iter().enumerate() {
            let cell = match inst {
                Instruction::Input(name) => inputs[name].clone(),
                Instruction::Constant(val) => Some(val.clone()),
                Instruction::Compare { op, lhs, rhs } => {
                    compare_cell(*op, &cells[*lhs], &cells[*rhs])
                }
                Instruction::Op { inputs, .. } => {
                    let args: Vec<Option<Decimal>> =
                        inputs.iter().map(|&id| cells[id].clone()).collect();
                    let stream = candidate[idx].as_mut().expect("op node has stream");
                    EventKernel::step(stream, &args).map_err(map_op_error)?
                }
                Instruction::Lead { .. } => return Err(err("QLIB_LOOKAHEAD_FORBIDDEN")),
            };
            cells.push(cell);
        }
        let out = if matches!(
            self.dag.instructions[self.dag.output],
            Instruction::Op { .. }
        ) {
            cells.swap_remove(self.dag.output)
        } else {
            let mut norm = self.normalizer.clone();
            EventKernel::step(&mut norm, &[cells.swap_remove(self.dag.output)])
                .map_err(map_op_error)?
        };
        self.streams = candidate;
        self.step_count = next;
        Ok(out)
    }

    pub fn capture_state(&self) -> DagState {
        let operator_states = self
            .streams
            .iter()
            .filter_map(|s| s.as_ref().map(EventKernel::capture_state))
            .collect();
        DagState {
            fingerprint: self.dag.fingerprint.clone(),
            step_count: self.step_count,
            operator_states,
        }
    }

    pub fn restore_state(&mut self, state: DagState) -> Result<()> {
        if state.fingerprint != self.dag.fingerprint {
            return Err(err("QLIB_STATE_BINDING"));
        }
        let expected = self.streams.iter().filter(|s| s.is_some()).count();
        if state.operator_states.len() != expected {
            return Err(err("QLIB_STATE_LAYOUT"));
        }
        let fresh = Self::new(self.dag.clone())?;
        let mut candidate = fresh.streams;
        let mut iter = state.operator_states.into_iter();
        for stream in candidate.iter_mut().flatten() {
            let cols = iter.next().expect("checked length");
            EventKernel::restore_state(stream, cols).map_err(map_op_error)?;
            stream
                .validate_step_count(state.step_count)
                .map_err(|_| err("QLIB_STATE_INCONSISTENT"))?;
        }
        self.streams = candidate;
        self.step_count = state.step_count;
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct PanelEventExecutor {
    dag: Arc<CompiledDag>,
    instrument_count: usize,
    /// Per instrument, one `Option<Stream>` per instruction (only populated for `TimeSeries` ops).
    streams: Vec<Vec<Option<Stream>>>,
    normalizer: Stream,
    step_count: u64,
}

impl PanelEventExecutor {
    pub(crate) fn new(dag: Arc<CompiledDag>, instrument_count: usize) -> Result<Self> {
        if instrument_count == 0 {
            return Err(err("QLIB_INVALID_INPUTS"));
        }
        let total_nodes = instrument_count
            .checked_mul(dag.instructions.len().max(1))
            .ok_or_else(|| err("QLIB_RESOURCE_BUDGET"))?;
        let total_state_cells = instrument_count
            .checked_mul(dag.budget.max_state_cells.max(1))
            .ok_or_else(|| err("QLIB_RESOURCE_BUDGET"))?;
        let total_work = instrument_count
            .checked_mul(dag.budget.work_per_row.max(1))
            .ok_or_else(|| err("QLIB_RESOURCE_BUDGET"))?;
        if instrument_count > MAX_CELLS
            || total_nodes > MAX_CELLS
            || total_state_cells > MAX_CELLS
            || total_work > MAX_WINDOW_WORK
        {
            return Err(err("QLIB_RESOURCE_BUDGET"));
        }
        let mut template = Vec::with_capacity(dag.instructions.len());
        for inst in &dag.instructions {
            match inst {
                Instruction::Op { kernel, .. } => {
                    if kernel.operator().spec().shape == ExecutionShape::CrossSection {
                        template.push(None);
                    } else {
                        template.push(Some(Stream::new(kernel.clone()).map_err(map_op_error)?));
                    }
                }
                Instruction::Lead { .. } => return Err(err("QLIB_LOOKAHEAD_FORBIDDEN")),
                Instruction::Input(_) | Instruction::Constant(_) | Instruction::Compare { .. } => {
                    template.push(None);
                }
            }
        }
        let streams = vec![template; instrument_count];
        let normalizer = Stream::new(normalize_kernel()?).map_err(map_op_error)?;
        Ok(Self {
            dag,
            instrument_count,
            streams,
            normalizer,
            step_count: 0,
        })
    }

    pub fn fingerprint(&self) -> &str {
        &self.dag.fingerprint
    }

    pub fn instrument_count(&self) -> usize {
        self.instrument_count
    }

    pub fn step_count(&self) -> u64 {
        self.step_count
    }

    pub fn step(
        &mut self,
        cohort: &[BTreeMap<String, Option<Decimal>>],
    ) -> Result<Vec<Option<Decimal>>> {
        if cohort.len() != self.instrument_count {
            return Err(err("QLIB_INPUT_LENGTH_MISMATCH"));
        }
        let next = self
            .step_count
            .checked_add(1)
            .ok_or_else(|| err("QLIB_POSITION_OVERFLOW"))?;
        for inputs in cohort {
            for field in &self.dag.inputs {
                let cell = inputs.get(field).ok_or_else(|| err("QLIB_MISSING_INPUT"))?;
                validate_cell(cell)?;
            }
        }
        let n = self.instrument_count;
        let mut candidate = self.streams.clone();
        // `cells[node_idx][inst_idx]`
        let mut cells: Vec<Vec<Option<Decimal>>> = Vec::with_capacity(self.dag.instructions.len());
        for (idx, inst) in self.dag.instructions.iter().enumerate() {
            let plane = match inst {
                Instruction::Input(name) => cohort.iter().map(|m| m[name].clone()).collect(),
                Instruction::Constant(val) => vec![Some(val.clone()); n],
                Instruction::Compare { op, lhs, rhs } => (0..n)
                    .map(|i| compare_cell(*op, &cells[*lhs][i], &cells[*rhs][i]))
                    .collect(),
                Instruction::Lead { .. } => return Err(err("QLIB_LOOKAHEAD_FORBIDDEN")),
                Instruction::Op { kernel, inputs, .. } => {
                    if kernel.operator().spec().shape == ExecutionShape::CrossSection {
                        let plane_args: Vec<Vec<Option<Decimal>>> =
                            inputs.iter().map(|&id| cells[id].clone()).collect();
                        VectorKernel::evaluate(kernel, &plane_args).map_err(map_op_error)?
                    } else {
                        let mut out = Vec::with_capacity(n);
                        for (inst_idx, inst_streams) in candidate.iter_mut().enumerate() {
                            let args: Vec<Option<Decimal>> = inputs
                                .iter()
                                .map(|&id| cells[id][inst_idx].clone())
                                .collect();
                            let stream = inst_streams[idx]
                                .as_mut()
                                .expect("time-series op has stream");
                            out.push(EventKernel::step(stream, &args).map_err(map_op_error)?);
                        }
                        out
                    }
                }
            };
            cells.push(plane);
        }
        let raw = cells.swap_remove(self.dag.output);
        let out = if matches!(
            self.dag.instructions[self.dag.output],
            Instruction::Op { .. }
        ) {
            raw
        } else {
            let mut norm = self.normalizer.clone();
            let mut normalized = Vec::with_capacity(n);
            for cell in raw {
                normalized.push(EventKernel::step(&mut norm, &[cell]).map_err(map_op_error)?);
            }
            normalized
        };
        self.streams = candidate;
        self.step_count = next;
        Ok(out)
    }

    pub fn capture_state(&self) -> PanelDagState {
        let instrument_states = self
            .streams
            .iter()
            .map(|inst_streams| {
                inst_streams
                    .iter()
                    .filter_map(|s| s.as_ref().map(EventKernel::capture_state))
                    .collect()
            })
            .collect();
        PanelDagState {
            fingerprint: self.dag.fingerprint.clone(),
            instrument_count: self.instrument_count,
            step_count: self.step_count,
            instrument_states,
        }
    }

    pub fn restore_state(&mut self, state: PanelDagState) -> Result<()> {
        if state.fingerprint != self.dag.fingerprint {
            return Err(err("QLIB_STATE_BINDING"));
        }
        if state.instrument_count != self.instrument_count
            || state.instrument_states.len() != self.instrument_count
        {
            return Err(err("QLIB_STATE_LAYOUT"));
        }
        let expected_ops = self.streams[0].iter().filter(|s| s.is_some()).count();
        let fresh = Self::new(self.dag.clone(), self.instrument_count)?;
        let mut candidate = fresh.streams;
        for (inst_streams, raw_ops) in candidate.iter_mut().zip(state.instrument_states) {
            if raw_ops.len() != expected_ops {
                return Err(err("QLIB_STATE_LAYOUT"));
            }
            let mut iter = raw_ops.into_iter();
            for stream in inst_streams.iter_mut().flatten() {
                let cols = iter.next().expect("checked length");
                EventKernel::restore_state(stream, cols).map_err(map_op_error)?;
                stream
                    .validate_step_count(state.step_count)
                    .map_err(|_| err("QLIB_STATE_INCONSISTENT"))?;
            }
        }
        self.streams = candidate;
        self.step_count = state.step_count;
        Ok(())
    }
}
