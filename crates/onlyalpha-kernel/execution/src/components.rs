use crate::model::*;
use onlyalpha_domain::{base::OnlyDomainModel, value::OnlyCurrency};
use serde_json::{Value, json};
#[cfg(test)]
std::thread_local! {
    pub(crate) static PAYLOAD_CAPTURE_BYTES: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    pub(crate) static FULL_STATE_CONSTRUCTIONS: std::cell::Cell<u64> = const { std::cell::Cell::new(0) };
    pub(crate) static PROJECTION_RESTORES: std::cell::Cell<[u64;6]> = const { std::cell::Cell::new([0;6]) };
}
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
    payload_cache: std::sync::OnceLock<(std::sync::Arc<Vec<Value>>,Vec<String>)>,
}
impl Components {
    pub fn new(config: Value) -> Result<Self, Error> {
        let fields=["engine","runtime","account","gateway","generation","runtime_kind","currency","initial_cash","capitals","profiles","instruments"];
        let account_version=match config["schema_version"].as_u64(){
            Some(1)=>{row(&config,&fields)?;4},
            Some(2)=>{
                let r=config.as_object().ok_or_else(||err("EXECUTION_RECORD"))?;
                if r.len()!=fields.len()+2||fields.iter().any(|field|!r.contains_key(*field))||!r.contains_key("account_checkpoint_version"){return Err(err("EXECUTION_FIELDS"));}
                if config["account_checkpoint_version"]!=5||config["runtime_kind"]!="BACKTEST"{return Err(err("EXECUTION_ACCOUNT_CHECKPOINT_FORMAT"));}
                5
            },
            _=>return Err(err("EXECUTION_FIELDS")),
        };
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
        ac["schema_version"] = json!(2);
        ac["position_configuration"] = json!(hash(&pc));
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
            account: boundary(if account_version==5{onlyalpha_account::Manager::new_checkpoint5(ac)}else{onlyalpha_account::Manager::new(ac)})?,
            ledger: boundary(onlyalpha_strategy_ledger::Manager::new(lc))?,
            risk: boundary(onlyalpha_risk::Manager::new(rc))?,
            config: config.clone(),
            meta: json!({"schema_version":5,"orders":{},"inputs":{},"sources":{},"fee_authority":boundary(onlyalpha_fee::Manager::new(json!({"engine":config["engine"],"runtime":config["runtime"],"account":config["account"],"gateway":config["gateway"],"runtime_kind":config["runtime_kind"],"generation":config["generation"]}),4096))?.checkpoint(),"margin_authority":boundary(onlyalpha_margin::Manager::new(settlement_config(&config),512))?.checkpoint(),"settlement_authority":boundary(onlyalpha_settlement::Authority::new(settlement_config(&config),512))?.checkpoint(),"markets":{},"valuations":{},"last_runtime_sequence":0,"transactions":{},"marks":{},"valuation_marks":{},"valuation_sources":{}}),
            sequence: 0,
            pending: None,
            payload_cache: std::sync::OnceLock::new(),
        })
    }
    /// Borrowed canonical configuration only; this supplies no source or Ready proof.
    pub fn configuration(&self) -> &Value {
        &self.config
    }
    /// Independent data only; callers still prove their current owning Store.
    pub(crate) fn clone_data(&self) -> Self {
        Self {
            config: self.config.clone(), precision: self.precision,
            order: self.order.clone(), position: self.position.clone(),
            account: self.account.clone(),
            ledger: self.ledger.clone(),
            risk: self.risk.clone(), meta: self.meta.clone(),
            sequence: self.sequence, pending: self.pending.clone(),
            payload_cache: self.payload_cache.clone(),
        }
    }
    /// Copy an actual reconciled Ready head without a checkpoint round trip.
    /// This is neither persisted recovery nor a grant for another Store/head.
    pub fn fork_ready<S: crate::Store>(&self, store: &S) -> Result<Self, Error> {
        if self.pending.is_some() || store.head()? != self.sequence {
            return Err(err("EXECUTION_FORK_UNREADY"));
        }
        self.reconcile(store)?;
        Ok(self.clone_data())
    }
    pub(crate) fn ready_source<S: crate::Store>(&self, store: &S) -> Result<(), Error> {
        let _=self.payload_hashes()?;
        let genesis=Self::genesis_payload_hashes(&self.config)?;
        self.ready_source_with_genesis(store,&genesis)
    }
    pub(crate) fn genesis_payload_hashes(config:&Value)->Result<Vec<String>,Error>{
        Ok(Self::new(config.clone())?.payload_hashes()?.to_vec())
    }
    // Images are derived here from the same immutably borrowed owners. They
    // are data only; actual Store facts are still checked on every invocation.
    pub(crate) fn ready_source_with_genesis<S:crate::Store>(&self,store:&S,genesis:&[String])->Result<(),Error>{
        let current=self.payload_hashes()?;
        if self.pending.is_some()||store.head()?!=self.sequence{return Err(err("EXECUTION_NOT_PROJECTION_READY"));}
        let expected=Self::ready_prefix_with_genesis(store,&self.config,self.sequence,genesis.to_vec())?;
        if expected.as_slice()!=current{return Err(err("EXECUTION_READY_SOURCE_CONFLICT"));}
        Ok(())
    }
    pub(crate) fn ready_prefix<S: crate::Store>(store:&S,config:&Value,sequence:u64)->Result<Vec<String>,Error>{
        Self::ready_prefix_with_genesis(store,config,sequence,Self::genesis_payload_hashes(config)?)
    }
    fn ready_prefix_with_genesis<S:crate::Store>(store:&S,config:&Value,sequence:u64,mut previous:Vec<String>)->Result<Vec<String>,Error>{
        let configuration_hash=hash(config);
        match store.read_prefix(sequence)? {
            Some(records)=>{
                if u64::try_from(records.len()).ok()!=Some(sequence){return Err(err("EXECUTION_READY_SOURCE_CONFLICT"));}
                for (index,record) in records.iter().enumerate(){
                    Self::validate_ready_prefix_record(record,config,&configuration_hash,index as u64+1,&mut previous)?;
                }
            },
            None=>{
                // Keep each default get immediately followed by its original
                // validation. A later callback/error cannot overtake a bad row.
                for n in 1..=sequence {
                    let record=store.get(n)?.ok_or_else(||err("EXECUTION_READY_SOURCE_MISSING"))?;
                    Self::validate_ready_prefix_record(&record,config,&configuration_hash,n,&mut previous)?;
                }
            },
        }
        Ok(previous)
    }
    fn validate_ready_prefix_record(record:&crate::Record,config:&Value,configuration_hash:&str,n:u64,previous:&mut [String])->Result<(),Error>{
        let prepared=record.prepared();
        Self::require_account_checkpoint_for_config(config,&prepared.value()["projections"][2]["result"])?;
        if !record.ready()||prepared.sequence()!=n||prepared.value()["config_hash"]!=configuration_hash {
            return Err(err("EXECUTION_READY_SOURCE_CONFLICT"));
        }
        for (i,prior) in previous.iter_mut().enumerate(){
            let projection=&prepared.value()["projections"][i];
            if projection["before_hash"]!=*prior{return Err(err("EXECUTION_READY_LINEAGE_CONFLICT"));}
            *prior=text(&projection["result_hash"])?.to_owned();
        }
        Ok(())
    }
    /// Read-only proposed Order from the current owner for fee binding. Not admission or dispatch authority.
    pub fn fee_order_preview<S: crate::Store>(
        &self,
        store: &S,
        cluster: &str,
        request: &Value,
        at: u64,
    ) -> Result<onlyalpha_domain::execution::OnlyOrderSnapshot, Error> {
        self.ready_source(store)?;
        let (bytes, _) = boundary(self.order.checkpoint())?;
        let checkpoint: Value = serde_json::from_slice(&bytes)?;
        Self::fee_order_preview_checkpoint(&self.config, &checkpoint, cluster, request, at)
    }
    /// Pure original-owner preview for a checkpoint supplied by the owning Ready
    /// source. It returns no admission, Prepared transaction or dispatch identity.
    pub fn fee_order_preview_checkpoint(
        configuration: &Value,
        checkpoint: &Value,
        cluster: &str,
        request: &Value,
        at: u64,
    ) -> Result<onlyalpha_domain::execution::OnlyOrderSnapshot, Error> {
        if request.to_string().len() > 65536 {
            return Err(err("EXECUTION_INPUT_BOUND"));
        }
        bound_decimal_leaves(request)?;
        if configuration["profiles"].get(cluster).is_none() {
            return Err(err("EXECUTION_PREVIEW_SCOPE"));
        }
        let mut order=onlyalpha_order::Manager::new(json!({"schema_version":1,"engine_id":configuration["engine"],"runtime_id":configuration["runtime"],"gateway_id":configuration["gateway"],"generation":configuration["generation"]})).map_err(|e|err(&e.to_string()))?;
        let bytes = serde_json::to_vec(checkpoint)?;
        let digest = hash(checkpoint);
        order
            .restore(&bytes, &digest)
            .map_err(|e| err(&e.to_string()))?;
        let result=order.apply(&json!({"schema_version":1,"op":"CREATE","cluster_id":cluster,"account_id":configuration["account"],"request":request,"cause":hash(request),"at":at})).map_err(|e|err(&e.to_string()))?;
        if result.result != onlyalpha_order::ApplyResult::Applied {
            return Err(err("EXECUTION_PREVIEW_REQUEST_CONFLICT"));
        }
        result
            .snapshot
            .ok_or_else(|| err("EXECUTION_PREVIEW_MISSING"))
    }
    /// Owning read for Broker composition: no snapshot is available from an unready lineage.
    pub fn order_snapshot<S: crate::Store>(
        &self,
        store: &S,
        cluster: &str,
        order: &str,
    ) -> Result<onlyalpha_domain::execution::OnlyOrderSnapshot, Error> {
        self.ready_source(store)?;
        boundary(self.order.get(cluster, order))
    }
    /// Current owning submission lifecycle, used with the Ready intent and Order snapshot.
    /// A historical ADMIT alone cannot authorize a second external submit.
    pub fn order_submission<S: crate::Store>(
        &self,
        store: &S,
        cluster: &str,
        order: &str,
    ) -> Result<String, Error> {
        self.ready_source(store)?;
        Ok(boundary(self.order.submission(cluster, order))?.to_owned())
    }
    /// Exact Ready records through this component's applied head. These are read evidence,
    /// never new CommitIntent authoring authority and never an unready Store tail.
    pub fn ready_records<S: crate::Store>(&self, store: &S) -> Result<Vec<crate::Record>, Error> {
        self.ready_source(store)?;
        (1..=self.sequence)
            .map(|n| {
                store
                    .get(n)?
                    .ok_or_else(|| err("EXECUTION_READY_SOURCE_MISSING"))
            })
            .collect()
    }
    /// Current owning data only; the same full Ready/source guard as state().
    /// Position identity is its complete canonical checkpoint SHA, not metadata.
    pub fn position_order_view<S: crate::Store>(&self, store: &S) -> Result<Value, Error> {
        self.ready_source(store)?;
        let position = self.position.current_exposure();
        let account = self.account.snapshot();
        Ok(json!({"schema_version":1,"orders":self.meta["orders"],"position_accounts":position["accounts"],"position_allocations":position["allocations"],"economic_version":account["economic_version"],"position_checkpoint_fingerprint":self.payload_digest(1)?}))
    }
    pub fn state<S: crate::Store>(&self, store: &S) -> Result<Value, Error> {
        self.ready_source(store)?;
        #[cfg(test)]
        FULL_STATE_CONSTRUCTIONS.with(|count|count.set(count.get()+1));
        Ok(
            json!({"schema_version":1,"execution_sequence":self.sequence,"account":self.account.state(),"position":self.position.state(),"ledger":self.ledger.state(),"risk":self.risk.state(),"execution":self.meta}),
        )
    }
    fn require_account_checkpoint_for_config(config:&Value,value:&Value)->Result<(),Error>{
        let expected=if config["schema_version"]==2{5}else{4};
        if value["schema_version"]!=expected{return Err(err("EXECUTION_ACCOUNT_CHECKPOINT_FORMAT"));}
        Ok(())
    }
    pub(crate) fn require_account_checkpoint(&self,value:&Value)->Result<(),Error>{Self::require_account_checkpoint_for_config(&self.config,value)}
    pub(crate) fn invalidate_payloads(&mut self) {
        let _ = self.payload_cache.take();
    }
    pub(crate) fn payloads(&self) -> Result<std::sync::Arc<Vec<Value>>, Error> {
        if let Some(payloads) = self.payload_cache.get() {
            self.require_account_checkpoint(&payloads.0[2])?;
            return Ok(std::sync::Arc::clone(&payloads.0));
        }
        let mut ps = vec![];
        let mut fingerprints = Vec::with_capacity(6);
        for (bytes, fingerprint) in [
            boundary(self.order.checkpoint())?,
            boundary(self.position.checkpoint())?,
            boundary(self.account.checkpoint())?,
            boundary(self.ledger.checkpoint())?,
            boundary(self.risk.checkpoint())?,
        ] {
            #[cfg(test)]
            PAYLOAD_CAPTURE_BYTES.with(|count|count.set(count.get()+bytes.len() as u64));
            ps.push(serde_json::from_slice(&bytes)?);
            fingerprints.push(fingerprint);
        }
        #[cfg(test)]
        PAYLOAD_CAPTURE_BYTES.with(|count|count.set(count.get()+self.meta.to_string().len() as u64));
        ps.push(self.meta.clone());
        self.require_account_checkpoint(&ps[2])?;
        // Each actual owner already hashed its exact canonical bytes above.
        // Metadata has no separate encoder and retains its complete value hash.
        fingerprints.push(hash(&ps[5]));
        let payloads = std::sync::Arc::new(ps);
        let _ = self.payload_cache.set((payloads,fingerprints));
        Ok(std::sync::Arc::clone(&self.payload_cache.get().expect("codec image initialized").0))
    }
    pub(crate) fn payload_hashes(&self) -> Result<&[String],Error> {
        let _=self.payloads()?;
        Ok(&self.payload_cache.get().expect("codec image initialized").1)
    }
    pub(crate) fn payload_digest(&self, index: usize) -> Result<String, Error> {
        if index >= 6 { return Err(err("EXECUTION_PROJECTION_INDEX")); }
        if let Some((owners, hashes)) = self.payload_cache.get() {
            self.require_account_checkpoint(&owners[2])?;
            return Ok(hashes[index].clone());
        }
        // A partial installation invalidates the whole codec image. Read only
        // this actual owner here; completion still captures all six owners.
        if index == 5 {
            #[cfg(test)]
            PAYLOAD_CAPTURE_BYTES.with(|count|count.set(count.get()+self.meta.to_string().len() as u64));
            return Ok(hash(&self.meta));
        }
        let (bytes, fingerprint) = match index {
            0 => boundary(self.order.checkpoint())?,
            1 => boundary(self.position.checkpoint())?,
            2 => boundary(self.account.checkpoint())?,
            3 => boundary(self.ledger.checkpoint())?,
            4 => boundary(self.risk.checkpoint())?,
            _ => return Err(err("EXECUTION_PROJECTION_INDEX")),
        };
        #[cfg(test)]
        PAYLOAD_CAPTURE_BYTES.with(|count|count.set(count.get()+bytes.len() as u64));
        if index == 2 { self.require_account_checkpoint(&serde_json::from_slice(&bytes)?)?; }
        Ok(fingerprint)
    }
    pub fn checkpoint(&self) -> Result<Value, Error> {
        let mut checkpoint=json!({"schema_version":1,"config":self.config,"sequence":self.sequence,"pending":self.pending.as_ref().map(|(id,i)|json!([id,i]))});
        checkpoint.as_object_mut().expect("checkpoint object").insert("components".into(),Value::Array(self.payloads()?.as_ref().clone()));
        Ok(checkpoint)
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
        if fresh
            .pending
            .as_ref()
            .is_none_or(|(_, installed)| *installed == 6)
        {
            fresh.validate_valuation_metadata(&fresh.meta)?;
        }
        if fresh.checkpoint()? != *v {
            return Err(err("EXECUTION_CHECKPOINT_NONCANONICAL"));
        }
        *self = fresh;
        Ok(())
    }
    fn install_payload(&mut self, i: usize, p: &Value) -> Result<(), Error> {
        self.invalidate_payloads();
        #[cfg(test)]
        PROJECTION_RESTORES.with(|counts| {let mut actual=counts.get();if let Some(count)=actual.get_mut(i){*count+=1;}counts.set(actual);});
        let b = serde_json::to_vec(p)?;
        let h = digest(&b);
        match i {
            0 => boundary(self.order.restore(&b, &h))?,
            1 => boundary(self.position.restore(&b, &h))?,
            2 => {self.require_account_checkpoint(p)?;boundary(self.account.restore(&b, &h))?;},
            3 => boundary(self.ledger.restore(&b, &h))?,
            4 => boundary(self.risk.restore(&b, &h))?,
            5 => {
                if p["schema_version"] != 5 {
                    return Err(err("EXECUTION_ECONOMIC_METADATA_SCHEMA"));
                }
                let mut shape = p.clone();
                shape["schema_version"] = json!(1);
                row(
                    &shape,
                    &[
                        "orders",
                        "inputs",
                        "sources",
                        "fee_authority",
                        "settlement_authority",
                        "margin_authority",
                        "markets",
                        "valuations",
                        "last_runtime_sequence",
                        "transactions",
                        "marks",
                        "valuation_marks",
                        "valuation_sources",
                    ],
                )?;
                for f in ["orders", "inputs", "sources", "markets", "valuations"] {
                    if !p[f].is_object() {
                        return Err(err("EXECUTION_METADATA"));
                    }
                }
                let mut fee = boundary(onlyalpha_fee::Manager::new(
                    json!({"engine":self.config["engine"],"runtime":self.config["runtime"],"account":self.config["account"],"gateway":self.config["gateway"],"runtime_kind":self.config["runtime_kind"],"generation":self.config["generation"]}),
                    4096,
                ))?;
                boundary(fee.restore(
                    &p["fee_authority"],
                    &onlyalpha_fee::digest(&p["fee_authority"]),
                ))?;
                let mut settlement = boundary(onlyalpha_settlement::Authority::new(
                    settlement_config(&self.config),
                    512,
                ))?;
                boundary(settlement.restore(
                    &p["settlement_authority"],
                    &onlyalpha_settlement::digest(&p["settlement_authority"]),
                ))?;
                let mut margin = boundary(onlyalpha_margin::Manager::new(
                    settlement_config(&self.config),
                    512,
                ))?;
                boundary(margin.restore(
                    &p["margin_authority"],
                    &onlyalpha_margin::digest(&p["margin_authority"]),
                ))?;
                self.meta = p.clone();
            }
            _ => return Err(err("EXECUTION_PROJECTION_INDEX")),
        }
        Ok(())
    }
    pub(crate) fn validated_typed_after(p:&Prepared,i:usize)->Result<Option<&Self>,Error> {
        if i>=6{return Err(err("EXECUTION_PROJECTION_INDEX"));}
        let projection=&p.value()["projections"][i];
        let typed_after=p.typed_after();
        if let Some(after)=typed_after {
            if !p.is_planned(){return Err(err("EXECUTION_TYPED_AFTER_ORIGIN"));}
            if hash(&after.config)!=p.value()["config_hash"]{return Err(err("EXECUTION_TYPED_AFTER_CONFLICT"));}
            let (actual,actual_hash)=if i==5 {(after.meta.clone(),hash(&after.meta))}else{
                let (bytes,hash)=match i {
                    0=>boundary(after.order.checkpoint())?,
                    1=>boundary(after.position.checkpoint())?,
                    2=>boundary(after.account.checkpoint())?,
                    3=>boundary(after.ledger.checkpoint())?,
                    4=>boundary(after.risk.checkpoint())?,
                    _=>return Err(err("EXECUTION_PROJECTION_INDEX")),
                };
                (serde_json::from_slice::<Value>(&bytes)?,hash)
            };
            if i==2{after.require_account_checkpoint(&actual)?;}
            if actual!=projection["result"]||actual_hash!=projection["result_hash"] {
                return Err(err("EXECUTION_TYPED_AFTER_CONFLICT"));
            }
        }
        Ok(typed_after)
    }
    pub fn install_projection<S: crate::Store>(
        &mut self,
        store: &S,
        p: &Prepared,
        i: usize,
    ) -> Result<(), Error> {
        let committed = store
            .get(p.sequence())?
            .ok_or_else(|| err("EXECUTION_COMMIT_REQUIRED"))?;
        if committed.prepared() != p {
            return Err(err("EXECUTION_COMMIT_PAYLOAD_CONFLICT"));
        }
        if p.sequence() > 1 && !store.get(p.sequence() - 1)?.is_some_and(|v| v.ready()) {
            return Err(err("EXECUTION_PREDECESSOR_UNREADY"));
        }
        if p.value()["config_hash"] != hash(&self.config) || p.value()["predecessor"] != self.sequence {
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
        let projection = &p.value()["projections"][i];
        if i==2{self.require_account_checkpoint(&projection["result"])?;}
        let typed_after=Self::validated_typed_after(p,i)?;
        let h = self.payload_digest(i)?;
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
            if self.pending.is_none() {
                self.pending = Some((p.id().into(), 0));
            }
            if let Some(after)=typed_after.filter(|_|i<5) {
                self.invalidate_payloads();
                match i {
                    0=>self.order=after.order.clone(),
                    1=>self.position=after.position.clone(),
                    2=>self.account=after.account.clone(),
                    3=>self.ledger=after.ledger.clone(),
                    4=>self.risk=after.risk.clone(),
                    _=>return Err(err("EXECUTION_PROJECTION_INDEX")),
                }
            } else if matches!(i, 2 | 3) {
                // The actual owning before-hash was proved above. Extend
                // only that exact reconstructed journal; arbitrary cold
                // Components::restore still uses install_payload.
                let bytes = serde_json::to_vec(&projection["result"])?;
                let fingerprint = text(&projection["result_hash"])?;
                self.invalidate_payloads();
                #[cfg(test)]
                PROJECTION_RESTORES.with(|count| {
                    let mut counts = count.get();
                    counts[i] += 1;
                    count.set(counts);
                });
                if i == 2 {
                    boundary(self.account.restore_exact_extension(&bytes, fingerprint))?;
                } else {
                    boundary(self.ledger.restore_exact_extension(&bytes, fingerprint))?;
                }
            } else { self.install_payload(i, &projection["result"])?; }
        }
        if i == 5 {
            self.validate_valuation_metadata(&self.meta)?;
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
            || p.value()["predecessor"] != self.sequence
        {
            return Err(err("EXECUTION_INCOMPLETE"));
        }
        for (i, fingerprint) in self.payload_hashes()?.iter().enumerate() {
            if p.value()["projections"][i]["result_hash"] != *fingerprint {
                return Err(err("EXECUTION_COMPLETION_RESULT_CONFLICT"));
            }
        }
        self.validate_valuation_metadata(&self.meta)?;
        self.sequence = p.sequence();
        self.pending = None;
        Ok(())
    }
}

pub(crate) fn settlement_config(config: &Value) -> Value {
    let mut value = json!({"currency":config["currency"]});
    for key in [
        "engine",
        "runtime",
        "account",
        "gateway",
        "generation",
        "runtime_kind",
    ] {
        value[key] = config[key].clone();
    }
    value
}

#[cfg(test)]
#[path="payload_codec_tests.rs"]
mod payload_codec_tests;

#[cfg(test)]
#[path="position_order_view_tests.rs"]
mod position_order_view_tests;

#[cfg(test)]
#[path="prefix_read_tests.rs"]
mod prefix_read_tests;
