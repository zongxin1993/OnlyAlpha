//! Pure deterministic WebAssembly Component Model sandbox and ABI value codecs.
//!
//! Zero `unsafe` code is used anywhere in this crate. Every guest component is validated
//! before instantiation to guarantee zero WASI or ambient imports, exact WIT interface
//! exports and function signatures, explicit per-call fuel metering, bounded host lifting
//! (`hostcall_fuel`), and bounded linear memory.

use crate::config::{HostMetrics, ResourceBudget, SandboxState, WasmHostEngine};
use crate::contract::{
    CallOutcome, Error, PluginKind, Result, WIT_CONTRACT_VERSION, is_valid_sha256_hex, sha256_hex,
};
use std::collections::BTreeMap;
use std::sync::Arc;
use wasmtime::component::{
    Component, Instance, Linker, Val,
    types::{ComponentFunc, ComponentItem, Type},
};
use wasmtime::{Store, Trap};

// Wasmtime's remaining fuel saturates at zero, so exact exhaustion needs a distinct reading.
const FUEL_METER_RESERVE: u64 = 1;

/// Maximum guest `plugin-error.code` byte length.
pub(crate) const MAX_GUEST_ERROR_CODE_BYTES: usize = 128;
/// Maximum guest `plugin-error.message` byte length.
pub(crate) const MAX_GUEST_ERROR_MESSAGE_BYTES: usize = 1024;
/// Tight host-side lifting budget for small fixed-shape calls (`init-event`, `step-event`, `restore-state`).
pub(crate) const SMALL_CALL_LIFT_BYTES: usize = 16 * 1024;
/// Tight host-side lifting budget for `market-rule#validate-order`.
pub(crate) const MARKET_RULE_LIFT_BYTES: usize = 32 * 1024;
/// Tight host-side lifting budget for `metadata` calls (including `required-factors` list).
pub(crate) const METADATA_CALL_LIFT_BYTES: usize = 64 * 1024;

#[derive(Clone, Copy)]
enum ExpectedType {
    Bool,
    U8,
    U32,
    S64,
    String,
    List(&'static ExpectedType),
    Option(&'static ExpectedType),
    Result {
        ok: Option<&'static ExpectedType>,
        err: Option<&'static ExpectedType>,
    },
    Enum(&'static [&'static str]),
    Record(&'static [(&'static str, &'static ExpectedType)]),
}

struct ExpectedFunc {
    name: &'static str,
    params: &'static [(&'static str, &'static ExpectedType)],
    result: &'static ExpectedType,
}

static T_BOOL: ExpectedType = ExpectedType::Bool;
static T_U8: ExpectedType = ExpectedType::U8;
static T_U32: ExpectedType = ExpectedType::U32;
static T_S64: ExpectedType = ExpectedType::S64;
static T_STRING: ExpectedType = ExpectedType::String;
static T_OPT_STRING: ExpectedType = ExpectedType::Option(&T_STRING);
static T_LIST_STRING: ExpectedType = ExpectedType::List(&T_STRING);
static T_LIST_OPT_STRING: ExpectedType = ExpectedType::List(&T_OPT_STRING);
static T_LIST_U8: ExpectedType = ExpectedType::List(&T_U8);

static T_PARAM_ENTRY: ExpectedType =
    ExpectedType::Record(&[("key", &T_STRING), ("value", &T_STRING)]);
static T_LIST_PARAM_ENTRY: ExpectedType = ExpectedType::List(&T_PARAM_ENTRY);

static T_PLUGIN_ERROR: ExpectedType =
    ExpectedType::Record(&[("code", &T_STRING), ("message", &T_STRING)]);

static T_DECIMAL_COLUMN: ExpectedType = ExpectedType::Record(&[("values", &T_LIST_OPT_STRING)]);
static T_LIST_DECIMAL_COLUMN: ExpectedType = ExpectedType::List(&T_DECIMAL_COLUMN);

static T_OPERATOR_METADATA: ExpectedType = ExpectedType::Record(&[
    ("operator-id", &T_STRING),
    ("version", &T_STRING),
    ("input-arity", &T_U32),
    ("warmup", &T_U32),
    ("numeric-policy", &T_STRING),
]);

static T_RES_DECIMAL_COLUMN: ExpectedType = ExpectedType::Result {
    ok: Some(&T_DECIMAL_COLUMN),
    err: Some(&T_PLUGIN_ERROR),
};
static T_RES_UNIT: ExpectedType = ExpectedType::Result {
    ok: None,
    err: Some(&T_PLUGIN_ERROR),
};
static T_RES_OPT_STRING: ExpectedType = ExpectedType::Result {
    ok: Some(&T_OPT_STRING),
    err: Some(&T_PLUGIN_ERROR),
};
static T_RES_LIST_U8: ExpectedType = ExpectedType::Result {
    ok: Some(&T_LIST_U8),
    err: Some(&T_PLUGIN_ERROR),
};

static EXTENDED_OPERATOR_SIGS: &[ExpectedFunc] = &[
    ExpectedFunc {
        name: "metadata",
        params: &[],
        result: &T_OPERATOR_METADATA,
    },
    ExpectedFunc {
        name: "eval-vector",
        params: &[
            ("columns", &T_LIST_DECIMAL_COLUMN),
            ("params", &T_LIST_PARAM_ENTRY),
        ],
        result: &T_RES_DECIMAL_COLUMN,
    },
    ExpectedFunc {
        name: "init-event",
        params: &[("params", &T_LIST_PARAM_ENTRY)],
        result: &T_RES_UNIT,
    },
    ExpectedFunc {
        name: "step-event",
        params: &[("values", &T_LIST_OPT_STRING)],
        result: &T_RES_OPT_STRING,
    },
    ExpectedFunc {
        name: "capture-state",
        params: &[],
        result: &T_RES_LIST_U8,
    },
    ExpectedFunc {
        name: "restore-state",
        params: &[("snapshot", &T_LIST_U8)],
        result: &T_RES_UNIT,
    },
];

static T_ORDER_SIDE: ExpectedType = ExpectedType::Enum(&["buy", "sell"]);
static T_ORDER_TYPE: ExpectedType = ExpectedType::Enum(&["market", "limit"]);
static T_TIME_IN_FORCE: ExpectedType = ExpectedType::Enum(&["day", "gtc", "ioc", "fok"]);

static T_MARKET_RULE_METADATA: ExpectedType = ExpectedType::Record(&[
    ("plugin-id", &T_STRING),
    ("market-id", &T_STRING),
    ("version", &T_STRING),
]);
static T_MARKET_RULE_INPUT: ExpectedType = ExpectedType::Record(&[
    ("trading-day", &T_STRING),
    ("instrument-id", &T_STRING),
    ("side", &T_ORDER_SIDE),
    ("order-type", &T_ORDER_TYPE),
    ("quantity", &T_STRING),
    ("price", &T_OPT_STRING),
    ("reference-price", &T_OPT_STRING),
    ("settled-quantity", &T_STRING),
    ("rule-version", &T_STRING),
]);
static T_MARKET_RULE_DECISION: ExpectedType = ExpectedType::Record(&[
    ("allowed", &T_BOOL),
    ("reject-code", &T_OPT_STRING),
    ("normalized-quantity", &T_OPT_STRING),
    ("normalized-price", &T_OPT_STRING),
    ("fee-estimate", &T_OPT_STRING),
]);
static T_RES_MARKET_RULE_DECISION: ExpectedType = ExpectedType::Result {
    ok: Some(&T_MARKET_RULE_DECISION),
    err: Some(&T_PLUGIN_ERROR),
};

static MARKET_RULE_SIGS: &[ExpectedFunc] = &[
    ExpectedFunc {
        name: "metadata",
        params: &[],
        result: &T_MARKET_RULE_METADATA,
    },
    ExpectedFunc {
        name: "validate-order",
        params: &[("input", &T_MARKET_RULE_INPUT)],
        result: &T_RES_MARKET_RULE_DECISION,
    },
];

static T_NAMED_FACTOR: ExpectedType =
    ExpectedType::Record(&[("name", &T_STRING), ("value", &T_OPT_STRING)]);
static T_LIST_NAMED_FACTOR: ExpectedType = ExpectedType::List(&T_NAMED_FACTOR);

static T_READONLY_POSITION: ExpectedType = ExpectedType::Record(&[
    ("instrument-id", &T_STRING),
    ("quantity", &T_STRING),
    ("average-cost", &T_OPT_STRING),
]);
static T_LIST_READONLY_POSITION: ExpectedType = ExpectedType::List(&T_READONLY_POSITION);

static T_READONLY_ACCOUNT_STATE: ExpectedType = ExpectedType::Record(&[
    ("timestamp-ns", &T_S64),
    ("cash-available", &T_STRING),
    ("total-equity", &T_STRING),
    ("positions", &T_LIST_READONLY_POSITION),
]);

static T_ORDER_INTENT: ExpectedType = ExpectedType::Record(&[
    ("instrument-id", &T_STRING),
    ("side", &T_ORDER_SIDE),
    ("order-type", &T_ORDER_TYPE),
    ("quantity", &T_STRING),
    ("limit-price", &T_OPT_STRING),
    ("time-in-force", &T_TIME_IN_FORCE),
    ("reason-code", &T_STRING),
]);
static T_LIST_ORDER_INTENT: ExpectedType = ExpectedType::List(&T_ORDER_INTENT);
static T_RES_ORDER_INTENTS: ExpectedType = ExpectedType::Result {
    ok: Some(&T_LIST_ORDER_INTENT),
    err: Some(&T_PLUGIN_ERROR),
};

static T_STRATEGY_METADATA: ExpectedType = ExpectedType::Record(&[
    ("strategy-id", &T_STRING),
    ("version", &T_STRING),
    ("required-factors", &T_LIST_STRING),
]);

static STRATEGY_SIGS: &[ExpectedFunc] = &[
    ExpectedFunc {
        name: "metadata",
        params: &[],
        result: &T_STRATEGY_METADATA,
    },
    ExpectedFunc {
        name: "on-event",
        params: &[
            ("factors", &T_LIST_NAMED_FACTOR),
            ("readonly-state", &T_READONLY_ACCOUNT_STATE),
            ("params", &T_LIST_PARAM_ENTRY),
        ],
        result: &T_RES_ORDER_INTENTS,
    },
];

/// Compiled, SHA-256 verified, import-free WebAssembly Component ready for isolated instantiation.
pub(crate) struct CompiledComponent {
    engine: Arc<WasmHostEngine>,
    component: Component,
    artifact_sha256: String,
}

impl CompiledComponent {
    pub(crate) fn compile(
        engine: Arc<WasmHostEngine>,
        kind: PluginKind,
        wasm_bytes: &[u8],
        expected_sha256: &str,
        budget: ResourceBudget,
    ) -> Result<Self> {
        budget.validate()?;
        if wasm_bytes.is_empty() {
            return Err(Error::InvalidArtifact("empty wasm artifact".into()));
        }
        if wasm_bytes.len() > budget.max_artifact_bytes {
            return Err(Error::InvalidArtifact(format!(
                "artifact size {} exceeds max_artifact_bytes {}",
                wasm_bytes.len(),
                budget.max_artifact_bytes
            )));
        }
        if !is_valid_sha256_hex(expected_sha256) {
            return Err(Error::InvalidArtifact(
                "expected_sha256 must be 64 lowercase hex characters".into(),
            ));
        }
        let actual_sha256 = sha256_hex(wasm_bytes);
        if actual_sha256 != expected_sha256 {
            return Err(Error::Sha256Mismatch {
                expected: expected_sha256.to_owned(),
                actual: actual_sha256,
            });
        }

        let component = Component::new(engine.engine(), wasm_bytes).map_err(|err| {
            Error::InvalidArtifact(format!("component compilation failed: {err:?}"))
        })?;

        validate_pure_component(engine.engine(), &component, kind)?;

        Ok(Self {
            engine,
            component,
            artifact_sha256: actual_sha256,
        })
    }

    pub(crate) fn engine(&self) -> &Arc<WasmHostEngine> {
        &self.engine
    }

    pub(crate) fn component(&self) -> &Component {
        &self.component
    }

    pub(crate) fn artifact_sha256(&self) -> &str {
        &self.artifact_sha256
    }

    pub(crate) fn wit_contract_version(&self) -> &'static str {
        WIT_CONTRACT_VERSION
    }
}

fn validate_pure_component(
    engine: &wasmtime::Engine,
    component: &Component,
    kind: PluginKind,
) -> Result<()> {
    let comp_ty = component.component_type();

    // ADR 0152 §2.6: L3 WASM plugins are strictly pure deterministic computation.
    // Reject ANY import (especially WASI clock, random, filesystem, network, process, env).
    if let Some((import_name, _)) = comp_ty.imports(engine).next() {
        return Err(Error::ForbiddenImport {
            import_name: import_name.to_owned(),
        });
    }

    let expected_interface = kind.wit_interface();
    let required_sigs = match kind {
        PluginKind::ExtendedOperator => EXTENDED_OPERATOR_SIGS,
        PluginKind::MarketRule => MARKET_RULE_SIGS,
        PluginKind::Strategy => STRATEGY_SIGS,
    };

    // Reject any extra non-type top-level exports beyond the single expected WIT interface.
    let mut found_expected = false;
    for (export_name, export_item) in comp_ty.exports(engine) {
        if export_name == expected_interface {
            found_expected = true;
            continue;
        }
        if !matches!(export_item.ty, ComponentItem::Type(_)) {
            return Err(Error::ContractExportMismatch {
                expected: expected_interface.to_owned(),
                detail: format!("unexpected extra component export '{export_name}'"),
            });
        }
    }

    let Some(export_item) = found_expected
        .then(|| comp_ty.get_export(engine, expected_interface))
        .flatten()
    else {
        return Err(Error::ContractExportMismatch {
            expected: expected_interface.to_owned(),
            detail: "required versioned WIT interface export is missing".into(),
        });
    };

    let ComponentItem::ComponentInstance(iface_ty) = export_item.ty else {
        return Err(Error::ContractExportMismatch {
            expected: expected_interface.to_owned(),
            detail: "exported item is not a WIT interface instance".into(),
        });
    };

    let mut exported_funcs: BTreeMap<String, ComponentFunc> = BTreeMap::new();
    for (name, item) in iface_ty.exports(engine) {
        if let ComponentItem::ComponentFunc(func_ty) = item.ty {
            exported_funcs.insert(name.to_owned(), func_ty);
        }
    }

    if exported_funcs.len() != required_sigs.len() {
        return Err(Error::ContractExportMismatch {
            expected: expected_interface.to_owned(),
            detail: format!(
                "interface exports {} functions, expected exactly {}",
                exported_funcs.len(),
                required_sigs.len()
            ),
        });
    }

    for expected in required_sigs {
        let Some(func_ty) = exported_funcs.get(expected.name) else {
            return Err(Error::ContractExportMismatch {
                expected: format!("{expected_interface}#{}", expected.name),
                detail: "required WIT interface function is missing".into(),
            });
        };
        validate_func_signature(expected_interface, func_ty, expected)?;
    }

    Ok(())
}

fn validate_func_signature(
    interface_name: &str,
    func_ty: &ComponentFunc,
    expected: &ExpectedFunc,
) -> Result<()> {
    let fq = format!("{interface_name}#{}", expected.name);
    if func_ty.async_() {
        return Err(Error::ContractExportMismatch {
            expected: fq,
            detail: "async component functions are forbidden".into(),
        });
    }
    let actual_params: Vec<(&str, Type)> = func_ty.params().collect();
    if actual_params.len() != expected.params.len() {
        return Err(Error::ContractExportMismatch {
            expected: fq,
            detail: format!(
                "parameter count mismatch: expected {}, got {}",
                expected.params.len(),
                actual_params.len()
            ),
        });
    }
    for (idx, ((actual_name, actual_ty), (expected_name, expected_ty))) in
        actual_params.iter().zip(expected.params.iter()).enumerate()
    {
        if actual_name != expected_name {
            return Err(Error::ContractExportMismatch {
                expected: fq,
                detail: format!(
                    "parameter #{idx} name mismatch: expected '{expected_name}', got '{actual_name}'"
                ),
            });
        }
        if let Err(reason) = match_wit_type(actual_ty, expected_ty) {
            return Err(Error::ContractExportMismatch {
                expected: fq,
                detail: format!("parameter '{expected_name}' type mismatch: {reason}"),
            });
        }
    }

    let actual_results: Vec<Type> = func_ty.results().collect();
    if actual_results.len() != 1 {
        return Err(Error::ContractExportMismatch {
            expected: fq,
            detail: format!(
                "result count mismatch: expected 1, got {}",
                actual_results.len()
            ),
        });
    }
    if let Err(reason) = match_wit_type(&actual_results[0], expected.result) {
        return Err(Error::ContractExportMismatch {
            expected: fq,
            detail: format!("return type mismatch: {reason}"),
        });
    }

    Ok(())
}

fn match_wit_type(actual: &Type, expected: &ExpectedType) -> std::result::Result<(), String> {
    match (actual, expected) {
        (Type::Bool, ExpectedType::Bool)
        | (Type::U8, ExpectedType::U8)
        | (Type::U32, ExpectedType::U32)
        | (Type::S64, ExpectedType::S64)
        | (Type::String, ExpectedType::String) => Ok(()),
        (Type::List(list_ty), ExpectedType::List(expected_elem)) => {
            match_wit_type(&list_ty.ty(), expected_elem)
                .map_err(|reason| format!("list element: {reason}"))
        }
        (Type::Option(opt_ty), ExpectedType::Option(expected_inner)) => {
            match_wit_type(&opt_ty.ty(), expected_inner)
                .map_err(|reason| format!("option inner: {reason}"))
        }
        (Type::Result(res_ty), ExpectedType::Result { ok, err }) => {
            match (res_ty.ok(), ok) {
                (None, None) => {}
                (Some(actual_ok), Some(expected_ok)) => {
                    match_wit_type(&actual_ok, expected_ok)
                        .map_err(|reason| format!("result ok: {reason}"))?;
                }
                _ => return Err("result ok payload presence mismatch".into()),
            }
            match (res_ty.err(), err) {
                (None, None) => {}
                (Some(actual_err), Some(expected_err)) => {
                    match_wit_type(&actual_err, expected_err)
                        .map_err(|reason| format!("result err: {reason}"))?;
                }
                _ => return Err("result err payload presence mismatch".into()),
            }
            Ok(())
        }
        (Type::Enum(enum_ty), ExpectedType::Enum(expected_names)) => {
            let actual_names: Vec<&str> = enum_ty.names().collect();
            if actual_names.as_slice() != *expected_names {
                return Err(format!(
                    "enum cases mismatch: expected {:?}, got {:?}",
                    expected_names, actual_names
                ));
            }
            Ok(())
        }
        (Type::Record(rec_ty), ExpectedType::Record(expected_fields)) => {
            let actual_fields: Vec<_> = rec_ty.fields().collect();
            if actual_fields.len() != expected_fields.len() {
                return Err(format!(
                    "record field count mismatch: expected {}, got {}",
                    expected_fields.len(),
                    actual_fields.len()
                ));
            }
            for (actual_field, (expected_name, expected_ty)) in
                actual_fields.iter().zip(expected_fields.iter())
            {
                if actual_field.name != *expected_name {
                    return Err(format!(
                        "record field name mismatch: expected '{expected_name}', got '{}'",
                        actual_field.name
                    ));
                }
                match_wit_type(&actual_field.ty, expected_ty)
                    .map_err(|reason| format!("record field '{expected_name}': {reason}"))?;
            }
            Ok(())
        }
        _ => Err(format!("unexpected WIT type {actual:?}")),
    }
}

/// Isolated per-call or per-stream WebAssembly component instance with bounded fuel,
/// bounded host lifting (`hostcall_fuel`), zero component handles, and bounded linear memory.
pub(crate) struct SandboxInstance {
    store: Store<SandboxState>,
    instance: Instance,
    _compiled: Arc<CompiledComponent>,
    metrics: Arc<HostMetrics>,
}

impl SandboxInstance {
    pub(crate) fn instantiate(
        compiled: Arc<CompiledComponent>,
        budget: ResourceBudget,
    ) -> Result<Self> {
        Self::instantiate_with_fuel(compiled, budget, budget.max_fuel_per_call)
            .map(|(instance, _)| instance)
    }

    pub(crate) fn instantiate_and_call(
        compiled: Arc<CompiledComponent>,
        budget: ResourceBudget,
        remaining_fuel: u64,
        interface: &str,
        function: &str,
        params: &[Val],
        lift_limit: usize,
    ) -> Result<(Self, u64, CallOutcome<Val>)> {
        let (mut instance, startup_fuel) =
            Self::instantiate_with_fuel(compiled, budget, remaining_fuel)?;
        let (value, fuel_consumed) = instance.call_interface_func_with_limits(
            interface,
            function,
            params,
            lift_limit,
            remaining_fuel - startup_fuel,
        )?;
        Ok((
            instance,
            startup_fuel,
            CallOutcome {
                value,
                fuel_consumed,
            },
        ))
    }

    fn instantiate_with_fuel(
        compiled: Arc<CompiledComponent>,
        budget: ResourceBudget,
        fuel_limit: u64,
    ) -> Result<(Self, u64)> {
        budget.validate()?;
        let effective_fuel = fuel_limit.min(budget.max_fuel_per_call);
        if effective_fuel == 0 {
            return Err(Error::FuelExhausted { limit: 0 });
        }
        let metrics = compiled.engine().metrics_handle();
        let state = SandboxState::new(budget, Arc::clone(&metrics));
        let mut store = Store::new(compiled.engine().engine(), state);
        store.limiter(|s| s);
        store.set_max_component_handles(0);
        store.set_hostcall_fuel(SMALL_CALL_LIFT_BYTES.min(budget.max_host_lift_bytes));
        store
            .set_fuel(effective_fuel + FUEL_METER_RESERVE)
            .map_err(|err| Error::HostInitialization(err.to_string()))?;

        // Empty linker: zero WASI, zero host ambient capabilities.
        let linker: Linker<SandboxState> = Linker::new(compiled.engine().engine());
        let result = linker.instantiate(&mut store, compiled.component());
        let (instance, consumed) = finish_metered_execution(
            result,
            &store,
            &metrics,
            effective_fuel,
            SMALL_CALL_LIFT_BYTES.min(budget.max_host_lift_bytes),
        )?;

        Ok((
            Self {
                store,
                instance,
                _compiled: compiled,
                metrics,
            },
            consumed,
        ))
    }

    pub(crate) fn consumed_call_fuel(&self, limit: u64) -> u64 {
        metered_fuel_used(
            limit.min(self.budget().max_fuel_per_call),
            self.store.get_fuel().unwrap_or(0),
        )
    }

    pub(crate) fn live_memory_bytes(&self) -> usize {
        self.store.data().tracked_memory_bytes()
    }

    pub(crate) fn budget(&self) -> ResourceBudget {
        self.store.data().budget()
    }

    pub(crate) fn call_interface_func(
        &mut self,
        interface_name: &str,
        func_name: &str,
        params: &[Val],
        max_lift_bytes: usize,
    ) -> Result<(Val, u64)> {
        let fuel_limit = self.store.data().budget().max_fuel_per_call;
        self.call_interface_func_with_limits(
            interface_name,
            func_name,
            params,
            max_lift_bytes,
            fuel_limit,
        )
    }

    pub(crate) fn call_interface_func_with_limits(
        &mut self,
        interface_name: &str,
        func_name: &str,
        params: &[Val],
        max_lift_bytes: usize,
        fuel_limit: u64,
    ) -> Result<(Val, u64)> {
        let budget = self.store.data().budget();
        let effective_fuel = fuel_limit.min(budget.max_fuel_per_call);
        if effective_fuel == 0 {
            return Err(Error::FuelExhausted { limit: 0 });
        }
        let effective_lift_limit = max_lift_bytes.max(1024).min(budget.max_host_lift_bytes);

        self.store.data_mut().reset_call_flags();
        self.store.set_hostcall_fuel(effective_lift_limit);
        self.store
            .set_fuel(effective_fuel + FUEL_METER_RESERVE)
            .map_err(|err| Error::HostInitialization(err.to_string()))?;

        let Some(iface_idx) = self
            .instance
            .get_export_index(&mut self.store, None, interface_name)
        else {
            return Err(Error::ContractExportMismatch {
                expected: interface_name.to_owned(),
                detail: "interface export missing at runtime".into(),
            });
        };
        let Some(func_idx) =
            self.instance
                .get_export_index(&mut self.store, Some(&iface_idx), func_name)
        else {
            return Err(Error::ContractExportMismatch {
                expected: format!("{interface_name}#{func_name}"),
                detail: "function export missing at runtime".into(),
            });
        };
        let Some(func) = self.instance.get_func(&mut self.store, func_idx) else {
            return Err(Error::ContractExportMismatch {
                expected: format!("{interface_name}#{func_name}"),
                detail: "export is not a callable component function".into(),
            });
        };

        let mut results = vec![Val::Bool(false)];
        let result = func.call(&mut self.store, params, &mut results);
        let ((), consumed) = finish_metered_execution(
            result,
            &self.store,
            &self.metrics,
            effective_fuel,
            effective_lift_limit,
        )?;

        let value = results
            .into_iter()
            .next()
            .ok_or_else(|| Error::InvalidGuestOutput("missing return value".into()))?;
        Ok((value, consumed))
    }
}

fn metered_fuel_used(limit: u64, remaining: u64) -> u64 {
    limit - remaining.saturating_sub(FUEL_METER_RESERVE)
}

fn finish_metered_execution<T>(
    result: wasmtime::Result<T>,
    store: &Store<SandboxState>,
    metrics: &HostMetrics,
    fuel_limit: u64,
    lift_limit: usize,
) -> Result<(T, u64)> {
    let remaining = store
        .get_fuel()
        .map_err(|err| Error::HostInitialization(err.to_string()))?;
    let consumed = metered_fuel_used(fuel_limit, remaining);
    metrics.record_fuel(consumed);
    let value = result.map_err(|err| {
        classify_execution_error(
            store,
            metrics,
            store.data().budget(),
            fuel_limit,
            lift_limit,
            err,
        )
    })?;
    if remaining < FUEL_METER_RESERVE {
        metrics.record_trap_isolated();
        return Err(Error::FuelExhausted { limit: fuel_limit });
    }
    Ok((value, consumed))
}

fn classify_execution_error(
    store: &Store<SandboxState>,
    metrics: &HostMetrics,
    budget: ResourceBudget,
    effective_fuel: u64,
    effective_lift_limit: usize,
    err: wasmtime::Error,
) -> Error {
    metrics.record_trap_isolated();
    if store.data().memory_limit_exceeded() {
        return Error::MemoryLimitExceeded {
            limit_bytes: budget.max_memory_bytes,
        };
    }
    if let Some(trap) = err.downcast_ref::<Trap>() {
        if *trap == Trap::OutOfFuel {
            return Error::FuelExhausted {
                limit: effective_fuel,
            };
        }
        if *trap == Trap::HostcallFuelExhausted {
            return Error::HostLiftLimitExceeded {
                limit_bytes: effective_lift_limit,
            };
        }
        return Error::GuestTrap(trap.to_string());
    }
    if store.get_fuel().ok() == Some(0) {
        return Error::FuelExhausted {
            limit: effective_fuel,
        };
    }
    Error::GuestTrap(err.to_string())
}

// --- Canonical Val encoding/decoding helpers ---

pub(crate) fn encode_params(params: &BTreeMap<String, String>) -> Val {
    Val::List(
        params
            .iter()
            .map(|(key, value)| {
                Val::Record(vec![
                    ("key".into(), Val::String(key.clone())),
                    ("value".into(), Val::String(value.clone())),
                ])
            })
            .collect(),
    )
}

pub(crate) fn expect_record<'a>(val: &'a Val, context: &str) -> Result<BTreeMap<&'a str, &'a Val>> {
    match val {
        Val::Record(fields) => Ok(fields.iter().map(|(k, v)| (k.as_str(), v)).collect()),
        _ => Err(Error::InvalidGuestOutput(format!(
            "{context}: expected WIT record"
        ))),
    }
}

pub(crate) fn record_field<'a>(
    fields: &BTreeMap<&'a str, &'a Val>,
    name: &str,
    context: &str,
) -> Result<&'a Val> {
    fields.get(name).copied().ok_or_else(|| {
        Error::InvalidGuestOutput(format!("{context}: missing record field '{name}'"))
    })
}

pub(crate) fn expect_string<'a>(val: &'a Val, context: &str) -> Result<&'a str> {
    match val {
        Val::String(s) => Ok(s.as_str()),
        _ => Err(Error::InvalidGuestOutput(format!(
            "{context}: expected WIT string"
        ))),
    }
}

pub(crate) fn expect_u32(val: &Val, context: &str) -> Result<u32> {
    match val {
        Val::U32(n) => Ok(*n),
        _ => Err(Error::InvalidGuestOutput(format!(
            "{context}: expected WIT u32"
        ))),
    }
}

pub(crate) fn expect_bool(val: &Val, context: &str) -> Result<bool> {
    match val {
        Val::Bool(b) => Ok(*b),
        _ => Err(Error::InvalidGuestOutput(format!(
            "{context}: expected WIT bool"
        ))),
    }
}

pub(crate) fn expect_enum<'a>(val: &'a Val, context: &str) -> Result<&'a str> {
    match val {
        Val::Enum(name) => Ok(name.as_str()),
        _ => Err(Error::InvalidGuestOutput(format!(
            "{context}: expected WIT enum"
        ))),
    }
}

pub(crate) fn expect_list<'a>(val: &'a Val, context: &str) -> Result<&'a [Val]> {
    match val {
        Val::List(items) => Ok(items.as_slice()),
        _ => Err(Error::InvalidGuestOutput(format!(
            "{context}: expected WIT list"
        ))),
    }
}

pub(crate) fn expect_option<'a>(val: &'a Val, context: &str) -> Result<Option<&'a Val>> {
    match val {
        Val::Option(inner) => Ok(inner.as_deref()),
        _ => Err(Error::InvalidGuestOutput(format!(
            "{context}: expected WIT option"
        ))),
    }
}

pub(crate) fn expect_bytes(val: &Val, max_len: usize, context: &str) -> Result<Vec<u8>> {
    let items = expect_list(val, context)?;
    if items.len() > max_len {
        return Err(Error::InvalidGuestOutput(format!(
            "{context}: byte list length {} exceeds limit {max_len}",
            items.len()
        )));
    }
    let mut out = Vec::with_capacity(items.len());
    for item in items {
        match item {
            Val::U8(b) => out.push(*b),
            _ => {
                return Err(Error::InvalidGuestOutput(format!(
                    "{context}: expected list<u8>"
                )));
            }
        }
    }
    Ok(out)
}

pub(crate) fn unwrap_plugin_result(val: Val, context: &str) -> Result<Option<Val>> {
    match val {
        Val::Result(Ok(inner)) => Ok(inner.map(|b| *b)),
        Val::Result(Err(Some(err_val))) => {
            let fields = expect_record(&err_val, context)?;
            let code = expect_string(record_field(&fields, "code", context)?, context)?;
            let message = expect_string(record_field(&fields, "message", context)?, context)?;
            if code.trim().is_empty() || code.len() > MAX_GUEST_ERROR_CODE_BYTES {
                return Err(Error::InvalidGuestOutput(format!(
                    "{context}: guest error code must be non-empty and <= {MAX_GUEST_ERROR_CODE_BYTES} bytes"
                )));
            }
            if message.len() > MAX_GUEST_ERROR_MESSAGE_BYTES {
                return Err(Error::InvalidGuestOutput(format!(
                    "{context}: guest error message length {} exceeds {MAX_GUEST_ERROR_MESSAGE_BYTES} bytes",
                    message.len()
                )));
            }
            Err(Error::GuestError {
                code: code.to_owned(),
                message: message.to_owned(),
            })
        }
        Val::Result(Err(None)) => Err(Error::GuestError {
            code: "WASM_GUEST_UNSPECIFIED_ERROR".into(),
            message: format!("{context}: guest returned empty error"),
        }),
        _ => Err(Error::InvalidGuestOutput(format!(
            "{context}: expected WIT result"
        ))),
    }
}
