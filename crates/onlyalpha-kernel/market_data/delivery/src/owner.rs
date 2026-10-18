use crate::{OnlyDeliveryError, OnlyDeliveryResult, record::*, subscription::*};
use num_bigint::BigInt;
use onlyalpha_domain::{
    identifiers::{OnlyClusterId, OnlyIdentifier},
    time::OnlyTimestamp,
};
use onlyalpha_market_data_state::{OnlyMarketDataSnapshot, OnlyMarketDataStateScope};
use serde_json::{Value, json};
use std::collections::BTreeMap;
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyBarDeliveryPlan {
    subscription: OnlyIdentifier,
    snapshot: OnlyMarketDataSnapshot,
}
impl OnlyBarDeliveryPlan {
    pub fn cluster_id(&self) -> &OnlyClusterId {
        self.snapshot.cluster_id().expect("scoped plan")
    }
    pub fn subscription_id(&self) -> &OnlyIdentifier {
        &self.subscription
    }
    pub fn snapshot(&self) -> &OnlyMarketDataSnapshot {
        &self.snapshot
    }
}
struct Entry {
    subscription: OnlyBarSubscription,
    last: Option<OnlyTimestamp>,
}
/// Owns planning cursors, not actual execution or an external readiness decision.
pub struct OnlyMarketDataDelivery {
    scope: OnlyMarketDataStateScope,
    entries: BTreeMap<OnlyClusterId, Entry>,
}
impl OnlyMarketDataDelivery {
    pub fn new(scope: OnlyMarketDataStateScope) -> Self {
        Self {
            scope,
            entries: BTreeMap::new(),
        }
    }
    pub fn scope(&self) -> &OnlyMarketDataStateScope {
        &self.scope
    }
    pub fn subscription_count(&self) -> usize {
        self.entries.len()
    }
    pub fn register(
        &mut self,
        cluster: OnlyClusterId,
        subscription: OnlyBarSubscription,
    ) -> OnlyDeliveryResult<()> {
        if self.entries.contains_key(&cluster)
            || self
                .entries
                .values()
                .any(|entry| entry.subscription.id() == subscription.id())
        {
            return Err(OnlyDeliveryError::Configuration);
        }
        self.entries.insert(
            cluster,
            Entry {
                subscription,
                last: None,
            },
        );
        Ok(())
    }
    pub fn unregister(&mut self, cluster: &OnlyClusterId) -> OnlyDeliveryResult<()> {
        if self.entries.remove(cluster).is_none() {
            return Err(OnlyDeliveryError::Configuration);
        }
        Ok(())
    }
    pub fn route(
        &mut self,
        snapshot: &OnlyMarketDataSnapshot,
    ) -> OnlyDeliveryResult<Vec<OnlyBarDeliveryPlan>> {
        if snapshot.scope() != &self.scope || snapshot.cluster_id().is_some() {
            return Err(OnlyDeliveryError::Scope);
        }
        let updated = snapshot.updated_bar_types();
        let mut plans = vec![];
        for (cluster, entry) in &self.entries {
            let sub = &entry.subscription;
            if !updated.contains(sub.primary()) {
                continue;
            }
            if entry
                .last
                .as_ref()
                .is_some_and(|last| last >= snapshot.ts_event())
            {
                return Err(OnlyDeliveryError::Sequence);
            }
            let view = snapshot
                .restrict(cluster.clone(), sub.bar_types(), sub.primary())
                .map_err(invalid)?;
            if sub.freshness() == OnlyBarFreshness::SameEventTime {
                for kind in sub.bar_types() {
                    view.require_same_event_time(kind)
                        .map_err(|_| OnlyDeliveryError::Freshness)?;
                }
            }
            plans.push(OnlyBarDeliveryPlan {
                subscription: sub.id().clone(),
                snapshot: view,
            });
        }
        // All views/cursors validate first; this phase contains no user callbacks.
        for plan in &plans {
            self.entries
                .get_mut(plan.cluster_id())
                .expect("registered plan")
                .last = Some(snapshot.ts_event().clone());
        }
        Ok(plans)
    }
    pub fn capture_checkpoint(&self) -> Value {
        json!({"schema_version":1,"engine_id":self.scope.engine_id().value(),"runtime_id":self.scope.runtime_id().value(),"registrations":self.entries.iter().map(|(cluster,entry)|json!({"cluster_id":cluster.value(),"subscription":entry.subscription.to_record(),"last_planned_event_ns":entry.last.as_ref().map(|time|serde_json::from_str::<Value>(&time.unix_nanos().to_string()).expect("integer spelling"))})).collect::<Vec<_>>()})
    }
    pub fn restore_checkpoint(&mut self, value: &Value) -> OnlyDeliveryResult<()> {
        let row = object(
            value,
            &["schema_version", "engine_id", "runtime_id", "registrations"],
        )?;
        if text(&row["engine_id"])? != self.scope.engine_id().value()
            || text(&row["runtime_id"])? != self.scope.runtime_id().value()
        {
            return Err(OnlyDeliveryError::Scope);
        }
        let mut staged = BTreeMap::new();
        for raw in array(&row["registrations"])? {
            let entry = fields(
                raw,
                &["cluster_id", "subscription", "last_planned_event_ns"],
            )?;
            let id = text(&entry["cluster_id"])?;
            let cluster: OnlyClusterId = id.parse().map_err(invalid)?;
            if cluster.value() != id {
                return Err(OnlyDeliveryError::Scope);
            }
            let subscription = OnlyBarSubscription::from_record(&entry["subscription"])?;
            let expected = self.entries.get(&cluster).ok_or(OnlyDeliveryError::Scope)?;
            if subscription != expected.subscription {
                return Err(OnlyDeliveryError::Scope);
            }
            let last = if entry["last_planned_event_ns"].is_null() {
                None
            } else {
                let number = entry["last_planned_event_ns"]
                    .as_number()
                    .ok_or_else(|| invalid("INTEGER"))?;
                let nanos: BigInt = number.to_string().parse().map_err(invalid)?;
                let time = OnlyTimestamp::from_unix_nanos(nanos);
                time.to_datetime_exact().map_err(invalid)?;
                Some(time)
            };
            if staged
                .insert(cluster, Entry { subscription, last })
                .is_some()
            {
                return Err(invalid("DUPLICATE_CLUSTER"));
            }
        }
        if staged.len() != self.entries.len() {
            return Err(OnlyDeliveryError::Scope);
        }
        self.entries = staged;
        Ok(())
    }
}
