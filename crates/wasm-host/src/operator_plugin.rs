//! Sandboxed L3 WASM extended operator handle and stateful incremental event stream.

use crate::config::ResourceBudget;
use crate::contract::{
    ArtifactBinding, CallOutcome, EXTENDED_OPERATOR_INTERFACE, Error, NUMERIC_POLICY,
    OperatorMetadata, PluginKind, ReadyCertificate, Result, format_host_decimal,
    parse_guest_decimal, validate_canonical_parameters,
};
use crate::sandbox::{
    CompiledComponent, METADATA_CALL_LIFT_BYTES, SMALL_CALL_LIFT_BYTES, SandboxInstance,
    encode_params, expect_bytes, expect_list, expect_option, expect_record, expect_string,
    expect_u32, record_field, unwrap_plugin_result,
};
use onlyalpha_operators::algebra::{Decimal, Error as OperatorError};
use onlyalpha_operators::execution::VectorKernel;
use std::collections::BTreeMap;
use std::sync::Arc;
use wasmtime::component::Val;

/// Hard upper bound on declared operator input arity to prevent certification/vector DoS.
pub const MAX_OPERATOR_ARITY: u32 = 16;
/// Hard upper bound on declared operator warmup to prevent host DoS during admission certification.
pub const MAX_OPERATOR_WARMUP: u32 = 512;
/// Hard upper bound on total cells (`arity * rows`) in a single vectorized WASM call.
pub const MAX_VECTOR_CELLS: usize = 200_000;

/// Uncertified extended operator used strictly inside the admission pipeline.
/// Cannot be exposed as READY or registered in the active manager until certified.
pub(crate) struct UnverifiedExtendedOperator {
    compiled: Arc<CompiledComponent>,
    metadata: OperatorMetadata,
    budget: ResourceBudget,
}

impl UnverifiedExtendedOperator {
    pub(crate) fn load(compiled: Arc<CompiledComponent>, budget: ResourceBudget) -> Result<Self> {
        let mut instance = SandboxInstance::instantiate(Arc::clone(&compiled), budget)?;
        let (val, _) = instance.call_interface_func(
            EXTENDED_OPERATOR_INTERFACE,
            "metadata",
            &[],
            METADATA_CALL_LIFT_BYTES,
        )?;
        let metadata = decode_operator_metadata(&val)?;
        Ok(Self {
            compiled,
            metadata,
            budget,
        })
    }

    pub(crate) fn metadata(&self) -> &OperatorMetadata {
        &self.metadata
    }

    pub(crate) fn budget(&self) -> ResourceBudget {
        self.budget
    }

    pub(crate) fn artifact_sha256(&self) -> &str {
        self.compiled.artifact_sha256()
    }

    pub(crate) fn evaluate_vector_with_fuel(
        &self,
        columns: &[Vec<Option<Decimal>>],
        params: &BTreeMap<String, String>,
        fuel_limit: u64,
    ) -> Result<CallOutcome<Vec<Option<Decimal>>>> {
        evaluate_vector_inner(
            &self.compiled,
            &self.metadata,
            self.budget,
            columns,
            params,
            fuel_limit,
        )
    }

    pub(crate) fn new_stream_with_fuel(
        &self,
        params: &BTreeMap<String, String>,
        fuel_limit: u64,
    ) -> Result<(WasmOperatorStream, u64)> {
        WasmOperatorStream::new_with_fuel(
            Arc::clone(&self.compiled),
            self.metadata.clone(),
            self.budget,
            params,
            fuel_limit,
        )
    }

    pub(crate) fn into_certified(
        self,
        canonical_parameters: BTreeMap<String, String>,
        certificate: ReadyCertificate,
    ) -> WasmExtendedOperator {
        WasmExtendedOperator {
            compiled: self.compiled,
            metadata: self.metadata,
            canonical_parameters,
            budget: self.budget,
            certificate,
        }
    }
}

/// Certified READY L3 WASM extended operator supporting paired vector and event execution.
#[derive(Clone)]
pub struct WasmExtendedOperator {
    compiled: Arc<CompiledComponent>,
    metadata: OperatorMetadata,
    canonical_parameters: BTreeMap<String, String>,
    budget: ResourceBudget,
    certificate: ReadyCertificate,
}

impl WasmExtendedOperator {
    pub fn metadata(&self) -> &OperatorMetadata {
        &self.metadata
    }

    pub fn certificate(&self) -> &ReadyCertificate {
        &self.certificate
    }

    pub fn canonical_parameters(&self) -> &BTreeMap<String, String> {
        &self.canonical_parameters
    }

    pub fn artifact_sha256(&self) -> &str {
        self.compiled.artifact_sha256()
    }

    pub fn binding(&self) -> ArtifactBinding {
        ArtifactBinding {
            plugin_id: self.certificate.plugin_id.clone(),
            kind: PluginKind::ExtendedOperator,
            artifact_sha256: self.compiled.artifact_sha256().to_owned(),
            wit_contract_version: self.compiled.wit_contract_version().to_owned(),
            host_version: self.certificate.host_version.clone(),
            canonical_parameters: self.canonical_parameters.clone(),
        }
    }

    /// Executes the vectorized batch kernel inside a fresh bounded WASM store.
    pub fn evaluate_vector(
        &self,
        columns: &[Vec<Option<Decimal>>],
    ) -> Result<CallOutcome<Vec<Option<Decimal>>>> {
        evaluate_vector_inner(
            &self.compiled,
            &self.metadata,
            self.budget,
            columns,
            &self.canonical_parameters,
            self.budget.max_fuel_per_call,
        )
    }

    /// Creates a fresh isolated stateful incremental event stream for Backtest / SIM / LIVE.
    /// Dropping the returned stream immediately releases its WASM linear memory.
    pub fn new_stream(&self) -> Result<WasmOperatorStream> {
        let (stream, _) = WasmOperatorStream::new_with_fuel(
            Arc::clone(&self.compiled),
            self.metadata.clone(),
            self.budget,
            &self.canonical_parameters,
            self.budget.max_fuel_per_call,
        )?;
        Ok(stream)
    }

    pub(crate) fn strong_ref_count(&self) -> usize {
        Arc::strong_count(&self.compiled)
    }
}

impl VectorKernel for WasmExtendedOperator {
    fn evaluate(
        &self,
        columns: &[Vec<Option<Decimal>>],
    ) -> std::result::Result<Vec<Option<Decimal>>, OperatorError> {
        self.evaluate_vector(columns)
            .map(|outcome| outcome.value)
            .map_err(|err| match err {
                Error::FuelExhausted { .. }
                | Error::MemoryLimitExceeded { .. }
                | Error::HostLiftLimitExceeded { .. } => OperatorError::BudgetExceeded,
                Error::InvalidHostInput(_) | Error::InvalidBudget(_) => {
                    OperatorError::InvalidInputs
                }
                _ => OperatorError::NumericFailure,
            })
    }
}

/// Stateful incremental event-kernel instance for one certified L3 WASM extended operator.
///
/// Enforces Fail-Closed poisoning: if any guest invocation triggers a trap, fuel exhaustion,
/// memory/lift limit violation, guest error, or invalid guest output, the stream permanently
/// refuses all further calls because guest linear memory may have been partially mutated.
pub struct WasmOperatorStream {
    instance: SandboxInstance,
    metadata: OperatorMetadata,
    poisoned: bool,
}

impl WasmOperatorStream {
    fn new_with_fuel(
        compiled: Arc<CompiledComponent>,
        metadata: OperatorMetadata,
        budget: ResourceBudget,
        params: &BTreeMap<String, String>,
        fuel_limit: u64,
    ) -> Result<(Self, u64)> {
        validate_canonical_parameters(params)?;
        let mut instance = SandboxInstance::instantiate_with_fuel(compiled, budget, fuel_limit)?;
        let (val, init_fuel) = instance.call_interface_func_with_limits(
            EXTENDED_OPERATOR_INTERFACE,
            "init-event",
            &[encode_params(params)],
            SMALL_CALL_LIFT_BYTES,
            fuel_limit,
        )?;
        unwrap_plugin_result(val, "extended-operator#init-event")?;
        Ok((
            Self {
                instance,
                metadata,
                poisoned: false,
            },
            init_fuel,
        ))
    }

    pub fn is_poisoned(&self) -> bool {
        self.poisoned
    }

    fn ensure_healthy(&self) -> Result<()> {
        if self.poisoned {
            return Err(Error::GuestTrap(
                "operator stream is poisoned after a prior guest error or sandbox fault; recreate stream or restore from last verified snapshot".into(),
            ));
        }
        Ok(())
    }

    pub fn step(&mut self, values: &[Option<Decimal>]) -> Result<CallOutcome<Option<Decimal>>> {
        let fuel = self.instance.budget().max_fuel_per_call;
        self.step_with_fuel(values, fuel)
    }

    pub(crate) fn step_with_fuel(
        &mut self,
        values: &[Option<Decimal>],
        fuel_limit: u64,
    ) -> Result<CallOutcome<Option<Decimal>>> {
        self.ensure_healthy()?;
        if values.len() != self.metadata.input_arity as usize {
            return Err(Error::InvalidHostInput(format!(
                "step input arity mismatch: expected {}, got {}",
                self.metadata.input_arity,
                values.len()
            )));
        }
        let encoded_items = values
            .iter()
            .map(|v| encode_opt_decimal(v, "extended-operator#step-event.values[]"))
            .collect::<Result<Vec<_>>>()?;
        let encoded = Val::List(encoded_items);
        let outcome = (|| -> Result<CallOutcome<Option<Decimal>>> {
            let (val, fuel_consumed) = self.instance.call_interface_func_with_limits(
                EXTENDED_OPERATOR_INTERFACE,
                "step-event",
                &[encoded],
                SMALL_CALL_LIFT_BYTES,
                fuel_limit,
            )?;
            let ok_val =
                unwrap_plugin_result(val, "extended-operator#step-event")?.ok_or_else(|| {
                    Error::InvalidGuestOutput("step-event returned empty ok payload".into())
                })?;
            let parsed = decode_opt_decimal(&ok_val, "extended-operator#step-event")?;
            Ok(CallOutcome {
                value: parsed,
                fuel_consumed,
            })
        })();
        if outcome.is_err() {
            self.poisoned = true;
        }
        outcome
    }

    pub fn capture_state(&mut self) -> Result<CallOutcome<Vec<u8>>> {
        let fuel = self.instance.budget().max_fuel_per_call;
        self.capture_state_with_fuel(fuel)
    }

    pub(crate) fn capture_state_with_fuel(
        &mut self,
        fuel_limit: u64,
    ) -> Result<CallOutcome<Vec<u8>>> {
        self.ensure_healthy()?;
        let budget = self.instance.budget();
        let max_bytes = budget.max_snapshot_bytes;
        let lift_limit = max_bytes
            .saturating_mul(std::mem::size_of::<Val>())
            .saturating_add(8 * 1024)
            .min(budget.max_host_lift_bytes);
        let outcome = (|| -> Result<CallOutcome<Vec<u8>>> {
            let (val, fuel_consumed) = self.instance.call_interface_func_with_limits(
                EXTENDED_OPERATOR_INTERFACE,
                "capture-state",
                &[],
                lift_limit,
                fuel_limit,
            )?;
            let ok_val =
                unwrap_plugin_result(val, "extended-operator#capture-state")?.ok_or_else(|| {
                    Error::InvalidGuestOutput("capture-state returned empty ok payload".into())
                })?;
            let snapshot = expect_bytes(&ok_val, max_bytes, "extended-operator#capture-state")?;
            Ok(CallOutcome {
                value: snapshot,
                fuel_consumed,
            })
        })();
        if outcome.is_err() {
            self.poisoned = true;
        }
        outcome
    }

    pub fn restore_state(&mut self, snapshot: &[u8]) -> Result<u64> {
        let fuel = self.instance.budget().max_fuel_per_call;
        self.restore_state_with_fuel(snapshot, fuel)
    }

    pub(crate) fn restore_state_with_fuel(
        &mut self,
        snapshot: &[u8],
        fuel_limit: u64,
    ) -> Result<u64> {
        self.ensure_healthy()?;
        let max_bytes = self.instance.budget().max_snapshot_bytes;
        if snapshot.len() > max_bytes {
            return Err(Error::InvalidHostInput(format!(
                "snapshot size {} exceeds max_snapshot_bytes {max_bytes}",
                snapshot.len()
            )));
        }
        let encoded = Val::List(snapshot.iter().map(|b| Val::U8(*b)).collect());
        let outcome = (|| -> Result<u64> {
            let (val, fuel_consumed) = self.instance.call_interface_func_with_limits(
                EXTENDED_OPERATOR_INTERFACE,
                "restore-state",
                &[encoded],
                SMALL_CALL_LIFT_BYTES,
                fuel_limit,
            )?;
            unwrap_plugin_result(val, "extended-operator#restore-state")?;
            Ok(fuel_consumed)
        })();
        if outcome.is_err() {
            self.poisoned = true;
        }
        outcome
    }

    pub fn live_memory_bytes(&self) -> usize {
        self.instance.live_memory_bytes()
    }
}

fn evaluate_vector_inner(
    compiled: &Arc<CompiledComponent>,
    metadata: &OperatorMetadata,
    budget: ResourceBudget,
    columns: &[Vec<Option<Decimal>>],
    params: &BTreeMap<String, String>,
    fuel_limit: u64,
) -> Result<CallOutcome<Vec<Option<Decimal>>>> {
    validate_canonical_parameters(params)?;
    if columns.len() != metadata.input_arity as usize {
        return Err(Error::InvalidHostInput(format!(
            "vector input arity mismatch: expected {}, got {}",
            metadata.input_arity,
            columns.len()
        )));
    }
    let expected_len = columns.first().map_or(0, Vec::len);
    if columns.iter().any(|col| col.len() != expected_len) {
        return Err(Error::InvalidHostInput(
            "vector input columns have mismatched lengths".into(),
        ));
    }
    if expected_len > budget.max_output_items {
        return Err(Error::InvalidHostInput(format!(
            "vector input length {expected_len} exceeds max_output_items {}",
            budget.max_output_items
        )));
    }
    let total_cells = columns
        .len()
        .checked_mul(expected_len)
        .ok_or_else(|| Error::InvalidHostInput("vector cell count overflow".into()))?;
    if total_cells > MAX_VECTOR_CELLS {
        return Err(Error::InvalidHostInput(format!(
            "vector total cell count {total_cells} exceeds MAX_VECTOR_CELLS {MAX_VECTOR_CELLS}"
        )));
    }

    let mut encoded_col_records = Vec::with_capacity(columns.len());
    for col in columns {
        let mut encoded_vals = Vec::with_capacity(col.len());
        for cell in col {
            encoded_vals.push(encode_opt_decimal(
                cell,
                "extended-operator#eval-vector.columns[][]",
            )?);
        }
        encoded_col_records.push(Val::Record(vec![(
            "values".into(),
            Val::List(encoded_vals),
        )]));
    }
    let encoded_columns = Val::List(encoded_col_records);

    let per_item_lift = std::mem::size_of::<Val>()
        .saturating_mul(2)
        .saturating_add(64);
    let lift_limit = expected_len
        .saturating_mul(per_item_lift)
        .saturating_add(8 * 1024)
        .min(budget.max_host_lift_bytes);

    let mut instance =
        SandboxInstance::instantiate_with_fuel(Arc::clone(compiled), budget, fuel_limit)?;
    let (val, fuel_consumed) = instance.call_interface_func_with_limits(
        EXTENDED_OPERATOR_INTERFACE,
        "eval-vector",
        &[encoded_columns, encode_params(params)],
        lift_limit,
        fuel_limit,
    )?;
    let ok_val = unwrap_plugin_result(val, "extended-operator#eval-vector")?
        .ok_or_else(|| Error::InvalidGuestOutput("eval-vector returned empty ok payload".into()))?;
    let fields = expect_record(&ok_val, "extended-operator#eval-vector")?;
    let values = expect_list(
        record_field(&fields, "values", "extended-operator#eval-vector")?,
        "extended-operator#eval-vector.values",
    )?;
    if values.len() != expected_len {
        return Err(Error::InvalidGuestOutput(format!(
            "eval-vector output length {} does not match input length {expected_len}",
            values.len()
        )));
    }
    let mut out = Vec::with_capacity(values.len());
    for item in values {
        out.push(decode_opt_decimal(
            item,
            "extended-operator#eval-vector.values[]",
        )?);
    }
    Ok(CallOutcome {
        value: out,
        fuel_consumed,
    })
}

fn decode_operator_metadata(val: &Val) -> Result<OperatorMetadata> {
    let ctx = "extended-operator#metadata";
    let fields = expect_record(val, ctx)?;
    let operator_id = expect_string(record_field(&fields, "operator-id", ctx)?, ctx)?.to_owned();
    let version = expect_string(record_field(&fields, "version", ctx)?, ctx)?.to_owned();
    let input_arity = expect_u32(record_field(&fields, "input-arity", ctx)?, ctx)?;
    let warmup = expect_u32(record_field(&fields, "warmup", ctx)?, ctx)?;
    let numeric_policy =
        expect_string(record_field(&fields, "numeric-policy", ctx)?, ctx)?.to_owned();

    if operator_id.trim().is_empty() || operator_id.len() > 256 {
        return Err(Error::InvalidGuestOutput(
            "operator-id must be non-empty and <= 256 bytes".into(),
        ));
    }
    if version.trim().is_empty() || version.len() > 64 {
        return Err(Error::InvalidGuestOutput(
            "operator version must be non-empty and <= 64 bytes".into(),
        ));
    }
    if input_arity == 0 || input_arity > MAX_OPERATOR_ARITY {
        return Err(Error::InvalidGuestOutput(format!(
            "operator input-arity must be in [1, {MAX_OPERATOR_ARITY}], got {input_arity}"
        )));
    }
    if warmup == 0 || warmup > MAX_OPERATOR_WARMUP {
        return Err(Error::InvalidGuestOutput(format!(
            "operator warmup must be in [1, {MAX_OPERATOR_WARMUP}], got {warmup}"
        )));
    }
    if numeric_policy != NUMERIC_POLICY {
        return Err(Error::InvalidGuestOutput(format!(
            "unsupported numeric-policy '{numeric_policy}', required '{NUMERIC_POLICY}'"
        )));
    }

    Ok(OperatorMetadata {
        operator_id,
        version,
        input_arity,
        warmup,
        numeric_policy,
    })
}

fn encode_opt_decimal(value: &Option<Decimal>, field: &str) -> Result<Val> {
    match value {
        Some(d) => Ok(Val::Option(Some(Box::new(Val::String(
            format_host_decimal(d, field)?,
        ))))),
        None => Ok(Val::Option(None)),
    }
}

fn decode_opt_decimal(val: &Val, ctx: &str) -> Result<Option<Decimal>> {
    match expect_option(val, ctx)? {
        Some(inner) => {
            let raw = expect_string(inner, ctx)?;
            Ok(Some(parse_guest_decimal(raw, ctx)?))
        }
        None => Ok(None),
    }
}
