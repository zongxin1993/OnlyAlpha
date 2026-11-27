//! Runtime hot-load / hot-unload manager for L3 WASM plugins with exact binding enforcement
//! and deterministic linear-memory reclamation accounting.

use crate::certification::{CertificationRequest, certify_extended_operator};
use crate::config::{HostMetricsSnapshot, ResourceBudget, WasmHostEngine};
use crate::contract::{
    ArtifactBinding, Error, HOST_RUNTIME_VERSION, PluginKind, Result, WIT_CONTRACT_VERSION,
    validate_non_empty_id,
};
use crate::market_rule_plugin::WasmMarketRulePlugin;
use crate::operator_plugin::{UnverifiedExtendedOperator, WasmExtendedOperator};
use crate::sandbox::CompiledComponent;
use crate::strategy_plugin::WasmStrategyPlugin;
use std::collections::BTreeMap;
use std::sync::{Arc, RwLock};

/// Summary of one currently loaded L3 WASM plugin slot.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct LoadedPluginSummary {
    pub plugin_id: String,
    pub kind: PluginKind,
    pub artifact_sha256: String,
    pub wit_contract_version: String,
    pub host_version: String,
    pub ready: bool,
}

/// Receipt emitted on runtime hot-unload proving removal from the active registry and
/// reporting whether all compiled component references were reclaimed immediately.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UnloadReceipt {
    pub plugin_id: String,
    pub kind: PluginKind,
    pub artifact_sha256: String,
    pub remaining_external_refs: usize,
    pub reclaimed_immediately: bool,
}

enum LoadedEntry {
    ExtendedOperator(Box<WasmExtendedOperator>),
    MarketRule(WasmMarketRulePlugin),
    Strategy(WasmStrategyPlugin),
}

impl LoadedEntry {
    fn kind(&self) -> PluginKind {
        match self {
            Self::ExtendedOperator(_) => PluginKind::ExtendedOperator,
            Self::MarketRule(_) => PluginKind::MarketRule,
            Self::Strategy(_) => PluginKind::Strategy,
        }
    }

    fn artifact_sha256(&self) -> &str {
        match self {
            Self::ExtendedOperator(p) => p.artifact_sha256(),
            Self::MarketRule(p) => p.artifact_sha256(),
            Self::Strategy(p) => p.artifact_sha256(),
        }
    }

    fn host_version(&self) -> &str {
        match self {
            Self::ExtendedOperator(p) => &p.certificate().host_version,
            Self::MarketRule(p) => p.host_version(),
            Self::Strategy(p) => &p.binding().host_version,
        }
    }

    fn strong_ref_count(&self) -> usize {
        match self {
            Self::ExtendedOperator(p) => p.strong_ref_count(),
            Self::MarketRule(p) => p.strong_ref_count(),
            Self::Strategy(p) => p.strong_ref_count(),
        }
    }
}

/// Runtime manager owning hot-load, automatic admission certification, exact SHA-256 replay
/// verification, and hot-unload for all L3 WASM plugins.
pub struct WasmPluginManager {
    engine: Arc<WasmHostEngine>,
    default_budget: ResourceBudget,
    plugins: RwLock<BTreeMap<String, LoadedEntry>>,
}

impl WasmPluginManager {
    pub fn new(default_budget: ResourceBudget) -> Result<Self> {
        default_budget.validate()?;
        let engine = Arc::new(WasmHostEngine::new()?);
        Ok(Self {
            engine,
            default_budget,
            plugins: RwLock::new(BTreeMap::new()),
        })
    }

    pub fn default_budget(&self) -> ResourceBudget {
        self.default_budget
    }

    pub fn metrics(&self) -> HostMetricsSnapshot {
        self.engine.metrics()
    }

    /// Loads, verifies (SHA-256 + zero-WASI + WIT interface), automatically certifies
    /// (`Vector == Event`, causality, warmup/null, snapshot restore, determinism, goldens),
    /// and registers a READY L3 WASM extended operator plugin.
    pub fn load_extended_operator(
        &self,
        wasm_bytes: &[u8],
        expected_sha256: &str,
        request: CertificationRequest,
        budget: Option<ResourceBudget>,
    ) -> Result<WasmExtendedOperator> {
        validate_non_empty_id(&request.plugin_id, "plugin_id")?;
        let budget = budget.unwrap_or(self.default_budget);
        self.ensure_slot_free(&request.plugin_id)?;

        let compiled = Arc::new(CompiledComponent::compile(
            Arc::clone(&self.engine),
            PluginKind::ExtendedOperator,
            wasm_bytes,
            expected_sha256,
            budget,
        )?);
        let (unverified, metadata_fuel) = UnverifiedExtendedOperator::load(compiled, budget)?;
        let plugin_id = request.plugin_id.clone();
        let certified = certify_extended_operator(unverified, request, metadata_fuel)?;

        let mut guard = self.plugins.write().map_err(|_| Error::LockPoisoned)?;
        if guard.contains_key(&plugin_id) {
            return Err(Error::PluginAlreadyLoaded { plugin_id });
        }
        guard.insert(
            plugin_id,
            LoadedEntry::ExtendedOperator(Box::new(certified.clone())),
        );
        self.engine.metrics_handle().record_plugin_loaded();
        Ok(certified)
    }

    /// Loads, verifies (SHA-256 + zero-WASI + WIT interface), and registers a market-rule plugin.
    pub fn load_market_rule(
        &self,
        plugin_id: impl Into<String>,
        wasm_bytes: &[u8],
        expected_sha256: &str,
        budget: Option<ResourceBudget>,
    ) -> Result<WasmMarketRulePlugin> {
        let plugin_id = plugin_id.into();
        validate_non_empty_id(&plugin_id, "plugin_id")?;
        let budget = budget.unwrap_or(self.default_budget);
        self.ensure_slot_free(&plugin_id)?;

        let compiled = Arc::new(CompiledComponent::compile(
            Arc::clone(&self.engine),
            PluginKind::MarketRule,
            wasm_bytes,
            expected_sha256,
            budget,
        )?);
        let loaded = WasmMarketRulePlugin::load(compiled, budget)?;

        let mut guard = self.plugins.write().map_err(|_| Error::LockPoisoned)?;
        if guard.contains_key(&plugin_id) {
            return Err(Error::PluginAlreadyLoaded { plugin_id });
        }
        guard.insert(plugin_id, LoadedEntry::MarketRule(loaded.clone()));
        self.engine.metrics_handle().record_plugin_loaded();
        Ok(loaded)
    }

    /// Loads, verifies (SHA-256 + zero-WASI + WIT interface), and registers a strategy plugin.
    pub fn load_strategy(
        &self,
        plugin_id: impl Into<String>,
        wasm_bytes: &[u8],
        expected_sha256: &str,
        canonical_parameters: BTreeMap<String, String>,
        budget: Option<ResourceBudget>,
    ) -> Result<WasmStrategyPlugin> {
        let plugin_id = plugin_id.into();
        let binding = ArtifactBinding::new(
            &plugin_id,
            PluginKind::Strategy,
            expected_sha256,
            canonical_parameters,
        )?;
        let budget = budget.unwrap_or(self.default_budget);
        self.ensure_slot_free(&plugin_id)?;

        let compiled = Arc::new(CompiledComponent::compile(
            Arc::clone(&self.engine),
            PluginKind::Strategy,
            wasm_bytes,
            expected_sha256,
            budget,
        )?);
        let loaded = WasmStrategyPlugin::load(compiled, binding, budget)?;

        let mut guard = self.plugins.write().map_err(|_| Error::LockPoisoned)?;
        if guard.contains_key(&plugin_id) {
            return Err(Error::PluginAlreadyLoaded { plugin_id });
        }
        guard.insert(plugin_id, LoadedEntry::Strategy(loaded.clone()));
        self.engine.metrics_handle().record_plugin_loaded();
        Ok(loaded)
    }

    /// Hot-unloads a plugin from the active registry and drops the manager's compiled component
    /// reference so linear memory and compiled code are reclaimed cleanly.
    pub fn unload(&self, plugin_id: &str) -> Result<UnloadReceipt> {
        let mut guard = self.plugins.write().map_err(|_| Error::LockPoisoned)?;
        let Some(entry) = guard.remove(plugin_id) else {
            return Err(Error::PluginNotFound {
                plugin_id: plugin_id.to_owned(),
            });
        };
        drop(guard);

        let kind = entry.kind();
        let artifact_sha256 = entry.artifact_sha256().to_owned();
        // `strong_ref_count` includes the single Arc owned by `entry`.
        let remaining_external_refs = entry.strong_ref_count().saturating_sub(1);
        drop(entry);
        self.engine.metrics_handle().record_plugin_unloaded();

        Ok(UnloadReceipt {
            plugin_id: plugin_id.to_owned(),
            kind,
            artifact_sha256,
            remaining_external_refs,
            reclaimed_immediately: remaining_external_refs == 0,
        })
    }

    /// Looks up a loaded extended operator, optionally enforcing an exact frozen artifact SHA-256.
    pub fn get_extended_operator(
        &self,
        plugin_id: &str,
        expected_sha256: Option<&str>,
    ) -> Result<WasmExtendedOperator> {
        let guard = self.plugins.read().map_err(|_| Error::LockPoisoned)?;
        let entry = guard.get(plugin_id).ok_or_else(|| Error::PluginNotFound {
            plugin_id: plugin_id.to_owned(),
        })?;
        match entry {
            LoadedEntry::ExtendedOperator(op) => {
                check_expected_sha(plugin_id, op.artifact_sha256(), expected_sha256)?;
                Ok((**op).clone())
            }
            other => Err(Error::BindingMismatch {
                plugin_id: plugin_id.to_owned(),
                detail: format!(
                    "expected EXTENDED_OPERATOR, loaded plugin is {}",
                    other.kind().as_str()
                ),
            }),
        }
    }

    /// Looks up a loaded market-rule plugin, optionally enforcing an exact frozen artifact SHA-256.
    pub fn get_market_rule(
        &self,
        plugin_id: &str,
        expected_sha256: Option<&str>,
    ) -> Result<WasmMarketRulePlugin> {
        let guard = self.plugins.read().map_err(|_| Error::LockPoisoned)?;
        let entry = guard.get(plugin_id).ok_or_else(|| Error::PluginNotFound {
            plugin_id: plugin_id.to_owned(),
        })?;
        match entry {
            LoadedEntry::MarketRule(rule) => {
                check_expected_sha(plugin_id, rule.artifact_sha256(), expected_sha256)?;
                Ok(rule.clone())
            }
            other => Err(Error::BindingMismatch {
                plugin_id: plugin_id.to_owned(),
                detail: format!(
                    "expected MARKET_RULE, loaded plugin is {}",
                    other.kind().as_str()
                ),
            }),
        }
    }

    /// Looks up the strategy with the exact frozen execution binding.
    pub fn get_strategy(&self, binding: &ArtifactBinding) -> Result<WasmStrategyPlugin> {
        let guard = self.plugins.read().map_err(|_| Error::LockPoisoned)?;
        match Self::verified_entry(&guard, binding)? {
            LoadedEntry::Strategy(strategy) => Ok(strategy.clone()),
            other => Err(Error::BindingMismatch {
                plugin_id: binding.plugin_id.clone(),
                detail: format!(
                    "expected STRATEGY, loaded plugin is {}",
                    other.kind().as_str()
                ),
            }),
        }
    }

    /// Strictly verifies that a historical or frozen run binding matches the exact currently
    /// loaded plugin artifact, kind, WIT contract version, host version, and parameters.
    /// Rejects silent substitution with a newer version.
    pub fn verify_binding(&self, binding: &ArtifactBinding) -> Result<()> {
        let guard = self.plugins.read().map_err(|_| Error::LockPoisoned)?;
        Self::verified_entry(&guard, binding).map(|_| ())
    }

    fn verified_entry<'a>(
        plugins: &'a BTreeMap<String, LoadedEntry>,
        binding: &ArtifactBinding,
    ) -> Result<&'a LoadedEntry> {
        if binding.wit_contract_version != WIT_CONTRACT_VERSION {
            return Err(Error::UnsupportedContractVersion {
                expected: WIT_CONTRACT_VERSION.to_owned(),
                actual: binding.wit_contract_version.clone(),
            });
        }
        if binding.host_version != HOST_RUNTIME_VERSION {
            return Err(Error::UnsupportedContractVersion {
                expected: HOST_RUNTIME_VERSION.to_owned(),
                actual: binding.host_version.clone(),
            });
        }
        let entry = plugins
            .get(&binding.plugin_id)
            .ok_or_else(|| Error::PluginNotFound {
                plugin_id: binding.plugin_id.clone(),
            })?;
        if entry.kind() != binding.kind {
            return Err(Error::BindingMismatch {
                plugin_id: binding.plugin_id.clone(),
                detail: format!(
                    "kind mismatch: binding expects {}, loaded is {}",
                    binding.kind.as_str(),
                    entry.kind().as_str()
                ),
            });
        }
        if entry.artifact_sha256() != binding.artifact_sha256 {
            return Err(Error::Sha256Mismatch {
                expected: binding.artifact_sha256.clone(),
                actual: entry.artifact_sha256().to_owned(),
            });
        }
        match entry {
            LoadedEntry::ExtendedOperator(op)
                if *op.canonical_parameters() != binding.canonical_parameters =>
            {
                return Err(Error::BindingMismatch {
                    plugin_id: binding.plugin_id.clone(),
                    detail: "canonical_parameters mismatch against certified operator binding"
                        .into(),
                });
            }
            LoadedEntry::MarketRule(_) if !binding.canonical_parameters.is_empty() => {
                return Err(Error::BindingMismatch {
                    plugin_id: binding.plugin_id.clone(),
                    detail: "market-rule plugin bindings do not accept canonical_parameters".into(),
                });
            }
            LoadedEntry::Strategy(strategy)
                if strategy.binding().canonical_parameters != binding.canonical_parameters =>
            {
                return Err(Error::BindingMismatch {
                    plugin_id: binding.plugin_id.clone(),
                    detail: "canonical_parameters mismatch against frozen strategy binding".into(),
                });
            }
            _ => {}
        }
        Ok(entry)
    }

    pub fn list_loaded(&self) -> Result<Vec<LoadedPluginSummary>> {
        let guard = self.plugins.read().map_err(|_| Error::LockPoisoned)?;
        Ok(guard
            .iter()
            .map(|(plugin_id, entry)| LoadedPluginSummary {
                plugin_id: plugin_id.clone(),
                kind: entry.kind(),
                artifact_sha256: entry.artifact_sha256().to_owned(),
                wit_contract_version: WIT_CONTRACT_VERSION.to_owned(),
                host_version: entry.host_version().to_owned(),
                ready: true,
            })
            .collect())
    }

    fn ensure_slot_free(&self, plugin_id: &str) -> Result<()> {
        let guard = self.plugins.read().map_err(|_| Error::LockPoisoned)?;
        if guard.contains_key(plugin_id) {
            return Err(Error::PluginAlreadyLoaded {
                plugin_id: plugin_id.to_owned(),
            });
        }
        Ok(())
    }
}

fn check_expected_sha(plugin_id: &str, actual_sha: &str, expected_sha: Option<&str>) -> Result<()> {
    if let Some(expected) = expected_sha
        && actual_sha != expected
    {
        return Err(Error::Sha256Mismatch {
            expected: expected.to_owned(),
            actual: actual_sha.to_owned(),
        });
    }
    let _ = plugin_id;
    Ok(())
}
