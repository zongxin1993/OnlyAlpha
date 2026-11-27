//! Sandboxed L3 WASM market trading rule plugin host adapter.

use crate::config::ResourceBudget;
use crate::contract::{
    ArtifactBinding, CallOutcome, Error, HOST_RUNTIME_VERSION, MARKET_RULE_INTERFACE,
    MarketRuleDecision, MarketRuleInput, MarketRuleMetadata, PluginKind, Result,
    format_host_decimal, order_side_wit_name, order_type_wit_name, parse_guest_decimal,
    validate_non_empty_id,
};
use crate::sandbox::{
    CompiledComponent, MARKET_RULE_LIFT_BYTES, METADATA_CALL_LIFT_BYTES, SandboxInstance,
    expect_bool, expect_option, expect_record, expect_string, record_field, unwrap_plugin_result,
};
use onlyalpha_operators::algebra::Decimal;
use std::collections::BTreeMap;
use std::sync::Arc;
use wasmtime::component::Val;

/// Loaded and verified L3 WASM market-rule plugin.
#[derive(Clone)]
pub struct WasmMarketRulePlugin {
    compiled: Arc<CompiledComponent>,
    metadata: MarketRuleMetadata,
    budget: ResourceBudget,
}

impl WasmMarketRulePlugin {
    pub(crate) fn load(compiled: Arc<CompiledComponent>, budget: ResourceBudget) -> Result<Self> {
        let mut instance = SandboxInstance::instantiate(Arc::clone(&compiled), budget)?;
        let (val, _) = instance.call_interface_func(
            MARKET_RULE_INTERFACE,
            "metadata",
            &[],
            METADATA_CALL_LIFT_BYTES,
        )?;
        let metadata = decode_market_rule_metadata(&val)?;
        Ok(Self {
            compiled,
            metadata,
            budget,
        })
    }

    pub fn metadata(&self) -> &MarketRuleMetadata {
        &self.metadata
    }

    pub fn artifact_sha256(&self) -> &str {
        self.compiled.artifact_sha256()
    }

    pub fn binding(&self, plugin_id: impl Into<String>) -> Result<ArtifactBinding> {
        ArtifactBinding::new(
            plugin_id,
            PluginKind::MarketRule,
            self.compiled.artifact_sha256().to_owned(),
            BTreeMap::new(),
        )
    }

    /// Evaluates one order against the market-rule WASM plugin in a fresh bounded store.
    pub fn validate_order(
        &self,
        input: &MarketRuleInput,
    ) -> Result<CallOutcome<MarketRuleDecision>> {
        validate_market_rule_input(input)?;
        let encoded = encode_market_rule_input(input)?;
        let mut instance = SandboxInstance::instantiate(Arc::clone(&self.compiled), self.budget)?;
        let (val, fuel_consumed) = instance.call_interface_func(
            MARKET_RULE_INTERFACE,
            "validate-order",
            &[encoded],
            MARKET_RULE_LIFT_BYTES,
        )?;
        let ok_val = unwrap_plugin_result(val, "market-rule#validate-order")?.ok_or_else(|| {
            Error::InvalidGuestOutput("validate-order returned empty ok payload".into())
        })?;
        let decision = decode_market_rule_decision(&ok_val)?;
        Ok(CallOutcome {
            value: decision,
            fuel_consumed,
        })
    }

    pub(crate) fn strong_ref_count(&self) -> usize {
        Arc::strong_count(&self.compiled)
    }

    pub(crate) fn host_version(&self) -> &'static str {
        HOST_RUNTIME_VERSION
    }
}

fn validate_market_rule_input(input: &MarketRuleInput) -> Result<()> {
    validate_non_empty_id(&input.trading_day, "trading_day")?;
    validate_non_empty_id(&input.instrument_id, "instrument_id")?;
    validate_non_empty_id(&input.rule_version, "rule_version")?;
    let zero = Decimal::from(0);
    if input.quantity <= zero {
        return Err(Error::InvalidHostInput(
            "market rule quantity must be strictly positive".into(),
        ));
    }
    if input.settled_quantity < zero {
        return Err(Error::InvalidHostInput(
            "market rule settled_quantity must be non-negative".into(),
        ));
    }
    if let Some(price) = &input.price
        && *price <= zero
    {
        return Err(Error::InvalidHostInput(
            "market rule price must be strictly positive".into(),
        ));
    }
    if let Some(ref_price) = &input.reference_price
        && *ref_price <= zero
    {
        return Err(Error::InvalidHostInput(
            "market rule reference_price must be strictly positive".into(),
        ));
    }
    Ok(())
}

fn encode_market_rule_input(input: &MarketRuleInput) -> Result<Val> {
    let quantity = format_host_decimal(&input.quantity, "market_rule.quantity")?;
    let price = match &input.price {
        Some(p) => Some(Box::new(Val::String(format_host_decimal(
            p,
            "market_rule.price",
        )?))),
        None => None,
    };
    let reference_price = match &input.reference_price {
        Some(p) => Some(Box::new(Val::String(format_host_decimal(
            p,
            "market_rule.reference_price",
        )?))),
        None => None,
    };
    let settled_quantity =
        format_host_decimal(&input.settled_quantity, "market_rule.settled_quantity")?;
    Ok(Val::Record(vec![
        ("trading-day".into(), Val::String(input.trading_day.clone())),
        (
            "instrument-id".into(),
            Val::String(input.instrument_id.clone()),
        ),
        (
            "side".into(),
            Val::Enum(order_side_wit_name(input.side).into()),
        ),
        (
            "order-type".into(),
            Val::Enum(order_type_wit_name(input.order_type)?.into()),
        ),
        ("quantity".into(), Val::String(quantity)),
        ("price".into(), Val::Option(price)),
        ("reference-price".into(), Val::Option(reference_price)),
        ("settled-quantity".into(), Val::String(settled_quantity)),
        (
            "rule-version".into(),
            Val::String(input.rule_version.clone()),
        ),
    ]))
}

fn decode_market_rule_metadata(val: &Val) -> Result<MarketRuleMetadata> {
    let ctx = "market-rule#metadata";
    let fields = expect_record(val, ctx)?;
    let plugin_id = expect_string(record_field(&fields, "plugin-id", ctx)?, ctx)?.to_owned();
    let market_id = expect_string(record_field(&fields, "market-id", ctx)?, ctx)?.to_owned();
    let version = expect_string(record_field(&fields, "version", ctx)?, ctx)?.to_owned();

    if plugin_id.trim().is_empty() || plugin_id.len() > 256 {
        return Err(Error::InvalidGuestOutput(
            "market-rule plugin-id must be non-empty and <= 256 bytes".into(),
        ));
    }
    if market_id.trim().is_empty() || market_id.len() > 128 {
        return Err(Error::InvalidGuestOutput(
            "market-rule market-id must be non-empty and <= 128 bytes".into(),
        ));
    }
    if version.trim().is_empty() || version.len() > 64 {
        return Err(Error::InvalidGuestOutput(
            "market-rule version must be non-empty and <= 64 bytes".into(),
        ));
    }

    Ok(MarketRuleMetadata {
        plugin_id,
        market_id,
        version,
    })
}

fn decode_market_rule_decision(val: &Val) -> Result<MarketRuleDecision> {
    let ctx = "market-rule#validate-order";
    let fields = expect_record(val, ctx)?;
    let allowed = expect_bool(record_field(&fields, "allowed", ctx)?, ctx)?;
    let reject_code = match expect_option(record_field(&fields, "reject-code", ctx)?, ctx)? {
        Some(v) => Some(expect_string(v, "market-rule.reject-code")?.to_owned()),
        None => None,
    };
    let normalized_quantity =
        match expect_option(record_field(&fields, "normalized-quantity", ctx)?, ctx)? {
            Some(v) => Some(parse_guest_decimal(
                expect_string(v, "market-rule.normalized-quantity")?,
                "market-rule.normalized-quantity",
            )?),
            None => None,
        };
    let normalized_price =
        match expect_option(record_field(&fields, "normalized-price", ctx)?, ctx)? {
            Some(v) => Some(parse_guest_decimal(
                expect_string(v, "market-rule.normalized-price")?,
                "market-rule.normalized-price",
            )?),
            None => None,
        };
    let fee_estimate = match expect_option(record_field(&fields, "fee-estimate", ctx)?, ctx)? {
        Some(v) => Some(parse_guest_decimal(
            expect_string(v, "market-rule.fee-estimate")?,
            "market-rule.fee-estimate",
        )?),
        None => None,
    };

    // Fail-Closed invariant: every rejection must state an explicit non-empty reject code,
    // and allowed decisions must not carry a conflicting reject code.
    if !allowed {
        match &reject_code {
            Some(code) if !code.trim().is_empty() && code.len() <= 128 => {}
            _ => {
                return Err(Error::InvalidGuestOutput(
                    "rejected market-rule decision must include non-empty reject-code".into(),
                ));
            }
        }
    } else if reject_code.is_some() {
        return Err(Error::InvalidGuestOutput(
            "allowed market-rule decision must not include reject-code".into(),
        ));
    }

    let zero = Decimal::from(0);
    if let Some(qty) = &normalized_quantity
        && *qty <= zero
    {
        return Err(Error::InvalidGuestOutput(
            "normalized-quantity must be strictly positive".into(),
        ));
    }
    if let Some(price) = &normalized_price
        && *price <= zero
    {
        return Err(Error::InvalidGuestOutput(
            "normalized-price must be strictly positive".into(),
        ));
    }
    if let Some(fee) = &fee_estimate
        && *fee < zero
    {
        return Err(Error::InvalidGuestOutput(
            "fee-estimate must be non-negative".into(),
        ));
    }

    Ok(MarketRuleDecision {
        allowed,
        reject_code,
        normalized_quantity,
        normalized_price,
        fee_estimate,
    })
}
