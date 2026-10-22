//! Current sealed-history reader. Historical facts do not require an executable
//! Source; new provider work still goes through strict Resolver::resolve.
use super::*;
use crate::{
    integration_configuration::Lifecycle,
    integration_postgres::Snapshot,
    market_data::{CoverageStatus, Scope, Storage, plan_bar_window},
    source_access::{Permission, Reference, Selection, Session},
};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    calendar::OnlyTradingCalendar,
    market::{OnlyBar, OnlyBarSemantic},
};
use onlyalpha_integration_contract::source::{MarketIdentity, Resource};
use onlyalpha_market_data_construction::{
    OnlyConstructionCapability, OnlyConstructionIdentity, OnlyConstructionRequirement,
    OnlyConstructionResolutionPlan,
};
use serde_json::json;
use std::sync::Arc;
/// Opaque original context, issued only after owning Revision/Scope relations.
pub struct HistoryContext {
    pub(super) selection: Selection,
    pub(super) identity: MarketIdentity,
    pub(super) calendar: Arc<OnlyTradingCalendar>,
    pub(super) plan: OnlyConstructionResolutionPlan,
    pub(super) base: Scope,
    pub(super) implementation: Option<String>,
    pub(super) resource: Option<Arc<dyn Resource>>,
}
impl HistoryContext {
    pub fn selection(&self) -> &Selection {
        &self.selection
    }
    pub fn calendar(&self) -> &OnlyTradingCalendar {
        &self.calendar
    }
    pub fn plan(&self) -> &OnlyConstructionResolutionPlan {
        &self.plan
    }
    pub(super) fn current(
        r: &Resolved,
        instrument: &str,
        target: &OnlyBarSemantic,
    ) -> Result<Self> {
        let plan = queries::plan(r, instrument, target)?;
        let base = if plan.recipe().is_native() {
            plan.clone()
        } else {
            queries::plan(r, instrument, &queries::semantic(1)?)?
        };
        Ok(Self {
            selection: r.selection.clone(),
            identity: r.identity().clone(),
            calendar: Arc::new(r.resource.calendar().clone()),
            plan,
            base: queries::scope(r, instrument, 0, 1, &base)?,
            implementation: Some(r.implementation.clone()),
            resource: Some(Arc::clone(&r.resource)),
        })
    }
    /// Identity/calendar are explicit pure plugin witnesses. Accept only their
    /// exact match with the original verified descriptor/config and sealed plan.
    // Keep independently checked selection, plugin witnesses and requested
    // subject explicit; bundling them only for this lint would add no invariant.
    #[allow(clippy::too_many_arguments)]
    pub async fn select(
        snapshot: &Snapshot,
        reference: &Reference,
        session: &Session,
        store: &mut Storage<'_>,
        identity: MarketIdentity,
        calendar: OnlyTradingCalendar,
        instrument: &str,
        target: &OnlyBarSemantic,
    ) -> Result<Self> {
        let selection = original_selection(snapshot, reference, session, &identity)?;
        let id: onlyalpha_domain::identifiers::OnlyInstrumentId =
            instrument.parse().map_err(|_| Error::Invalid)?;
        if id.venue().value() != identity.venue {
            return Err(Error::Selection);
        }
        let families = store
            .catalog()
            .history_families(&identity.source_id, Some(instrument), reference.revision())
            .await?;
        let exact: Vec<_> = families
            .iter()
            .filter(|f| {
                f.to_record()["bar_construction"]["plan"]["target_semantic"] == target.to_record()
            })
            .collect();
        let base_semantic = queries::semantic(1)?.to_record();
        let candidates = if exact.is_empty() {
            families
                .iter()
                .filter(|f| {
                    f.to_record()["bar_construction"]["plan"]["target_semantic"] == base_semantic
                })
                .collect::<Vec<_>>()
        } else {
            exact
        };
        if candidates.len() != 1 {
            return Err(Error::Store(market_data::Error::Unprovable));
        }
        let base = candidates[0].clone();
        let raw = base.to_record();
        let original = OnlyConstructionIdentity::from_record(&raw["bar_construction"])
            .map_err(|_| Error::Corrupt)?;
        let pin = fp(&calendar.to_record())?;
        if raw["market"] != identity.market
            || !original.plan().recipe().is_native()
            || original.plan().context().calendar_fingerprint() != pin
        {
            return Err(Error::Store(market_data::Error::Unprovable));
        }
        let capability = OnlyConstructionCapability::new(
            original.plan().target().clone(),
            true,
            true,
            &pin,
            Some(original.plan().grid_origin().clone()),
        )
        .map_err(|_| Error::Corrupt)?;
        let plan = OnlyConstructionResolutionPlan::resolve(
            target.clone(),
            &[capability],
            original.plan().context().clone(),
            OnlyConstructionRequirement::PreferExactNative,
        )
        .map_err(|_| Error::Selection)?;
        session.require_selection(&selection, Permission::ClosedHistory)?;
        Ok(Self {
            selection,
            identity,
            calendar: Arc::new(calendar),
            plan,
            base,
            implementation: None,
            resource: None,
        })
    }
}
impl Application {
    pub async fn history_window(
        &self,
        context: &HistoryContext,
        session: &Session,
        store: &mut Storage<'_>,
        request: &WindowRequest,
    ) -> Result<Authorized<Value>> {
        session.require_selection(&context.selection, Permission::ClosedHistory)?;
        let p = &context.plan;
        if request.instrument_id != p.context().instrument().to_string()
            || request.semantic != *p.target()
        {
            return Err(Error::Selection);
        }
        let window = plan_bar_window(
            &request.semantic,
            request.before_ns,
            request.clock_ns.div_euclid(60_000_000_000) * 60_000_000_000,
            request.bar_count,
            2000,
        )?;
        let start = window.intervals.first().ok_or(Error::Invalid)?.0;
        let end = window.intervals.last().ok_or(Error::Invalid)?.1;
        let family = context.base.with_range(start, end)?;
        let verified = store.read_range(&family, &window.intervals).await?;
        let complete = verified.coverage_status == CoverageStatus::Complete;
        let mut bars = vec![];
        let mut cursor = None;
        if complete {
            cursor = verified
                .facts
                .iter()
                .map(|f| {
                    f["canonical_payload"]["source_sequence"]
                        .as_i64()
                        .ok_or(Error::Corrupt)
                })
                .collect::<Result<Vec<_>>>()?
                .into_iter()
                .max()
                .map(|n| n.to_string());
            let native = verified
                .facts
                .iter()
                .map(|f| {
                    OnlyBar::from_record(&f["canonical_payload"]["payload"]["value"])
                        .map_err(|_| Error::Corrupt)
                })
                .collect::<Result<Vec<_>>>()?;
            for bar in queries::derived_with_calendar(
                &context.calendar,
                p,
                &request.instrument_id,
                native,
            )? {
                if window
                    .intervals
                    .contains(&(ns(*bar.bar_start())?, ns(*bar.bar_end())?))
                {
                    bars.push(queries::bar_row(&bar)?);
                }
            }
            if bars.len() != request.bar_count || cursor.is_none() {
                return Err(Error::Corrupt);
            }
        }
        let source = queries::selection_value(&context.selection);
        let history = if complete {
            Some(fp(
                &json!({"source_selection":source,"bar_semantic":request.semantic.to_record(),"resolution_plan_fingerprint":p.fingerprint(),"revision_evidence":verified.evidence,"resolved_start_ns":start,"resolved_end_ns":end,"anchor_kind":if request.before_ns.is_some(){"BEFORE_TIME"}else{"LATEST_CLOSED"},"requested_before_ns":request.before_ns,"requested_bar_count":request.bar_count}),
            )?)
        } else {
            None
        };
        let derived = if !p.recipe().is_native() && complete {
            Some(fp(
                &json!({"history_projection_fingerprint":history,"target_semantic":request.semantic.to_record(),"resolution_plan_fingerprint":p.fingerprint(),"resolved_start_ns":start,"resolved_end_ns":end}),
            )?)
        } else {
            None
        };
        let planned = queries::coalesce_gaps(&verified.gaps, 7 * 86_400_000_000_000)?;
        let value = json!({"schema_version":1,"source_selection":source,"instrument_id":request.instrument_id,"display_symbol":request.instrument_id.split('.').next().unwrap_or_default(),"venue":context.identity.venue,"market":context.identity.market,"bar_semantic":request.semantic.to_record(),"closed_only":true,"anchor_kind":if request.before_ns.is_some(){"BEFORE_TIME"}else{"LATEST_CLOSED"},"requested_before_ns":request.before_ns.map(|n|n.to_string()),"requested_bar_count":request.bar_count,"resolved_start_ns":start.to_string(),"resolved_end_ns":end.to_string(),"coverage":{"status":verified.coverage_status.as_str(),"manifest_id":null,"manifest_fingerprint":null,"expected_bar_count":request.bar_count,"actual_bar_count":verified.complete_interval_count,"issues":verified.issues,"gaps":verified.gaps.iter().map(queries::gap_wire).collect::<Result<Vec<_>>>()?,"planned_acquisition_ranges":planned.iter().map(queries::gap_wire).collect::<Result<Vec<_>>>()?},"bars":bars,"revision_evidence":verified.evidence.iter().map(queries::evidence_wire).collect::<Result<Vec<_>>>()?,"history_projection_fingerprint":history,"derived_projection_fingerprint":derived,"aggregation_semantics_version":if p.recipe().is_native(){None}else{Some("TIME_BAR@1")},"calendar_fingerprint":p.context().calendar_fingerprint(),"resolution_mode":if p.recipe().is_native(){"PROVIDER_NATIVE"}else{"DERIVED"},"resolution_plan_fingerprint":p.fingerprint(),"resume_after_sequence":cursor,"resume_plan_fingerprint":if complete{Some(p.fingerprint())}else{None}});
        Authorized::history(value, session, context)
    }
    pub async fn historical_latest(
        &self,
        context: &HistoryContext,
        session: &Session,
        store: &mut Storage<'_>,
        clock_ns: i64,
    ) -> Result<Authorized<Value>> {
        session.require_selection(&context.selection, Permission::ClosedHistory)?;
        let (_, facts) = match store.read_latest(&context.base).await {
            Ok(v) => v,
            Err(market_data::Error::NotFound) => {
                return Err(Error::Store(market_data::Error::Unprovable));
            }
            Err(e) => return Err(e.into()),
        };
        let mut end = 0;
        for fact in facts {
            let b = OnlyBar::from_record(&fact["canonical_payload"]["payload"]["value"])
                .map_err(|_| Error::Corrupt)?;
            end = end.max(ns(*b.bar_end())?);
        }
        let stride = context
            .plan
            .target()
            .stride_minutes()
            .map_err(|_| Error::Invalid)?
            .to_string()
            .parse::<i64>()
            .map_err(|_| Error::Invalid)?
            .checked_mul(60_000_000_000)
            .ok_or(Error::Invalid)?;
        let origin = context
            .plan
            .grid_origin()
            .to_string()
            .parse::<i128>()
            .map_err(|_| Error::Invalid)?;
        let value = i128::from(end.min(clock_ns));
        let width = i128::from(stride);
        let base = origin;
        end = i64::try_from(
            value
                .checked_sub(base)
                .ok_or(Error::Invalid)?
                .div_euclid(width)
                .checked_mul(width)
                .and_then(|n| n.checked_add(base))
                .ok_or(Error::Invalid)?,
        )
        .map_err(|_| Error::Invalid)?;
        self.history_window(
            context,
            session,
            store,
            &WindowRequest {
                instrument_id: context.plan.context().instrument().to_string(),
                semantic: context.plan.target().clone(),
                before_ns: Some(end),
                bar_count: 1,
                clock_ns,
            },
        )
        .await
    }
}
/// The original declared Source relation, independent of installed code.
pub(super) fn original_selection(
    snapshot: &Snapshot,
    reference: &Reference,
    session: &Session,
    identity: &MarketIdentity,
) -> Result<Selection> {
    session.require_reference(reference, Permission::ClosedHistory)?;
    let owner = snapshot.integration().record();
    if owner.integration_id.value() != reference.integration_id()
        || owner.lifecycle != Lifecycle::Active
    {
        return Err(Error::Selection);
    }
    let (revision, _) = snapshot
        .history()
        .iter()
        .find(|(r, _)| r.record().revision_fingerprint == reference.revision())
        .ok_or(Error::Selection)?;
    let r = revision.record();
    if r.integration_id != owner.integration_id
        || r.type_id != owner.type_id
        || reference
            .expected_type_id()
            .is_some_and(|t| t != r.type_id.value())
    {
        return Err(Error::Corrupt);
    }
    let descriptor = onlyalpha_integration_contract::Descriptor::from_json(
        r.type_descriptor_document.raw().get(),
        64 * 1024 * 1024,
    )
    .map_err(|_| Error::Corrupt)?;
    let document: Value =
        serde_json::from_str(descriptor.document().get()).map_err(|_| Error::Corrupt)?;
    if descriptor.fingerprint() != r.type_descriptor_fingerprint
        || document["provider_id"] != identity.provider
        || descriptor.category() != onlyalpha_integration_contract::Category::DataSource
    {
        return Err(Error::Corrupt);
    }
    let selection = Selection::new(
        Reference::new(
            reference.integration_id(),
            reference.revision(),
            Some(r.type_id.value()),
        )?,
        &identity.source_id,
        &identity.environment,
    )?;
    session.require_selection(&selection, Permission::ClosedHistory)?;
    Ok(selection)
}
impl Application {
    /// Observation metadata comes only from physically verified retained bars.
    /// Missing reference fields remain explicitly UNKNOWN; no current provider runs.
    // These independent authority/resource/query inputs are the current boundary.
    #[allow(clippy::too_many_arguments)]
    pub async fn historical_instruments(
        &self,
        snapshot: &Snapshot,
        reference: &Reference,
        session: &Session,
        store: &mut Storage<'_>,
        identity: MarketIdentity,
        calendar: OnlyTradingCalendar,
        query: &super::InstrumentQuery,
    ) -> Result<super::AuthorizedBatch> {
        let selection = original_selection(snapshot, reference, session, &identity)?;
        if query.limit == 0
            || query.limit > 100
            || query.query.len() > 256
            || query.instrument_ids.len() > 100
        {
            return Err(Error::Invalid);
        }
        let families = store
            .catalog()
            .history_families(&identity.source_id, None, reference.revision())
            .await?;
        let mut contexts = std::collections::BTreeMap::new();
        for scope in families {
            let raw = scope.to_record();
            let id = raw["instrument_id"].as_str().ok_or(Error::Corrupt)?;
            if (!query.instrument_ids.is_empty() && !query.instrument_ids.iter().any(|v| v == id))
                || !id
                    .to_ascii_lowercase()
                    .contains(&query.query.to_ascii_lowercase())
            {
                continue;
            }
            let construction = OnlyConstructionIdentity::from_record(&raw["bar_construction"])
                .map_err(|_| Error::Corrupt)?;
            contexts
                .entry(id.to_owned())
                .or_insert_with(|| construction.plan().target().clone());
        }
        if contexts.len() > query.limit {
            contexts = contexts.into_iter().take(query.limit).collect();
        }
        let mut rows = vec![];
        for (id, semantic) in contexts {
            let context = HistoryContext::select(
                snapshot,
                reference,
                session,
                store,
                identity.clone(),
                calendar.clone(),
                &id,
                &semantic,
            )
            .await?;
            let window = self
                .historical_latest(&context, session, store, i64::MAX)
                .await?
                .into_parts()?
                .0;
            let bars = window["bars"].as_array().ok_or(Error::Corrupt)?;
            if bars.len() != 1 {
                return Err(Error::Store(market_data::Error::Unprovable));
            }
            let instrument: onlyalpha_domain::identifiers::OnlyInstrumentId =
                id.parse().map_err(|_| Error::Corrupt)?;
            rows.push(json!({"instrument_id":id,"display_symbol":instrument.symbol().value(),"venue":instrument.venue().value(),"market":identity.market,"asset_class":"UNKNOWN","instrument_type":"UNKNOWN","status":"HISTORICAL_ONLY","market_data_capabilities":["HISTORICAL_BARS"]}));
        }
        super::queries::AuthorizedBatch::new(
            json!({"schema_version":1,"source_selection":queries::selection_value(&selection),"instruments":rows}),
            session,
            vec![(selection, Permission::ClosedHistory)],
        )
    }
}
