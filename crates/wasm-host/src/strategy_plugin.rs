//! Sandboxed L3 WASM programmable strategy plugin host adapter.

use crate::config::ResourceBudget;
use crate::contract::{
    ArtifactBinding, CallOutcome, Error, Result, STRATEGY_INTERFACE, StrategyMetadata,
    format_domain_decimal, order_side_from_wit_name, order_type_from_wit_name,
    parse_guest_domain_decimal, time_in_force_from_wit_name,
};
use crate::sandbox::{
    CompiledComponent, METADATA_CALL_LIFT_BYTES, SandboxInstance, encode_params, expect_enum,
    expect_list, expect_option, expect_record, expect_string, record_field, unwrap_plugin_result,
};
use onlyalpha_domain::strategy::{NamedFactor, OrderIntent, ReadonlyAccountState};
use std::collections::BTreeSet;
use std::sync::Arc;
use wasmtime::component::Val;

/// Loaded and verified L3 WASM strategy plugin (`on_event(factors, readonly_state) -> list<order_intent>`).
#[derive(Clone)]
pub struct WasmStrategyPlugin {
    compiled: Arc<CompiledComponent>,
    metadata: StrategyMetadata,
    binding: ArtifactBinding,
    budget: ResourceBudget,
}

impl WasmStrategyPlugin {
    pub(crate) fn load(
        compiled: Arc<CompiledComponent>,
        binding: ArtifactBinding,
        budget: ResourceBudget,
    ) -> Result<Self> {
        let mut instance = SandboxInstance::instantiate(Arc::clone(&compiled), budget)?;
        let (val, _) = instance.call_interface_func(
            STRATEGY_INTERFACE,
            "metadata",
            &[],
            METADATA_CALL_LIFT_BYTES,
        )?;
        let metadata = decode_strategy_metadata(&val)?;
        Ok(Self {
            compiled,
            metadata,
            binding,
            budget,
        })
    }

    pub fn metadata(&self) -> &StrategyMetadata {
        &self.metadata
    }

    pub fn artifact_sha256(&self) -> &str {
        self.compiled.artifact_sha256()
    }

    pub fn binding(&self) -> &ArtifactBinding {
        &self.binding
    }

    /// Evaluates one market event in a fresh isolated store and returns validated order intents.
    ///
    /// - Enforces that every factor declared in `metadata.required_factors` is provided.
    /// - Passes only bound causal factors and read-only account/position views.
    /// - Any trap, fuel exhaustion, memory violation, or malformed intent fails closed with zero
    ///   partial intents emitted.
    pub fn on_event(
        &self,
        factors: &[NamedFactor],
        readonly_state: &ReadonlyAccountState,
    ) -> Result<CallOutcome<Vec<OrderIntent>>> {
        validate_strategy_inputs(&self.metadata, factors)?;

        let encoded_factors = encode_factors(factors)?;
        let encoded_state = encode_readonly_state(readonly_state)?;
        let encoded_params = encode_params(&self.binding.canonical_parameters);

        let lift_limit = self
            .budget
            .max_output_items
            .saturating_mul(1024)
            .saturating_add(8 * 1024)
            .min(self.budget.max_host_lift_bytes);

        let mut instance = SandboxInstance::instantiate(Arc::clone(&self.compiled), self.budget)?;
        let (val, fuel_consumed) = instance.call_interface_func(
            STRATEGY_INTERFACE,
            "on-event",
            &[encoded_factors, encoded_state, encoded_params],
            lift_limit,
        )?;
        let ok_val = unwrap_plugin_result(val, "strategy#on-event")?.ok_or_else(|| {
            Error::InvalidGuestOutput("strategy#on-event returned empty ok payload".into())
        })?;
        let intents = decode_order_intents(&ok_val, self.budget.max_output_items)?;
        Ok(CallOutcome {
            value: intents,
            fuel_consumed,
        })
    }

    pub(crate) fn strong_ref_count(&self) -> usize {
        Arc::strong_count(&self.compiled)
    }
}

fn validate_strategy_inputs(metadata: &StrategyMetadata, factors: &[NamedFactor]) -> Result<()> {
    let mut seen = BTreeSet::new();
    for factor in factors {
        if !seen.insert(factor.name()) {
            return Err(Error::InvalidHostInput(format!(
                "duplicate factor name '{}'",
                factor.name()
            )));
        }
    }
    for required in &metadata.required_factors {
        if !seen.remove(required.as_str()) {
            return Err(Error::InvalidHostInput(format!(
                "missing required bound factor '{required}' for strategy '{}'",
                metadata.strategy_id
            )));
        }
    }
    if let Some(name) = seen.first() {
        return Err(Error::InvalidHostInput(format!(
            "undeclared factor '{name}' for strategy '{}'",
            metadata.strategy_id
        )));
    }
    Ok(())
}

fn encode_factors(factors: &[NamedFactor]) -> Result<Val> {
    let mut items = Vec::with_capacity(factors.len());
    for factor in factors {
        let value = match factor.value() {
            Some(value) => Some(Box::new(Val::String(format_domain_decimal(
                value,
                "strategy.factor.value",
            )?))),
            None => None,
        };
        items.push(Val::Record(vec![
            ("name".into(), Val::String(factor.name().to_owned())),
            ("value".into(), Val::Option(value)),
        ]));
    }
    Ok(Val::List(items))
}

fn encode_readonly_state(state: &ReadonlyAccountState) -> Result<Val> {
    let timestamp_ns = i64::try_from(state.timestamp().unix_nanos()).map_err(|_| {
        Error::InvalidHostInput("strategy.timestamp exceeds the WIT timestamp-ns range".into())
    })?;
    let cash_available = format_domain_decimal(state.cash_available(), "strategy.cash_available")?;
    let total_equity = format_domain_decimal(state.total_equity(), "strategy.total_equity")?;
    let mut positions = Vec::with_capacity(state.positions().len());
    for position in state.positions() {
        let quantity = format_domain_decimal(position.quantity(), "strategy.position.quantity")?;
        let average_cost = match position.average_cost() {
            Some(cost) => Some(Box::new(Val::String(format_domain_decimal(
                cost,
                "strategy.position.average_cost",
            )?))),
            None => None,
        };
        positions.push(Val::Record(vec![
            (
                "instrument-id".into(),
                Val::String(position.instrument().to_string()),
            ),
            ("quantity".into(), Val::String(quantity)),
            ("average-cost".into(), Val::Option(average_cost)),
        ]));
    }
    Ok(Val::Record(vec![
        ("timestamp-ns".into(), Val::S64(timestamp_ns)),
        ("cash-available".into(), Val::String(cash_available)),
        ("total-equity".into(), Val::String(total_equity)),
        ("positions".into(), Val::List(positions)),
    ]))
}

fn decode_strategy_metadata(val: &Val) -> Result<StrategyMetadata> {
    let ctx = "strategy#metadata";
    let fields = expect_record(val, ctx)?;
    let strategy_id = expect_string(record_field(&fields, "strategy-id", ctx)?, ctx)?.to_owned();
    let version = expect_string(record_field(&fields, "version", ctx)?, ctx)?.to_owned();
    let raw_factors = expect_list(
        record_field(&fields, "required-factors", ctx)?,
        "strategy#metadata.required-factors",
    )?;

    if strategy_id.trim().is_empty() || strategy_id.len() > 256 {
        return Err(Error::InvalidGuestOutput(
            "strategy-id must be non-empty and <= 256 bytes".into(),
        ));
    }
    if version.trim().is_empty() || version.len() > 64 {
        return Err(Error::InvalidGuestOutput(
            "strategy version must be non-empty and <= 64 bytes".into(),
        ));
    }
    if raw_factors.len() > 256 {
        return Err(Error::InvalidGuestOutput(
            "strategy required-factors exceeds 256 limit".into(),
        ));
    }

    let mut required_factors = Vec::with_capacity(raw_factors.len());
    let mut seen = BTreeSet::new();
    for item in raw_factors {
        let name = expect_string(item, "strategy#metadata.required-factors[]")?;
        if name.trim().is_empty() || name.len() > 256 {
            return Err(Error::InvalidGuestOutput(
                "required factor name must be non-empty and <= 256 bytes".into(),
            ));
        }
        if !seen.insert(name.to_owned()) {
            return Err(Error::InvalidGuestOutput(format!(
                "duplicate required factor '{name}' in strategy metadata"
            )));
        }
        required_factors.push(name.to_owned());
    }

    Ok(StrategyMetadata {
        strategy_id,
        version,
        required_factors,
    })
}

fn decode_order_intents(val: &Val, max_items: usize) -> Result<Vec<OrderIntent>> {
    let ctx = "strategy#on-event";
    let items = expect_list(val, ctx)?;
    if items.len() > max_items {
        return Err(Error::InvalidGuestOutput(format!(
            "order intent count {} exceeds max_output_items {max_items}",
            items.len()
        )));
    }
    let mut out = Vec::with_capacity(items.len());
    for item in items {
        let fields = expect_record(item, "strategy.order-intent")?;
        let instrument = expect_string(
            record_field(&fields, "instrument-id", "strategy.order-intent")?,
            "strategy.order-intent.instrument-id",
        )?
        .parse()
        .map_err(|_| {
            Error::InvalidGuestOutput("order-intent instrument-id must use SYMBOL.VENUE".into())
        })?;
        let side = order_side_from_wit_name(expect_enum(
            record_field(&fields, "side", "strategy.order-intent")?,
            "strategy.order-intent.side",
        )?)?;
        let order_type = order_type_from_wit_name(expect_enum(
            record_field(&fields, "order-type", "strategy.order-intent")?,
            "strategy.order-intent.order-type",
        )?)?;
        let quantity = parse_guest_domain_decimal(
            expect_string(
                record_field(&fields, "quantity", "strategy.order-intent")?,
                "strategy.order-intent.quantity",
            )?,
            "strategy.order-intent.quantity",
        )?;
        let limit_price = match expect_option(
            record_field(&fields, "limit-price", "strategy.order-intent")?,
            "strategy.order-intent.limit-price",
        )? {
            Some(value) => Some(parse_guest_domain_decimal(
                expect_string(value, "strategy.order-intent.limit-price")?,
                "strategy.order-intent.limit-price",
            )?),
            None => None,
        };
        let time_in_force = time_in_force_from_wit_name(expect_enum(
            record_field(&fields, "time-in-force", "strategy.order-intent")?,
            "strategy.order-intent.time-in-force",
        )?)?;
        let reason_code = expect_string(
            record_field(&fields, "reason-code", "strategy.order-intent")?,
            "strategy.order-intent.reason-code",
        )?;
        out.push(
            OrderIntent::new(
                instrument,
                side,
                order_type,
                quantity,
                limit_price,
                time_in_force,
                reason_code,
            )
            .map_err(|failure| Error::InvalidGuestOutput(failure.to_string()))?,
        );
    }
    Ok(out)
}
