use crate::{Components, Store, model::*};
use onlyalpha_domain::{base::OnlyDomainModel, time::OnlyTimestamp};
use serde_json::{Value, json};
use std::collections::BTreeSet;

/// Immutable finalization of an explicitly declared Execution transcript.
/// This is not market-driver exhaustion, Runtime admission or an Evidence publication.
/// ```compile_fail
/// use onlyalpha_execution::BacktestResult;
/// let forged = BacktestResult { value: serde_json::json!({"run":{"status":"COMPLETED"}}) };
/// ```
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BacktestResult {
    value: Value,
}
impl BacktestResult {
    pub fn record(&self) -> Value {
        self.value.clone()
    }
    pub fn encode(&self) -> Result<Vec<u8>, Error> {
        Ok(serde_json::to_vec(&self.value)?)
    }
}
fn timestamp(v: &Value) -> Result<OnlyTimestamp, Error> {
    if v.to_string().len() > 100 {
        return Err(err("RESULT_TIME_BOUND"));
    }
    let t = OnlyTimestamp::from_record(v)?;
    if t.to_record() != *v {
        return Err(err("RESULT_TIME_NONCANONICAL"));
    }
    Ok(t)
}
fn diagnostic(code: &str, details: Value) -> Value {
    json!({"severity":"ERROR","code":code,"details":details})
}
impl Components {
    /// Caller declares the immutable input pin, exact artifact, config and complete ordered
    /// transaction-input hashes. Only the admitted Runtime driver can bind these to a Dataset
    /// and prove its market/Broker/Event drain; this library grants no such authority.
    pub fn backtest_result<S: Store>(
        &self,
        store: &S,
        manifest: &Value,
        outcome: &Value,
    ) -> Result<BacktestResult, Error> {
        row(
            manifest,
            &[
                "configuration",
                "kernel_artifact",
                "input_pin",
                "initial_time",
                "final_time",
                "inputs",
            ],
        )?;
        row(outcome, &["status", "reason"])?;
        if self.config["runtime_kind"] != "BACKTEST"
            || manifest["configuration"] != hash(&self.config)
        {
            return Err(err("RESULT_CONFIGURATION"));
        }
        for f in ["configuration", "kernel_artifact", "input_pin"] {
            fp(&manifest[f])?;
        }
        let initial = timestamp(&manifest["initial_time"])?;
        let final_time = timestamp(&manifest["final_time"])?;
        if final_time < initial {
            return Err(err("RESULT_TIME_ORDER"));
        }
        let requested = text(&outcome["status"])?;
        if !matches!(
            requested,
            "COMPLETED" | "FAILED" | "CANCELLED" | "INCOMPLETE" | "UNKNOWN"
        ) {
            return Err(err("RESULT_OUTCOME"));
        }
        if requested == "COMPLETED" {
            if !outcome["reason"].is_null() {
                return Err(err("RESULT_COMPLETION_REASON"));
            }
        } else {
            text(&outcome["reason"])?;
        }
        let expected = manifest["inputs"]
            .as_array()
            .filter(|a| a.len() <= 65536)
            .ok_or_else(|| err("RESULT_MANIFEST_INPUTS"))?;
        let mut unique = BTreeSet::new();
        for v in expected {
            fp(v)?;
            if !unique.insert(text(v)?) {
                return Err(err("RESULT_DUPLICATE_INPUT"));
            }
        }
        let mut facts = Vec::new();
        let mut trades = Vec::new();
        let source = self.verified_source(store, |record| {
            let prepared = record.prepared();
            let input = prepared.input();
            if expected.get(facts.len()) != Some(&json!(hash(input))) {
                return Err(err("RESULT_INPUT_PREFIX"));
            }
            let t = timestamp(&json!({"schema_version":1,"unix_nanos":input["time"]}))?;
            if t < initial || t > final_time {
                return Err(err("RESULT_INPUT_TIME"));
            }
            let fact =
                json!({"sequence":prepared.sequence(),"transaction":prepared.id(),"input":input});
            if input["op"] == "FILL" {
                trades.push(fact.clone());
            }
            facts.push(fact);
            Ok(())
        })?;
        let complete = facts.len() == expected.len();
        if requested == "COMPLETED" && !complete {
            return Err(err("RESULT_TRANSCRIPT_INCOMPLETE"));
        }
        let reconciliation = self.reconcile(store)?.record();
        let performance = self.performance(store, &initial)?.record();
        if reconciliation["source"] != source || performance["source"] != source {
            return Err(err("RESULT_SOURCE_CHANGED"));
        }
        let runtime_performance = performance["performance"].clone();
        let account = self.account.snapshot();
        let position = self.position.state();
        let ledger = self.ledger.state();
        let orders: Value = serde_json::from_slice(&boundary(self.order.checkpoint())?.0)?;
        let genesis = Self::new(self.config.clone())?;
        let mut diagnostics = Vec::new();
        if requested != "COMPLETED" {
            diagnostics.push(diagnostic("DRIVER_TERMINATION", outcome.clone()));
        }
        if reconciliation["status"] != "MATCHED" {
            diagnostics.push(diagnostic(
                "LEDGER_RECONCILIATION_MISMATCH",
                reconciliation["differences"].clone(),
            ));
        }
        if account["status"] != "ACTIVE"
            || exact(&account["reserved"])? != 0
            || exact(&account["reserved_margin"])? != 0
        {
            diagnostics.push(diagnostic("ACCOUNT_NOT_FINAL", account.clone()));
        }
        if !position["stale"]
            .as_object()
            .ok_or_else(|| err("RESULT_POSITION_STATE"))?
            .is_empty()
        {
            diagnostics.push(diagnostic(
                "POSITION_RECONCILIATION_REQUIRED",
                position["stale"].clone(),
            ));
        }
        let mut clusters = Vec::new();
        let mut timelines = Vec::new();
        let mut final_ledgers = Vec::new();
        for cluster in self.config["capitals"]
            .as_object()
            .expect("validated capitals")
            .keys()
        {
            let snapshot = boundary(self.ledger.snapshot(cluster))?;
            let risk = boundary(self.risk.snapshot(cluster))?;
            let open = self
                .order
                .open(cluster)
                .iter()
                .map(OnlyDomainModel::to_record)
                .collect::<Vec<_>>();
            if !open.is_empty() {
                diagnostics.push(diagnostic(
                    "UNRESOLVED_ORDER",
                    json!({"cluster":cluster,"orders":open}),
                ));
            }
            if risk["active_count"] != 0 {
                diagnostics.push(diagnostic("RISK_HOLDS_REMAIN", risk));
            }
            if !snapshot["flags"]
                .as_array()
                .ok_or_else(|| err("RESULT_LEDGER_STATE"))?
                .is_empty()
            {
                diagnostics.push(diagnostic(
                    "LEDGER_RECONCILIATION_REQUIRED",
                    snapshot.clone(),
                ));
            }
            let mut timeline = vec![
                json!({"timeline_sequence":0,"source":"LEDGER_CREATED","time":manifest["initial_time"],"snapshot":boundary(genesis.ledger.snapshot(cluster))?}),
            ];
            for point in ledger["timeline"]
                .as_array()
                .ok_or_else(|| err("RESULT_LEDGER_TIMELINE"))?
            {
                if point["cluster"] == *cluster {
                    timeline.push(json!({"timeline_sequence":timeline.len(),"source":"LEDGER_OCCURRENCE","point":point}));
                }
            }
            // The Ledger owns these values, including its numerical and quality policy.
            let fields = [
                "initial_capital",
                "equity",
                "net_pnl",
                "realized_pnl",
                "unrealized_pnl",
                "fees",
                "simple_return",
                "high_water_mark",
                "drawdown",
                "maximum_drawdown",
                "external_cash_flow",
                "flags",
            ];
            let summary: serde_json::Map<_, _> = fields
                .into_iter()
                .map(|k| (k.into(), snapshot[k].clone()))
                .collect();
            clusters.push(json!({"cluster":cluster,"revision":self.config["profiles"][cluster]["revision"],"cluster_performance":{"authority":"STRATEGY_LEDGER","summary":summary},"final_ledger":snapshot}));
            timelines.push(json!({"cluster":cluster,"points":timeline}));
            final_ledgers.push(snapshot);
        }
        let blocked = diagnostics
            .iter()
            .any(|d| d["code"] != "DRIVER_TERMINATION");
        let status =
            if reconciliation["status"] == "MISMATCHED" || (requested == "COMPLETED" && blocked) {
                "FAILED"
            } else if requested == "UNKNOWN" {
                "INCOMPLETE"
            } else {
                requested
            };
        let mut value = json!({"schema_version":1,"semantic_version":"BACKTEST_RESULT@1","completion_scope":"EXECUTION_TRANSCRIPT","scope":self.config,"manifest":manifest,"source":source,
            "run":{"status":status,"requested_outcome":outcome,"initial_time":manifest["initial_time"],"final_time":manifest["final_time"]},
            "closure":{"complete":complete,"observed":facts.len(),"expected":expected.len()},
            "execution":{"transaction_count":facts.len(),"order_count":orders["state"]["orders"].as_array().ok_or_else(||err("RESULT_ORDER_STATE"))?.len(),"trade_count":trades.len()},
            "runtime_performance":runtime_performance,"final_account":account,"final_positions":position["accounts"],"final_allocations":position["allocations"],"final_ledgers":final_ledgers,
            "orders":orders["state"]["orders"],"trades":trades,"facts":facts,"cluster_results":clusters,
            "account_equity_timeline":runtime_performance["timeline"],"cluster_equity_timelines":timelines,"reconciliation":reconciliation,"diagnostics":diagnostics,
            "final_seal":{"kind":"READ_ONLY_OBSERVATION","time":manifest["final_time"],"source":source}});
        let fingerprint = hash(&value);
        value["determinism_fingerprint"] = json!(fingerprint);
        value["result_fingerprint"] = json!(fingerprint);
        value["id"] = json!(format!("BTR-{}", hash(&value)));
        Ok(BacktestResult { value })
    }
}
