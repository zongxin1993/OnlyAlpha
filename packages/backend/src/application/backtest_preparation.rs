//! Fixed next-open Product input choices; no parsed value grants execution.
use crate::application::{command::CommandId, factor_studies::Source};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use utoipa::ToSchema;
/// Explicit authoring or already-qualified origin. Neither portable branch grants a Run.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize, ToSchema)]
#[serde(tag = "kind", rename_all = "SCREAMING_SNAKE_CASE", deny_unknown_fields)]
pub enum BacktestOrigin {
    ManualStrategy {
        strategy_id: String,
        strategy_revision_fingerprint: String,
    },
    FrozenStrategy {
        strategy_fingerprint: String,
        freeze_relation_fingerprint: String,
        qualification_decision_fingerprint: String,
        promotion_fingerprint: String,
    },
}
impl BacktestOrigin {
    pub(crate) fn validate(&self) -> Result<(), &'static str> {
        const INVALID: &str = "BACKTEST_PREPARATION_INVALID";
        match self {
            Self::ManualStrategy {
                strategy_id,
                strategy_revision_fingerprint,
            } => {
                crate::application::private_assets::id(strategy_id, "STRATEGY")
                    .map_err(|_| INVALID)?;
                if !crate::is_sha256_hex(strategy_revision_fingerprint) {
                    return Err(INVALID);
                }
            }
            Self::FrozenStrategy {
                strategy_fingerprint,
                freeze_relation_fingerprint,
                qualification_decision_fingerprint,
                promotion_fingerprint,
            } => {
                if [
                    strategy_fingerprint,
                    freeze_relation_fingerprint,
                    qualification_decision_fingerprint,
                    promotion_fingerprint,
                ]
                .iter()
                .any(|p| !crate::is_sha256_hex(p))
                {
                    return Err(INVALID);
                }
            }
        }
        Ok(())
    }
}
#[derive(Clone, Serialize, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct BacktestPrepareInput {
    pub schema_version: u8,
    pub profile: String,
    pub origin: BacktestOrigin,
    pub source: Source,
    pub release_manifest_fingerprint: String,
    pub expected_active_generation: Option<String>,
    pub initialize_fresh_runtime: bool,
    pub backtest_command_id: String,
}
impl BacktestPrepareInput {
    pub fn validate(&self, command: &CommandId) -> Result<(), &'static str> {
        const INVALID: &str = "BACKTEST_PREPARATION_INVALID";
        if self.schema_version != 2
            || self.profile != "BTC_SPOT_NEXT_OPEN_BACKTEST_V1"
            || self.initialize_fresh_runtime
            || self.backtest_command_id == command.value()
            || self.source.instrument_id != "BTCUSDT.BINANCE"
            || self.source.expected_type_id != "binance.spot.market_data"
            || !crate::is_sha256_hex(&self.release_manifest_fingerprint)
            || self
                .expected_active_generation
                .as_deref()
                .is_some_and(|s| !crate::is_sha256_hex(s))
            || (matches!(self.origin, BacktestOrigin::FrozenStrategy { .. })
                && self.expected_active_generation.is_none())
            || serde_json::to_string(self).map_err(|_| INVALID)?.len() > 65536
        {
            return Err(INVALID);
        }
        self.origin.validate()?;
        CommandId::new(&self.backtest_command_id).map_err(|_| INVALID)?;
        self.source.selection().map_err(|_| INVALID)?;
        Ok(())
    }
}
/// Reservation identity in the Backtest domain, independent of Research Run IDs.
pub fn run_id(command: &CommandId) -> String {
    let mut bytes = Sha256::digest(
        [
            b"ONLYALPHA_NEXT_OPEN_BACKTEST_RUN_ID_V1\x1f".as_slice(),
            command.value().as_bytes(),
        ]
        .concat(),
    );
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    let s = bytes[..16]
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    format!(
        "{}-{}-{}-{}-{}",
        &s[..8],
        &s[8..12],
        &s[12..16],
        &s[16..20],
        &s[20..32]
    )
}

/// Pure exact input construction; neither this value nor a SourceRevision grants execution.
pub(crate) fn build_prepared_next_open(
    source_revision: &onlyalpha_strategy::SourceRevision,
    materialized: &crate::application::research_dataset::MaterializedDataset,
    rules: onlyalpha_market_crypto::spot::SpotRuleSnapshot,
    generation: &str,
) -> std::result::Result<
    crate::workers::backtest::PreparedNextOpen,
    crate::application::research_admission::PreparationError,
> {
    use crate::{application::factor_content::hash, workers::backtest::PreparedNextOpen};
    use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
    use serde_json::json;
    const INVALID: &str = "RESEARCH_PREPARATION_INPUT_MISMATCH";
    const START: &str = "2025-01-03T00:00:00Z";
    const END: &str = "2025-01-03T12:00:00Z";
    let dataset = materialized.verified().dataset();
    let provenance = materialized.verified().manifest()["provenance"]
        .as_array()
        .filter(|r| r.len() == 1)
        .ok_or(INVALID)?
        .first()
        .ok_or(INVALID)?;
    let scope = &provenance["source_metadata"]["sealed_input"]["scope"];
    let source = source_revision.to_record();
    if dataset.definition()["instruments"] != source["universe"]["instruments"]
        || dataset.definition()["bar_semantic"] != source["market_input_contract"]["bar_semantic"]
        || provenance["source_metadata"]["construction_recipe"]
            != source["market_input_contract"]["construction_requirement"]["recipe"]
    {
        return Err(INVALID.into());
    }
    let bars = dataset.bars()?;
    if bars.len() > 8192 {
        return Err(INVALID.into());
    }
    let source_id = hash(
        &json!({"contract":"ONLYALPHA_NEXT_OPEN_DATASET_SOURCE_V1","snapshot":dataset.snapshot_fingerprint(),"request":materialized.lineage()["request_fingerprint"],"scope":scope}),
    )?;
    let version = scope["data_version"].as_str().ok_or(INVALID)?;
    let pin = onlyalpha_backtest::Source::new(
        &source_id,
        dataset.snapshot_fingerprint(),
        materialized.lineage()["request_fingerprint"]
            .as_str()
            .ok_or(INVALID)?,
        version,
        0,
        bars.len() as u64,
    )
    .map_err(|_| INVALID)?;
    let rows = bars
        .into_iter()
        .enumerate()
        .map(|(index, bar)| {
            onlyalpha_backtest::MarketInput::new(&source_id, index as u64 + 1, version, bar)
                .map_err(|_| INVALID)
        })
        .collect::<std::result::Result<Vec<_>, _>>()?;
    let inputs = onlyalpha_backtest::Inputs::new(vec![pin], rows).map_err(|_| INVALID)?;
    let instrument = rules.model_instrument().map_err(|_| INVALID)?.to_record();
    let precision = instrument["quote_currency"]["precision"]
        .as_u64()
        .filter(|p| *p <= 18)
        .ok_or(INVALID)? as usize;
    let cash = if precision == 0 {
        "10000".into()
    } else {
        format!("10000.{}", "0".repeat(precision))
    };
    let execution = json!({"schema_version":2,"account_checkpoint_version":5,"engine":"onlyalpha-backtest","runtime":"next-open-backtest","account":"experimental-account","gateway":"binance-spot-simulation","generation":generation,"runtime_kind":"BACKTEST",
        "currency":instrument["quote_currency"],"initial_cash":cash,"capitals":{"strategy":cash},
        "profiles":{"strategy":{"schema_version":1,"revision":source_revision.fingerprint(),"instruments":["BTCUSDT.BINANCE"],"rules":[]}},
        "instruments":[{"schema_version":1,"id":"BTCUSDT.BINANCE","price_precision":instrument["price_precision"],"quantity_precision":instrument["quantity_precision"],"multiplier":"1"}]});
    PreparedNextOpen::new(
        source_revision.clone(),
        inputs,
        rules,
        execution,
        OnlyTimestamp::from_datetime(START.parse().map_err(|_| INVALID)?),
        OnlyTimestamp::from_datetime(END.parse().map_err(|_| INVALID)?),
    )
    .map_err(|_| INVALID.into())
}

/// Pure retained occurrence validation shared by Product confirmation and
/// historical reads. A parsed snapshot alone grants no venue or Run authority.
pub(crate) fn retained_backtest_rules(
    value: &serde_json::Value,
    source: &Source,
    command: &CommandId,
) -> std::result::Result<onlyalpha_market_crypto::spot::SpotRuleSnapshot, &'static str> {
    const INVALID: &str = "BACKTEST_RULE_OCCURRENCE_CORRUPT";
    if value.as_object().is_none_or(|m| m.len() != 8)
        || value["request"].as_object().is_none_or(|m| m.len() != 4)
    {
        return Err(INVALID);
    }
    let body = value["body"]
        .as_str()
        .filter(|b| b.len() <= 8 * 1024 * 1024)
        .ok_or(INVALID)?;
    let digest = Sha256::digest(body.as_bytes())
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect::<String>();
    let raw: serde_json::Value = serde_json::from_str(body).map_err(|_| INVALID)?;
    let rules = onlyalpha_market_crypto::spot::SpotRuleSnapshot::from_record(&value["snapshot"])
        .map_err(|_| INVALID)?;
    if value["schema_version"] != 1
        || value["contract"] != "ONLYALPHA_BINANCE_PUBLIC_RULE_OCCURRENCE_V1"
        || value["body_sha256"] != digest
        || value["source"] != serde_json::to_value(source).map_err(|_| INVALID)?
        || value["request"]["source_id"] != source.source_id
        || value["request"]["path"] != "/api/v3/exchangeInfo"
        || value["request"]["symbols"] != "[\"BTCUSDT\"]"
        || raw["symbols"].as_array().is_none_or(|r| r.len() != 1)
        || raw["symbols"][0] != rules.record()["raw_symbol"]
        || value["captured_at"] != rules.record()["captured_at"]
        || rules.record()["source_ref"] != format!("backtest-rules:{}", command.value())
    {
        return Err(INVALID);
    }
    Ok(rules)
}
