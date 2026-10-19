use crate::model::*;
use onlyalpha_domain::{base::OnlyDomainModel, value::OnlyCurrency};
use serde_json::{Value, json};
/// Technical component composition. Queries fail while a committed projection prefix is incomplete.
pub struct Components {
    pub(crate) config: Value,
    pub(crate) precision: u8,
    pub(crate) order: onlyalpha_order::Manager,
    pub(crate) position: onlyalpha_position::Manager,
    pub(crate) account: onlyalpha_account::Manager,
    pub(crate) ledger: onlyalpha_strategy_ledger::Manager,
    pub(crate) risk: onlyalpha_risk::Manager,
    pub(crate) meta: Value,
    pub(crate) sequence: u64,
    pub(crate) pending: Option<(String, usize)>,
}
impl Components {
    pub fn new(config: Value) -> Result<Self, Error> {
        row(
            &config,
            &[
                "engine",
                "runtime",
                "account",
                "gateway",
                "generation",
                "runtime_kind",
                "currency",
                "initial_cash",
                "capitals",
                "profiles",
                "instruments",
            ],
        )?;
        for f in ["engine", "runtime", "account", "gateway", "generation"] {
            id(&config[f])?;
        }
        fp(&config["generation"])?;
        let currency = OnlyCurrency::from_record(&config["currency"])?;
        if currency.to_record() != config["currency"] {
            return Err(err("EXECUTION_CURRENCY"));
        }
        if !matches!(text(&config["runtime_kind"])?, "BACKTEST" | "SIM" | "LIVE") {
            return Err(err("EXECUTION_RUNTIME_KIND"));
        }
        let profiles = config["profiles"]
            .as_object()
            .filter(|r| !r.is_empty())
            .ok_or_else(|| err("EXECUTION_PROFILES"))?;
        if config["capitals"]
            .as_object()
            .map(|r| r.keys().collect::<Vec<_>>())
            != Some(profiles.keys().collect())
        {
            return Err(err("EXECUTION_CAPITAL_SCOPE"));
        }
        let instruments = config["instruments"]
            .as_array()
            .filter(|a| !a.is_empty())
            .ok_or_else(|| err("EXECUTION_INSTRUMENTS"))?;
        for i in instruments {
            if i["multiplier"] != "1" {
                return Err(err("EXECUTION_T0_MULTIPLIER"));
            }
        }
        let known: std::collections::BTreeSet<_> =
            instruments.iter().map(|i| i["id"].as_str()).collect();
        for profile in profiles.values() {
            let entries = profile["instruments"]
                .as_array()
                .ok_or_else(|| err("EXECUTION_PROFILE_INSTRUMENTS"))?;
            if entries.iter().any(|i| !known.contains(&i.as_str())) {
                return Err(err("EXECUTION_PROFILE_INSTRUMENTS"));
            }
        }
        if config["initial_cash"]
            != money(&nonnegative(&config["initial_cash"])?, currency.precision())?
        {
            return Err(err("EXECUTION_CONFIG_NONCANONICAL"));
        }
        for amount in config["capitals"]
            .as_object()
            .expect("validated capitals")
            .values()
        {
            if *amount != money(&nonnegative(amount)?, currency.precision())? {
                return Err(err("EXECUTION_CONFIG_NONCANONICAL"));
            }
        }
        let base = json!({"schema_version":1,"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"generation":config["generation"]});
        let mut pc = base.clone();
        pc["gateway"] = config["gateway"].clone();
        pc["currency"] = config["currency"].clone();
        pc["clusters"] = json!(profiles.keys().collect::<Vec<_>>());
        pc["instruments"] = config["instruments"].clone();
        let mut ac = base.clone();
        ac["gateway"] = config["gateway"].clone();
        ac["currency"] = config["currency"].clone();
        ac["account_type"] = json!("CASH");
        ac["initial_cash"] = config["initial_cash"].clone();
        let mut lc = base.clone();
        lc["runtime_kind"] = config["runtime_kind"].clone();
        lc["currency"] = config["currency"].clone();
        lc["account_initial_cash"] = config["initial_cash"].clone();
        lc["capitals"] = config["capitals"].clone();
        let mut rc = base;
        rc["runtime_kind"] = config["runtime_kind"].clone();
        rc["currency"] = config["currency"].clone();
        rc["clusters"] = config["profiles"].clone();
        rc["admission_limits"] = json!({"schema_version":1,"commands":4096,"journal_bytes":8388608,"checkpoint_bytes":33554432,"reservations":1024});
        Ok(Self {
            precision: currency.precision(),
            order: boundary(onlyalpha_order::Manager::new(
                json!({"schema_version":1,"engine_id":config["engine"],"runtime_id":config["runtime"],"gateway_id":config["gateway"],"generation":config["generation"]}),
            ))?,
            position: boundary(onlyalpha_position::Manager::new(pc))?,
            account: boundary(onlyalpha_account::Manager::new(ac))?,
            ledger: boundary(onlyalpha_strategy_ledger::Manager::new(lc))?,
            risk: boundary(onlyalpha_risk::Manager::new(rc))?,
            config,
            meta: json!({"schema_version":1,"orders":{},"inputs":{},"sources":{},"fees":{},"settlements":{},"markets":{},"valuations":{},"last_runtime_sequence":0,"transactions":{},"marks":{}}),
            sequence: 0,
            pending: None,
        })
    }
    pub(crate) fn ready_source<S: crate::Store>(&self, store: &S) -> Result<(), Error> {
        if self.pending.is_some() || store.head()? != self.sequence {
            return Err(err("EXECUTION_NOT_PROJECTION_READY"));
        }
        let current = self.payloads()?;
        let expected = Self::ready_prefix(store, &self.config, self.sequence)?;
        for (i, value) in current.iter().enumerate() {
            if expected[i] != hash(value) {
                return Err(err("EXECUTION_READY_SOURCE_CONFLICT"));
            }
        }

        Ok(())
    }
    pub(crate) fn ready_prefix<S: crate::Store>(
        store: &S,
        config: &Value,
        sequence: u64,
    ) -> Result<Vec<String>, Error> {
        let mut previous: Vec<_> = Self::new(config.clone())?
            .payloads()?
            .iter()
            .map(hash)
            .collect();
        for n in 1..=sequence {
            let record = store
                .get(n)?
                .ok_or_else(|| err("EXECUTION_READY_SOURCE_MISSING"))?;
            let p = record.prepared();
            if !record.ready() || p.sequence() != n || p.value["config_hash"] != hash(config) {
                return Err(err("EXECUTION_READY_SOURCE_CONFLICT"));
            }
            for (i, h) in previous.iter_mut().enumerate() {
                let projection = &p.value["projections"][i];
                if projection["before_hash"] != *h {
                    return Err(err("EXECUTION_READY_LINEAGE_CONFLICT"));
                }
                *h = text(&projection["result_hash"])?.into();
            }
        }
        Ok(previous)
    }
    pub fn state<S: crate::Store>(&self, store: &S) -> Result<Value, Error> {
        self.ready_source(store)?;
        Ok(
            json!({"schema_version":1,"execution_sequence":self.sequence,"account":self.account.state(),"position":self.position.state(),"ledger":self.ledger.state(),"risk":self.risk.state(),"execution":self.meta}),
        )
    }
    pub(crate) fn payloads(&self) -> Result<Vec<Value>, Error> {
        let mut ps = vec![];
        for bytes in [
            boundary(self.order.checkpoint())?.0,
            boundary(self.position.checkpoint())?.0,
            boundary(self.account.checkpoint())?.0,
            boundary(self.ledger.checkpoint())?.0,
            boundary(self.risk.checkpoint())?.0,
        ] {
            ps.push(serde_json::from_slice(&bytes)?);
        }
        ps.push(self.meta.clone());
        Ok(ps)
    }
    pub fn checkpoint(&self) -> Result<Value, Error> {
        Ok(
            json!({"schema_version":1,"config":self.config,"sequence":self.sequence,"pending":self.pending.as_ref().map(|(id,i)|json!([id,i])),"components":self.payloads()?}),
        )
    }
    pub fn restore(&mut self, v: &Value, expected: &str) -> Result<(), Error> {
        if hash(v) != expected {
            return Err(err("EXECUTION_CHECKPOINT_DIGEST"));
        }
        row(v, &["config", "sequence", "pending", "components"])?;
        if v["config"] != self.config {
            return Err(err("EXECUTION_CHECKPOINT_CONTEXT"));
        }
        let ps = v["components"]
            .as_array()
            .filter(|a| a.len() == 6)
            .ok_or_else(|| err("EXECUTION_CHECKPOINT_COMPONENTS"))?;
        let mut fresh = Self::new(self.config.clone())?;
        for (i, p) in ps.iter().enumerate() {
            fresh.install_payload(i, p)?;
        }
        fresh.sequence = uint(&v["sequence"])?;
        fresh.pending = if v["pending"].is_null() {
            None
        } else {
            let a = v["pending"]
                .as_array()
                .filter(|a| a.len() == 2)
                .ok_or_else(|| err("EXECUTION_CHECKPOINT_PENDING"))?;
            let i =
                usize::try_from(uint(&a[1])?).map_err(|_| err("EXECUTION_CHECKPOINT_PENDING"))?;
            if i > 6 {
                return Err(err("EXECUTION_CHECKPOINT_PENDING"));
            }
            Some((text(&a[0])?.into(), i))
        };
        if fresh.checkpoint()? != *v {
            return Err(err("EXECUTION_CHECKPOINT_NONCANONICAL"));
        }
        *self = fresh;
        Ok(())
    }
    fn install_payload(&mut self, i: usize, p: &Value) -> Result<(), Error> {
        let b = serde_json::to_vec(p)?;
        let h = digest(&b);
        match i {
            0 => boundary(self.order.restore(&b, &h))?,
            1 => boundary(self.position.restore(&b, &h))?,
            2 => boundary(self.account.restore(&b, &h))?,
            3 => boundary(self.ledger.restore(&b, &h))?,
            4 => boundary(self.risk.restore(&b, &h))?,
            5 => {
                row(
                    p,
                    &[
                        "orders",
                        "inputs",
                        "sources",
                        "fees",
                        "settlements",
                        "markets",
                        "valuations",
                        "last_runtime_sequence",
                        "transactions",
                        "marks",
                    ],
                )?;
                for f in [
                    "orders",
                    "inputs",
                    "sources",
                    "fees",
                    "settlements",
                    "markets",
                    "valuations",
                ] {
                    if !p[f].is_object() {
                        return Err(err("EXECUTION_METADATA"));
                    }
                }
                self.meta = p.clone();
            }
            _ => return Err(err("EXECUTION_PROJECTION_INDEX")),
        }
        Ok(())
    }
    pub fn install_projection<S: crate::Store>(
        &mut self,
        store: &S,
        p: &Prepared,
        i: usize,
    ) -> Result<(), Error> {
        p.validate()?;
        let committed = store
            .get(p.sequence())?
            .ok_or_else(|| err("EXECUTION_COMMIT_REQUIRED"))?;
        if committed.prepared() != p {
            return Err(err("EXECUTION_COMMIT_PAYLOAD_CONFLICT"));
        }
        if p.sequence() > 1 && !store.get(p.sequence() - 1)?.is_some_and(|v| v.ready()) {
            return Err(err("EXECUTION_PREDECESSOR_UNREADY"));
        }
        if p.value["config_hash"] != hash(&self.config) || p.value["predecessor"] != self.sequence {
            return Err(err("EXECUTION_PROJECTION_SCOPE_OR_SEQUENCE"));
        }
        if i >= 6 {
            return Err(err("EXECUTION_PROJECTION_INDEX"));
        }
        let next = match &self.pending {
            None => 0,
            Some((id, next)) if id == p.id() => *next,
            _ => return Err(err("EXECUTION_PENDING_CONFLICT")),
        };
        if i > next {
            return Err(err("EXECUTION_PROJECTION_ORDER"));
        }
        if self.pending.is_none() {
            self.pending = Some((p.id().into(), 0));
        }
        let projection = &p.value["projections"][i];
        let current = self.payloads()?[i].clone();
        let h = hash(&current);
        if i < next {
            if projection["result_hash"] != h {
                return Err(err("EXECUTION_RESULT_CONFLICT"));
            }
            return Ok(());
        }
        if projection["result_hash"] != h {
            if projection["before_hash"] != h {
                return Err(err("EXECUTION_BEFORE_CONFLICT"));
            }
            self.install_payload(i, &projection["result"])?;
        }
        self.pending = Some((p.id().into(), i + 1));
        Ok(())
    }
    /// Technical acknowledgement after the owning Store has durably marked Ready.
    pub fn complete<S: crate::Store>(&mut self, store: &S, p: &Prepared) -> Result<(), Error> {
        let ready = store
            .get(p.sequence())?
            .ok_or_else(|| err("EXECUTION_READY_REQUIRED"))?;
        if !ready.ready() || ready.prepared() != p {
            return Err(err("EXECUTION_READY_REQUIRED"));
        }
        if self.pending.as_ref() != Some(&(p.id().into(), 6))
            || p.value["predecessor"] != self.sequence
        {
            return Err(err("EXECUTION_INCOMPLETE"));
        }
        for (i, value) in self.payloads()?.iter().enumerate() {
            if p.value["projections"][i]["result_hash"] != hash(value) {
                return Err(err("EXECUTION_COMPLETION_RESULT_CONFLICT"));
            }
        }
        self.sequence = p.sequence();
        self.pending = None;
        Ok(())
    }
}
