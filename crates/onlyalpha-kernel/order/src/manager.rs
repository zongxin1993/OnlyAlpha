use crate::model::*;
use num_bigint::BigInt;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::OnlyOrderStatus as Status,
    execution::{
        OnlyCancelOrderRequest, OnlyOrderFailure, OnlyOrderFill, OnlyOrderRejection,
        OnlyOrderRequest, OnlyOrderSnapshot, OnlyOrderSnapshotInput,
    },
    fee::{OnlyOrderFeeEstimate, OnlyOrderFeePolicyBinding, OnlyOrderFundingPlan},
    identifiers::{
        OnlyAccountId, OnlyClientOrderId, OnlyClusterId, OnlyEngineId, OnlyIdentifier, OnlyOrderId,
        OnlyRuntimeId, OnlyVenueOrderId,
    },
    numeric::{only_add, only_multiply},
    value::OnlyQuantity,
};
use serde_json::{Value, json};
use std::collections::BTreeMap;

#[derive(Clone, Debug)]
pub(crate) struct Entity {
    pub snapshot: OnlyOrderSnapshot,
    pub creation: Value,
    pub outcome: String,
}
#[derive(Debug)]
pub struct Manager {
    pub(crate) config: Value,
    pub(crate) orders: BTreeMap<String, Entity>,
    pub(crate) creation: Vec<String>,
    requests: BTreeMap<String, String>,
    cancels: BTreeMap<String, Value>,
    receipts: BTreeMap<(String, String), String>,
    venues: BTreeMap<(String, String), String>,
    pub(crate) journal: Vec<Value>,
    journal_bytes: usize,
    pub(crate) sequence: u64,
}
impl Manager {
    pub fn new(config: Value) -> Result<Self, Error> {
        let r = row(
            &config,
            &["engine_id", "runtime_id", "gateway_id", "generation"],
        )?;
        OnlyEngineId::new(text(r, "engine_id")?)?;
        OnlyRuntimeId::new(text(r, "runtime_id")?)?;
        OnlyIdentifier::new(text(r, "gateway_id")?)?;
        for key in ["engine_id", "runtime_id", "gateway_id"] {
            if OnlyIdentifier::new(text(r, key)?)?.value() != text(r, key)? {
                return Err(err("ORDER_NONCANONICAL_CONFIG_ID"));
            }
        }
        fingerprint(text(r, "generation")?)?;
        Ok(Self {
            config,
            orders: BTreeMap::new(),
            creation: Vec::new(),
            requests: BTreeMap::new(),
            cancels: BTreeMap::new(),
            receipts: BTreeMap::new(),
            venues: BTreeMap::new(),
            journal: Vec::new(),
            journal_bytes: 2,
            sequence: 0,
        })
    }
    pub fn get(&self, cluster: &str, order: &str) -> Result<OnlyOrderSnapshot, Error> {
        let entity = self
            .orders
            .get(order)
            .ok_or_else(|| err("ORDER_NOT_FOUND"))?;
        if entity.snapshot.cluster_id().value() != cluster {
            return Err(err("ORDER_SCOPE_MISMATCH"));
        }
        Ok(entity.snapshot.clone())
    }
    pub fn submission(&self, cluster: &str, order: &str) -> Result<&str, Error> {
        self.get(cluster, order)?;
        Ok(&self.orders[order].outcome)
    }
    pub fn open(&self, cluster: &str) -> Vec<OnlyOrderSnapshot> {
        self.creation
            .iter()
            .filter_map(|id| self.orders.get(id))
            .filter(|e| e.snapshot.cluster_id().value() == cluster && is_open(*e.snapshot.status()))
            .map(|e| e.snapshot.clone())
            .collect()
    }
    pub fn recent(&self, cluster: &str, limit: usize) -> Result<Vec<OnlyOrderSnapshot>, Error> {
        if limit == 0 || limit > MAX_ORDERS {
            return Err(err("ORDER_QUERY_BOUND"));
        }
        Ok(self
            .creation
            .iter()
            .rev()
            .filter_map(|id| self.orders.get(id))
            .filter(|e| e.snapshot.cluster_id().value() == cluster)
            .take(limit)
            .map(|e| e.snapshot.clone())
            .collect())
    }
    pub fn find_by_client(
        &self,
        cluster: &str,
        client: &str,
    ) -> Result<Option<OnlyOrderSnapshot>, Error> {
        match self
            .orders
            .values()
            .find(|e| e.snapshot.client_order_id().value() == client)
        {
            Some(e) => self.get(cluster, e.snapshot.order_id().value()).map(Some),
            None => Ok(None),
        }
    }
    pub fn executable_remaining(&self, cluster: &str, order: &str) -> Result<OnlyQuantity, Error> {
        let s = self.get(cluster, order)?;
        if is_open(*s.status()) {
            Ok(s.remaining_quantity().clone())
        } else {
            Ok(OnlyQuantity::new("0".parse()?, s.quantity().precision())?)
        }
    }
    pub fn apply(&mut self, value: &Value) -> Result<Outcome, Error> {
        let size = value.to_string().len();
        if size > MAX_COMMAND_BYTES {
            return Err(err("ORDER_COMMAND_BOUND"));
        }
        let object = value
            .as_object()
            .ok_or_else(|| err("ORDER_RECORD_REQUIRED"))?;
        let op = text(object, "op")?;
        if op == "CREATE" {
            return self.create_order(value, size);
        }
        let extra: &[&str] = match op {
            "FEE" => &["contract"],
            "BEGIN_SUBMIT" | "RECONCILE" => &[],
            "SUBMIT_RESULT" => &["outcome"],
            "CANCEL" => &["request"],
            "FAIL" => &["failure"],
            "ACCEPT" => &[
                "runtime_id",
                "gateway_id",
                "generation",
                "account_id",
                "event_at",
                "event_id",
                "sequence",
                "venue_order_id",
            ],
            "FILL" => &[
                "runtime_id",
                "gateway_id",
                "generation",
                "account_id",
                "event_at",
                "event_id",
                "sequence",
                "fill",
            ],
            "CANCELLED" | "EXPIRED" => &[
                "runtime_id",
                "gateway_id",
                "generation",
                "account_id",
                "event_at",
                "event_id",
                "sequence",
            ],
            "REJECTED" => &[
                "runtime_id",
                "gateway_id",
                "generation",
                "account_id",
                "event_at",
                "event_id",
                "sequence",
                "rejection",
            ],
            "FAILED" => &[
                "runtime_id",
                "gateway_id",
                "generation",
                "account_id",
                "event_at",
                "event_id",
                "sequence",
                "failure",
            ],
            _ => return Err(err("ORDER_OPERATION_UNKNOWN")),
        };
        let mut fields = vec!["op", "cluster_id", "order_id", "at"];
        fields.extend(extra);
        let r = row(value, &fields)?;
        let cluster = text(r, "cluster_id")?;
        let id = text(r, "order_id")?;
        let before = self.get(cluster, id)?;
        let at = time(r, "at")?;
        let mut entity = self.orders[id].clone();
        let mut s = before.input();
        let mut receipt_keys = Vec::new();
        let mut venue = None;
        let mut cancel_identity = None;
        let external = matches!(
            op,
            "ACCEPT" | "FILL" | "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED"
        );
        let mut external_sequence = None;
        let unchanged = |result| Ok(Outcome::unchanged(result, Some(before.clone())));
        if external {
            for key in ["runtime_id", "gateway_id", "generation"] {
                if r[key] != self.config[key] {
                    return Err(err("ORDER_EXTERNAL_CONTEXT_MISMATCH"));
                }
            }
            if text(r, "account_id")? != s.account_id.value() {
                return Err(err("ORDER_ACCOUNT_SCOPE_MISMATCH"));
            }
            let event_time = time(r, "event_at")?;
            if at < event_time || event_time < s.created_at {
                return Err(err("ORDER_EXTERNAL_TIME_INVALID"));
            }
            let event = text(r, "event_id")?;
            if OnlyIdentifier::new(event)?.value() != event {
                return Err(err("ORDER_NONCANONICAL_EVENT_ID"));
            }
            if !r["sequence"].is_null() {
                let seq = integer(&r["sequence"])?;
                if seq < BigInt::from(0) {
                    return Err(err("ORDER_SEQUENCE_INVALID"));
                }
                external_sequence = Some(seq);
            }
            receipt_keys.push((s.account_id.to_string(), format!("EVENT:{event}")));
            if op == "ACCEPT" {
                venue = Some(OnlyVenueOrderId::new(text(r, "venue_order_id")?)?);
            }
            if op == "FILL" {
                let f = OnlyOrderFill::from_record(&r["fill"])?;
                if f.to_record() != r["fill"]
                    || f.order_id() != &s.order_id
                    || f.ts_event() != &event_time
                    || f.ts_init() != &at
                    || f.external_sequence() != &external_sequence
                    || f.external_event_id().as_deref() != Some(event)
                {
                    return Err(err("ORDER_FILL_ENVELOPE_MISMATCH"));
                }
                decimal_bound(f.price().value())?;
                decimal_bound(f.quantity().value())?;
                venue = f.venue_order_id().clone();
                receipt_keys.push((s.account_id.to_string(), format!("TRADE:{}", f.trade_id())));
                if let Some(t) = f.venue_trade_id() {
                    receipt_keys.push((s.account_id.to_string(), format!("VENUE_TRADE:{t}")));
                }
            }
            let fp = hash(value);
            let mut matched = false;
            for key in &receipt_keys {
                if let Some(old) = self.receipts.get(key) {
                    if old != &fp {
                        return unchanged(ApplyResult::Conflict);
                    }
                    matched = true;
                }
            }
            if matched {
                return unchanged(ApplyResult::Duplicate);
            }
            if let Some(v) = &venue
                && (s.venue_order_id.as_ref().is_some_and(|old| old != v)
                    || self
                        .venues
                        .get(&(s.account_id.to_string(), v.to_string()))
                        .is_some_and(|owner| owner != id))
            {
                return unchanged(ApplyResult::Conflict);
            }
            if let (Some(previous), Some(incoming)) =
                (&s.last_external_sequence, &external_sequence)
            {
                if incoming < previous {
                    return unchanged(ApplyResult::Stale);
                }
                if incoming == previous {
                    return unchanged(ApplyResult::Conflict);
                }
            }
            if matches!(entity.outcome.as_str(), "NOT_DISPATCHED" | "SUPPRESSED") {
                return unchanged(ApplyResult::Invalid);
            }
        }
        match op {
            "FEE" => {
                let c = row(&r["contract"], &["binding", "estimate", "funding"])?;
                fee_amount_bounds(&r["contract"])?;
                let binding = OnlyOrderFeePolicyBinding::from_record(&c["binding"])?;
                let estimate = OnlyOrderFeeEstimate::from_record(&c["estimate"])?;
                let funding = OnlyOrderFundingPlan::from_record(&c["funding"])?;
                if s.status != Status::Created || entity.outcome != "NOT_DISPATCHED" {
                    return unchanged(ApplyResult::Invalid);
                }
                if s.fee_policy_binding.is_some() {
                    return unchanged(
                        if s.fee_policy_binding.as_ref() == Some(&binding)
                            && s.fee_estimate.as_ref() == Some(&estimate)
                            && s.funding_plan.as_ref() == Some(&funding)
                        {
                            ApplyResult::Duplicate
                        } else {
                            ApplyResult::Conflict
                        },
                    );
                }
                if binding.bound_at() < &s.created_at || binding.bound_at() > &at {
                    return Err(err("ORDER_FEE_TIME_INVALID"));
                }
                s.fee_policy_binding = Some(binding);
                s.fee_estimate = Some(estimate);
                s.funding_plan = Some(funding);
            }
            "BEGIN_SUBMIT" => {
                if s.status != Status::Created
                    || entity.outcome != "NOT_DISPATCHED"
                    || s.fee_policy_binding.is_none()
                {
                    return unchanged(ApplyResult::Invalid);
                }
                if s.expire_time.as_ref().is_some_and(|t| t <= &at) {
                    return unchanged(ApplyResult::Invalid);
                }
                s.status = Status::Submitted;
                s.submitted_at = Some(at.clone());
                entity.outcome = "DISPATCHING".into();
            }
            "SUBMIT_RESULT" => {
                let next = text(r, "outcome")?;
                if !matches!(next, "KNOWN_RESULT" | "UNKNOWN" | "SUPPRESSED") {
                    return Err(err("ORDER_SUBMIT_OUTCOME_INVALID"));
                }
                if next == entity.outcome {
                    return unchanged(ApplyResult::Duplicate);
                }
                if !(entity.outcome == "DISPATCHING" && matches!(next, "KNOWN_RESULT" | "UNKNOWN")
                    || entity.outcome == "NOT_DISPATCHED" && next == "SUPPRESSED")
                {
                    return unchanged(ApplyResult::Invalid);
                }
                entity.outcome = next.into();
                if next == "SUPPRESSED" {
                    s.status = Status::Failed;
                    s.failed_at = Some(at.clone());
                    s.failure = Some(OnlyOrderFailure::from_record(
                        &json!({"schema_version":1,"code":"SUBMISSION_SUPPRESSED","message":"explicitly not dispatched"}),
                    )?);
                }
            }
            "RECONCILE" => {
                if entity.outcome == "RECONCILING" {
                    return unchanged(ApplyResult::Duplicate);
                }
                if entity.outcome != "UNKNOWN" {
                    return unchanged(ApplyResult::Invalid);
                }
                entity.outcome = "RECONCILING".into();
            }
            "CANCEL" => {
                let request = OnlyCancelOrderRequest::from_record(&r["request"])?;
                if request.to_record() != r["request"] || request.order_id() != &s.order_id {
                    return Err(err("ORDER_CANCEL_SCOPE_MISMATCH"));
                }
                let identity = json!({"cluster_id":cluster,"request":request.to_record()});
                if let Some(previous) = self.cancels.get(request.request_id().value()) {
                    return unchanged(if previous == &identity {
                        ApplyResult::Duplicate
                    } else {
                        ApplyResult::Conflict
                    });
                }
                if s.status == Status::PendingCancel {
                    // Pending state proves the original request, not this unseen request's occurrence.
                    return unchanged(ApplyResult::Invalid);
                }
                if !matches!(
                    s.status,
                    Status::Submitted | Status::Accepted | Status::PartiallyFilled
                ) {
                    return unchanged(ApplyResult::Invalid);
                }
                s.status = Status::PendingCancel;
                s.cancel_requested_at = Some(at.clone());
                cancel_identity = Some((request.request_id().to_string(), identity));
            }
            "FAIL" => {
                let failure = OnlyOrderFailure::from_record(&r["failure"])?;
                if s.status != Status::Created || entity.outcome != "NOT_DISPATCHED" {
                    return unchanged(ApplyResult::Invalid);
                }
                s.status = Status::Failed;
                s.failed_at = Some(at.clone());
                s.failure = Some(failure);
                entity.outcome = "SUPPRESSED".into();
            }
            "ACCEPT" => {
                if !matches!(
                    s.status,
                    Status::Submitted
                        | Status::Accepted
                        | Status::PartiallyFilled
                        | Status::PendingCancel
                        | Status::Filled
                        | Status::Cancelled
                ) {
                    return unchanged(ApplyResult::Invalid);
                }
                if s.status != Status::Submitted && s.venue_order_id == venue {
                    return unchanged(ApplyResult::Duplicate);
                }
                if s.status == Status::Submitted {
                    s.status = Status::Accepted;
                    s.accepted_at = Some(at.clone());
                }
            }
            "FILL" => {
                if !matches!(
                    s.status,
                    Status::Submitted
                        | Status::Accepted
                        | Status::PartiallyFilled
                        | Status::PendingCancel
                ) {
                    return unchanged(ApplyResult::Invalid);
                }
                let f = OnlyOrderFill::from_record(&r["fill"])?;
                if f.quantity().precision() != s.quantity.precision() {
                    return unchanged(ApplyResult::Invalid);
                }
                let filled = s.filled_quantity.checked_add(f.quantity())?;
                if filled.value() > s.quantity.value() {
                    return unchanged(ApplyResult::Invalid);
                }
                let total = only_add(
                    &s.cumulative_price_quantity,
                    &only_multiply(f.price().value(), f.quantity().value())?,
                )?;
                decimal_bound(&total)?;
                let precision = f
                    .price()
                    .precision()
                    .max(s.price.as_ref().map_or(0, |p| p.precision()))
                    .max(s.average_fill_price.as_ref().map_or(0, |p| p.precision()));
                s.average_fill_price = Some(average(&total, filled.value(), precision)?);
                s.cumulative_price_quantity = total;
                s.filled_quantity = filled;
                s.remaining_quantity = s.quantity.checked_subtract(&s.filled_quantity)?;
                s.fill_count += 1;
                s.last_trade_id = Some(f.trade_id().clone());
                if s.remaining_quantity.value().is_zero() {
                    s.status = Status::Filled;
                    s.filled_at = Some(time(r, "event_at")?);
                } else if s.status != Status::PendingCancel {
                    s.status = Status::PartiallyFilled;
                }
            }
            "CANCELLED" | "REJECTED" | "EXPIRED" | "FAILED" => {
                let target = match op {
                    "CANCELLED" => Status::Cancelled,
                    "REJECTED" => Status::Rejected,
                    "EXPIRED" => Status::Expired,
                    _ => Status::Failed,
                };
                // Parse payload even for terminal/no-op observations; malformed proof cannot certify a duplicate.
                let rejection = if op == "REJECTED" {
                    Some(OnlyOrderRejection::from_record(&r["rejection"])?)
                } else {
                    None
                };
                let failure = if op == "FAILED" {
                    Some(OnlyOrderFailure::from_record(&r["failure"])?)
                } else {
                    None
                };
                if s.status == target {
                    return unchanged(
                        if (op == "REJECTED" && s.rejection != rejection)
                            || (op == "FAILED" && s.failure != failure)
                        {
                            ApplyResult::Conflict
                        } else {
                            ApplyResult::Duplicate
                        },
                    );
                }
                if !matches!(
                    s.status,
                    Status::Submitted
                        | Status::Accepted
                        | Status::PartiallyFilled
                        | Status::PendingCancel
                ) || (op == "EXPIRED" && s.status == Status::Submitted)
                {
                    return unchanged(ApplyResult::Invalid);
                }
                s.status = target;
                match target {
                    Status::Cancelled => s.cancelled_at = Some(at.clone()),
                    Status::Rejected => {
                        s.rejected_at = Some(at.clone());
                        s.rejection = rejection;
                    }
                    Status::Expired => s.expired_at = Some(at.clone()),
                    Status::Failed => {
                        s.failed_at = Some(at.clone());
                        s.failure = failure;
                    }
                    _ => unreachable!(),
                }
            }
            _ => return Err(err("ORDER_OPERATION_UNKNOWN")),
        }
        if !external && at < s.updated_at {
            return unchanged(ApplyResult::Stale);
        }
        if let Some(v) = &venue {
            s.venue_order_id = Some(v.clone());
        }
        if external {
            if external_sequence.is_some() {
                s.last_external_sequence = external_sequence;
            }
            entity.outcome = "RESOLVED".into();
        }
        s.updated_at = s.updated_at.max(at);
        s.version += 1;
        entity.snapshot = OnlyOrderSnapshot::new(s)?;
        let result = self.prepare_result(
            op,
            &entity.snapshot,
            value,
            &entity.creation,
            &entity.outcome,
        )?;
        self.capacity(size, &entity.snapshot)?;
        // All validation, arithmetic and result construction precede the single owned commit.
        if let Some(v) = venue {
            self.venues.insert(
                (entity.snapshot.account_id().to_string(), v.to_string()),
                id.into(),
            );
        }
        if let Some((key, identity)) = cancel_identity {
            self.cancels.insert(key, identity);
        }
        for key in receipt_keys {
            self.receipts.insert(key, hash(value));
        }
        self.orders.insert(id.into(), entity);
        self.commit(value, size);
        Ok(result)
    }
    fn capacity(&self, size: usize, snapshot: &OnlyOrderSnapshot) -> Result<(), Error> {
        if self.journal.len() >= MAX_JOURNAL
            || self.journal_bytes + size + 1 > MAX_JOURNAL_BYTES
            || snapshot.to_record().to_string().len() > 65536
        {
            return Err(err("ORDER_CAPACITY_EXHAUSTED"));
        }
        Ok(())
    }
    fn commit(&mut self, value: &Value, size: usize) {
        self.journal.push(value.clone());
        self.journal_bytes += size + 1;
        self.sequence += 1;
    }
    fn prepare_result(
        &self,
        op: &str,
        snapshot: &OnlyOrderSnapshot,
        input: &Value,
        creation: &Value,
        outcome: &str,
    ) -> Result<Outcome, Error> {
        let seq = self
            .sequence
            .checked_add(1)
            .ok_or_else(|| err("ORDER_SEQUENCE_EXHAUSTED"))?;
        Ok(Outcome {
            result: ApplyResult::Applied,
            snapshot: Some(snapshot.clone()),
            fact: Some(
                json!({"schema_version":1,"sequence":seq,"op":op,"config":self.config,"input_fingerprint":hash(input),"cause":creation["cause"],"submission_outcome":outcome,"snapshot":snapshot.to_record()}),
            ),
        })
    }
    fn create_order(&mut self, value: &Value, size: usize) -> Result<Outcome, Error> {
        let r = row(
            value,
            &["op", "cluster_id", "account_id", "request", "cause", "at"],
        )?;
        let cluster = OnlyClusterId::new(text(r, "cluster_id")?)?;
        let account = OnlyAccountId::new(text(r, "account_id")?)?;
        fingerprint(text(r, "cause")?)?;
        if cluster.value() != text(r, "cluster_id")? || account.value() != text(r, "account_id")? {
            return Err(err("ORDER_NONCANONICAL_SCOPE_ID"));
        }
        let request = OnlyOrderRequest::from_record(&r["request"])?;
        if request.to_record() != r["request"]
            || request.account_id().as_ref().is_some_and(|a| a != &account)
        {
            return Err(err("ORDER_REQUEST_SCOPE_OR_RECORD_INVALID"));
        }
        decimal_bound(request.quantity().value())?;
        if let Some(price) = request.price() {
            decimal_bound(price.value())?;
        }
        let at = time(r, "at")?;
        let mut identity = value.clone();
        identity
            .as_object_mut()
            .ok_or_else(|| err("ORDER_RECORD_REQUIRED"))?
            .remove("at");
        if let Some(id) = self.requests.get(request.request_id().value()) {
            let entity = &self.orders[id];
            return Ok(Outcome::unchanged(
                if entity.creation == identity {
                    ApplyResult::Duplicate
                } else {
                    ApplyResult::Conflict
                },
                Some(entity.snapshot.clone()),
            ));
        }
        if request
            .expire_time()
            .as_ref()
            .is_some_and(|expiry| expiry <= &at)
        {
            return Err(err("ORDER_EXPIRY_INVALID"));
        }
        if self.creation.len() >= MAX_ORDERS {
            return Err(err("ORDER_CAPACITY_EXHAUSTED"));
        }
        let runtime = OnlyRuntimeId::new(
            self.config["runtime_id"]
                .as_str()
                .ok_or_else(|| err("ORDER_CONFIG_INVALID"))?,
        )?;
        let next = self.creation.len() + 1;
        let order = OnlyOrderId::new(&format!("{runtime}-ORDER-{next:06}"))?;
        let client = OnlyClientOrderId::new(&format!("{runtime}-CLIENT-{next:06}"))?;
        let q = OnlyQuantity::new("0".parse()?, request.quantity().precision())?;
        let s = OnlyOrderSnapshot::new(OnlyOrderSnapshotInput {
            order_id: order.clone(),
            request_id: request.request_id().clone(),
            client_order_id: client,
            venue_order_id: None,
            runtime_id: runtime,
            cluster_id: cluster,
            account_id: account,
            instrument_id: request.instrument_id().clone(),
            side: *request.side(),
            offset: *request.offset(),
            order_type: *request.order_type(),
            time_in_force: *request.time_in_force(),
            quantity: request.quantity().clone(),
            price: request.price().clone(),
            stop_price: request.stop_price().clone(),
            expire_time: request.expire_time().clone(),
            status: Status::Created,
            filled_quantity: q,
            remaining_quantity: request.quantity().clone(),
            average_fill_price: None,
            created_at: at.clone(),
            updated_at: at,
            submitted_at: None,
            accepted_at: None,
            cancel_requested_at: None,
            cancelled_at: None,
            filled_at: None,
            rejected_at: None,
            expired_at: None,
            failed_at: None,
            version: BigInt::from(1),
            last_external_sequence: None,
            rejection: None,
            failure: None,
            tags: request.tags().clone(),
            metadata: request.metadata().clone(),
            fill_count: BigInt::from(0),
            cumulative_price_quantity: "0".parse()?,
            last_trade_id: None,
            historical_fill_identity_missing: false,
            fee_policy_binding: None,
            fee_estimate: None,
            funding_plan: None,
            execution_intent: request.execution_intent().clone(),
        })?;
        self.capacity(size, &s)?;
        let result = self.prepare_result("CREATE", &s, value, &identity, "NOT_DISPATCHED")?;
        self.requests
            .insert(request.request_id().to_string(), order.to_string());
        self.creation.push(order.to_string());
        self.orders.insert(
            order.to_string(),
            Entity {
                snapshot: s,
                creation: identity,
                outcome: "NOT_DISPATCHED".into(),
            },
        );
        self.commit(value, size);
        Ok(result)
    }
    pub(crate) fn state_record(&self) -> Value {
        json!({"sequence":self.sequence,"receipts":self.receipts.iter().map(|((account,id),fp)|json!([account,id,fp])).collect::<Vec<_>>(),"venues":self.venues.iter().map(|((account,venue),id)|json!([account,venue,id])).collect::<Vec<_>>(),"cancels":self.cancels,"orders":self.creation.iter().map(|id|{let e=&self.orders[id];json!({"snapshot":e.snapshot.to_record(),"submission":e.outcome,"creation":e.creation})}).collect::<Vec<_>>()})
    }
}
fn is_open(status: Status) -> bool {
    matches!(
        status,
        Status::Created
            | Status::Submitted
            | Status::Accepted
            | Status::PartiallyFilled
            | Status::PendingCancel
    )
}
