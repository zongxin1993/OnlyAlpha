use crate::model::*;
use num_bigint::BigInt;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Clone)]
pub struct Manager {
    pub(crate) config: Value,
    pub(crate) precision: u8,
    pub(crate) profiles: BTreeMap<String, Profile>,
    pub(crate) reservations: BTreeMap<String, Hold>,
    pub(crate) decisions: BTreeMap<String, Value>,
    pub(crate) request_inputs: BTreeMap<String, Value>,
    pub(crate) request_orders: BTreeMap<String, String>,
    pub(crate) receipts: BTreeMap<String, (String, Option<Value>)>,
    pub(crate) aliases: BTreeMap<String, String>,
    pub(crate) sources: BTreeMap<String, String>,
    pub(crate) kills: BTreeSet<String>,
    pub(crate) audits: Vec<Value>,
    pub(crate) journal: Vec<Value>,
    pub(crate) sequence: u64,
    pub(crate) epoch: u64,
    pub(crate) watermark: u64,
    pub(crate) now: Option<BigInt>,
}
impl Manager {
    pub fn new(mut config_value: Value) -> Result<Self, Error> {
        let (p, profiles) = config(&config_value)?;
        for (cluster, profile) in &profiles {
            config_value["clusters"][cluster]["instruments"] = json!(profile.instruments);
            config_value["clusters"][cluster]["rules"]=json!(profile.rules.iter().map(|r|json!({"schema_version":1,"id":r.id,"scope":r.scope,"order":r.order,"mode":if r.observing{"OBSERVING"}else{"ENFORCING"},"kind":r.kind,"limit":norm(&r.limit)})).collect::<Vec<_>>());
        }
        Ok(Self {
            config: config_value,
            precision: p,
            profiles,
            reservations: BTreeMap::new(),
            decisions: BTreeMap::new(),
            request_inputs: BTreeMap::new(),
            request_orders: BTreeMap::new(),
            receipts: BTreeMap::new(),
            aliases: BTreeMap::new(),
            sources: BTreeMap::new(),
            kills: BTreeSet::new(),
            audits: vec![],
            journal: vec![],
            sequence: 0,
            epoch: 0,
            watermark: 0,
            now: None,
        })
    }
    pub fn snapshot(&self, cluster: &str) -> Result<Value, Error> {
        if !self.profiles.contains_key(cluster) {
            return Err(err("RISK_CLUSTER_UNKNOWN"));
        }
        let holds: Vec<_> = self
            .reservations
            .values()
            .filter(|h| h.cluster == cluster && h.state == "ACTIVE")
            .collect();
        let notional: Decimal = holds.iter().map(|h| h.remaining_notional()).sum();
        let cash: Decimal = holds.iter().map(|h| h.cash()).sum();
        Ok(
            json!({"schema_version":1,"engine":self.config["engine"],"runtime":self.config["runtime"],"account":self.config["account"],"generation":self.config["generation"],"cluster":cluster,"revision":self.profiles[cluster].revision,"sequence":self.sequence,"admission_epoch":self.epoch,"active_count":holds.len(),"reserved_notional":money(&notional,self.precision),"cash_hold":money(&cash,self.precision),"kill_switch":self.kills.contains("RUNTIME")||self.kills.contains("ACCOUNT")||self.kills.contains(&key("CLUSTER",cluster))}),
        )
    }
    pub fn state(&self) -> Value {
        let holds: BTreeMap<_, _> = self
            .reservations
            .iter()
            .map(|(k, v)| (k, v.record(self.precision)))
            .collect();
        json!({"reservations":holds,"decisions":self.decisions,"request_inputs":self.request_inputs,"request_orders":self.request_orders,"receipts":self.receipts,"aliases":self.aliases,"sources":self.sources,"kill_switches":self.kills,"audits":self.audits,"sequence":self.sequence,"admission_epoch":self.epoch,"economic_watermark":self.watermark,"time":self.now.as_ref().map(ToString::to_string),"active_count":self.reservations.values().filter(|r|r.state=="ACTIVE").count()})
    }
    pub fn apply(&mut self, input: &Value) -> Result<Outcome, Error> {
        if input.to_string().len() > 65536 {
            return Err(err("RISK_COMMAND_BOUND"));
        }
        let mut command = input.clone();
        self.normalize(&mut command)?;
        let r = row(
            &command,
            &[
                "engine",
                "runtime",
                "account",
                "generation",
                "cluster",
                "command_id",
                "causal",
                "time",
                "runtime_sequence",
                "op",
                "payload",
            ],
        )?;
        for f in ["engine", "runtime", "account", "generation"] {
            if r[f] != self.config[f] {
                return Err(err("RISK_COMMAND_CONTEXT"));
            }
        }
        let cluster = id(&r["cluster"])?;
        if !self.profiles.contains_key(&cluster) {
            return Err(err("RISK_CLUSTER_UNKNOWN"));
        }
        let receipt = id(&r["command_id"])?;
        fp(&r["causal"])?;
        let n = uint(&r["runtime_sequence"])?;
        let now = time(&r["time"])?;
        let fingerprint = hash(&command);
        if let Some((old, d)) = self.receipts.get(&receipt) {
            return if old == &fingerprint {
                Ok(Outcome {
                    status: Status::Duplicate,
                    decision: d.clone(),
                })
            } else {
                Err(err("RISK_COMMAND_ID_CONFLICT"))
            };
        }
        if n <= self.sequence || self.now.as_ref().is_some_and(|t| &now < t) {
            return Err(err("RISK_SEQUENCE_OR_TIME_REGRESSION"));
        }
        let mut candidate = self.clone();
        let op = text(&r["op"])?;
        let payload = &r["payload"];
        let mut status = Status::Applied;
        let decision = match op {
            "EVALUATE" => {
                let (d, duplicate) = candidate.evaluate(&cluster, payload, n)?;
                if duplicate {
                    status = Status::Duplicate;
                }
                Some(d)
            }
            "RESERVE" => {
                if candidate.reserve(&cluster, payload)? {
                    status = Status::Duplicate;
                }
                None
            }
            "STAGE" | "FILL" | "TERMINAL" => {
                if candidate.transition(&cluster, op, payload, n)? {
                    status = Status::Duplicate;
                }
                None
            }
            "KILL" => {
                let p = row(payload, &["scope", "active"])?;
                let scope = text(&p["scope"])?;
                if !matches!(scope, "RUNTIME" | "ACCOUNT" | "CLUSTER") {
                    return Err(err("RISK_KILL_SCOPE"));
                }
                let target = if scope == "CLUSTER" {
                    key(scope, &cluster)
                } else {
                    scope.into()
                };
                let active = boolean(&p["active"])?;
                let changed = if active {
                    candidate.kills.insert(target)
                } else {
                    candidate.kills.remove(&target)
                };
                if changed {
                    candidate.advance_epoch()?;
                }
                None
            }
            _ => return Err(err("RISK_OPERATION_UNKNOWN")),
        };
        candidate.sequence = n;
        candidate.now = Some(now);
        candidate
            .receipts
            .insert(receipt, (fingerprint, decision.clone()));
        // Capacity is admission backpressure, never permission to abandon accepted risk.
        // Every accepted safety occurrence retains complete receipts/history and remains recoverable.
        let increases = match op {
            "EVALUATE" => payload["request"]["effect"] == "OPEN",
            "RESERVE" => candidate
                .request_inputs
                .get(&key(&cluster, text(&payload["request_id"])?))
                .is_some_and(|v| v["request"]["effect"] == "OPEN"),
            _ => false,
        };
        candidate.journal.push(command);
        if increases && status != Status::Duplicate {
            let limits = &candidate.config["admission_limits"];
            let count = candidate.journal.len() as u64;
            let journal_bytes = serde_json::to_vec(&candidate.journal)?.len() as u64;
            let checkpoint_bytes = candidate.checkpoint()?.0.len() as u64;
            if count > uint(&limits["commands"])?
                || journal_bytes > uint(&limits["journal_bytes"])?
                || checkpoint_bytes > uint(&limits["checkpoint_bytes"])?
                || candidate.reservations.len() as u64 > uint(&limits["reservations"])?
            {
                return Err(err("RISK_CAPACITY_NEW_RISK_BLOCKED"));
            }
        }
        *self = candidate;
        Ok(Outcome { status, decision })
    }
    fn normalize(&self, c: &mut Value) -> Result<(), Error> {
        fn normalize_decimal(record: &mut Value, field: &str, precision: u8) -> Result<(), Error> {
            let slot = record
                .get_mut(field)
                .ok_or_else(|| err("RISK_FIELDS_INVALID"))?;
            if !slot.is_null() {
                *slot = json!(norm(&dec(slot, precision)?));
            }
            Ok(())
        }
        let op = text(&c["op"])?.to_string();
        if op == "EVALUATE" {
            let payload = c
                .get_mut("payload")
                .ok_or_else(|| err("RISK_FIELDS_INVALID"))?;
            let request = payload
                .get_mut("request")
                .ok_or_else(|| err("RISK_FIELDS_INVALID"))?;
            for f in ["quantity", "price", "notional", "fee", "cash_requirement"] {
                normalize_decimal(
                    request,
                    f,
                    if matches!(f, "quantity" | "price") {
                        18
                    } else {
                        self.precision
                    },
                )?;
            }
            let views = payload
                .get_mut("views")
                .ok_or_else(|| err("RISK_FIELDS_INVALID"))?;
            for family in ["account", "ledger", "position"] {
                let view = views
                    .get_mut(family)
                    .ok_or_else(|| err("RISK_FIELDS_INVALID"))?;
                if view.is_null() {
                    continue;
                }
                let data = view
                    .get_mut("data")
                    .ok_or_else(|| err("RISK_FIELDS_INVALID"))?;
                let fields: &[&str] = if family == "position" {
                    &["account_available", "allocation_available"]
                } else {
                    &["cash"]
                };
                for f in fields {
                    normalize_decimal(
                        data,
                        f,
                        if family == "position" {
                            18
                        } else {
                            self.precision
                        },
                    )?;
                }
            }
        } else if op == "FILL" {
            let payload = c
                .get_mut("payload")
                .ok_or_else(|| err("RISK_FIELDS_INVALID"))?;
            normalize_decimal(payload, "quantity", 18)?;
            normalize_decimal(payload, "notional", self.precision)?;
        }
        Ok(())
    }
    pub(crate) fn advance_epoch(&mut self) -> Result<(), Error> {
        self.epoch = self
            .epoch
            .checked_add(1)
            .ok_or_else(|| err("RISK_EPOCH_EXHAUSTED"))?;
        Ok(())
    }
    pub(crate) fn envelope<'a>(
        &mut self,
        v: &'a Value,
        family: &str,
        cluster: &str,
        instrument: &str,
        n: u64,
    ) -> Result<Option<&'a Value>, Error> {
        if v.is_null() {
            return Ok(None);
        }
        let r = row(
            v,
            &[
                "family",
                "engine",
                "runtime",
                "account",
                "generation",
                "cluster",
                "instrument",
                "revision",
                "source_ref",
                "version",
                "as_of_sequence",
                "source_digest",
                "data",
            ],
        )?;
        for f in ["engine", "runtime", "account", "generation"] {
            if r[f] != self.config[f] {
                return Err(err("RISK_PROOF_CONTEXT"));
            }
        }
        if r["family"] != family
            || r["cluster"] != cluster
            || r["instrument"] != instrument
            || r["revision"] != self.profiles[cluster].revision
        {
            return Err(err("RISK_PROOF_OWNER_RELATION"));
        }
        let source = id(&r["source_ref"])?;
        fp(&r["source_digest"])?;
        let version = uint(&r["version"])?;
        let at = uint(&r["as_of_sequence"])?;
        if version == 0 || at > n {
            return Err(err("RISK_PROOF_VERSION"));
        }
        let k = key(family, &source);
        let h = hash(v);
        if self.sources.get(&k).is_some_and(|old| old != &h) {
            return Err(err("RISK_SOURCE_ID_CONFLICT"));
        }
        self.sources.insert(k, h);
        if at < self.watermark {
            return Ok(None);
        }
        Ok(Some(&r["data"]))
    }
}
