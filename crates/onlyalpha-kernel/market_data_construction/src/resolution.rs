//! Explicit capability resolution and lineage values; no artifact-existence certification.
use crate::{model::*, record::*};
use num_bigint::BigInt;
use onlyalpha_domain::{
    base::OnlyDomainModel,
    enums::{OnlyAdjustmentType, OnlyPriceType},
    identifiers::OnlyInstrumentId,
    market::{
        OnlyBarFormation, OnlyBarFormationKind, OnlyBarSemantic, OnlyBarSemanticInput,
        OnlyFixedDurationBarFormation, OnlyFixedDurationBarFormationInput,
    },
};
use serde_json::{Value, json};
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum OnlyConstructionRequirement {
    PreferExactNative,
    Exact(Box<OnlyConstructionRecipe>),
}
impl OnlyConstructionRequirement {
    pub fn to_record(&self) -> Value {
        match self {
            Self::PreferExactNative => {
                json!({"schema_version":1,"kind":"POLICY","policy":"PREFER_EXACT_NATIVE","recipe":null})
            }
            Self::Exact(recipe) => {
                json!({"schema_version":1,"kind":"EXACT_RECIPE","policy":null,"recipe":recipe.to_record()})
            }
        }
    }
    pub fn from_record(v: &Value) -> OnlyConstructionResult<Self> {
        let r = object(v, 1, &["kind", "policy", "recipe"])?;
        let result = match text(&r["kind"])? {
            "POLICY" => Self::PreferExactNative,
            "EXACT_RECIPE" => {
                Self::Exact(Box::new(OnlyConstructionRecipe::from_record(&r["recipe"])?))
            }
            _ => return Err(err("REQUIREMENT_KIND")),
        };
        if result.to_record() != *v {
            return Err(err("REQUIREMENT_FIELDS"));
        }
        Ok(result)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyConstructionCapability {
    semantic: OnlyBarSemantic,
    historical: bool,
    realtime: bool,
    calendar: String,
    origin: Option<BigInt>,
}
impl OnlyConstructionCapability {
    pub fn new(
        semantic: OnlyBarSemantic,
        historical: bool,
        realtime: bool,
        calendar: &str,
        origin: Option<BigInt>,
    ) -> OnlyConstructionResult<Self> {
        nonempty(calendar)?;
        if semantic.adjustment_policy() != &OnlyAdjustmentType::Raw {
            return Err(err("CAPABILITY_ADJUSTMENT"));
        }
        Ok(Self {
            semantic,
            historical,
            realtime,
            calendar: calendar.into(),
            origin,
        })
    }
    pub fn semantic(&self) -> &OnlyBarSemantic {
        &self.semantic
    }
    fn matches(&self, semantic: &OnlyBarSemantic, calendar: &str) -> bool {
        self.semantic == *semantic
            && self.calendar == calendar
            && self.historical
            && self.realtime
            && self.origin.is_some()
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyConstructionResolutionContext {
    source: String,
    instrument: OnlyInstrumentId,
    integration: String,
    calendar: String,
}
impl OnlyConstructionResolutionContext {
    pub fn new(
        source: &str,
        instrument: OnlyInstrumentId,
        integration: &str,
        calendar: &str,
    ) -> OnlyConstructionResult<Self> {
        nonempty(source)?;
        nonempty(calendar)?;
        digest(integration)?;
        Ok(Self {
            source: source.into(),
            instrument,
            integration: integration.into(),
            calendar: calendar.into(),
        })
    }
    pub fn source(&self) -> &str {
        &self.source
    }
    pub fn instrument(&self) -> &OnlyInstrumentId {
        &self.instrument
    }
    pub fn calendar_fingerprint(&self) -> &str {
        &self.calendar
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyConstructionResolutionPlan {
    target: OnlyBarSemantic,
    requirement: OnlyConstructionRequirement,
    recipe: OnlyConstructionRecipe,
    context: OnlyConstructionResolutionContext,
    origin: BigInt,
}
pub(crate) fn positive_mod(value: BigInt, modulus: &BigInt) -> BigInt {
    let rem = value % modulus;
    if rem < BigInt::from(0) {
        rem + modulus
    } else {
        rem
    }
}
impl OnlyConstructionResolutionPlan {
    pub fn resolve(
        target: OnlyBarSemantic,
        capabilities: &[OnlyConstructionCapability],
        context: OnlyConstructionResolutionContext,
        requirement: OnlyConstructionRequirement,
    ) -> OnlyConstructionResult<Self> {
        if target.price_type() != &OnlyPriceType::Last
            || target.adjustment_policy() != &OnlyAdjustmentType::Raw
            || !target.is_fixed_duration()
            || target.window_minutes().map_err(err)? > &240.into()
        {
            return Err(err("RESOLUTION_UNSUPPORTED"));
        }
        let native: Vec<_> = capabilities
            .iter()
            .filter(|c| c.matches(&target, &context.calendar))
            .collect();
        let recipe = match &requirement {
            OnlyConstructionRequirement::Exact(recipe) => {
                if recipe.target() != &target {
                    return Err(err("REQUIREMENT_TARGET"));
                }
                recipe.as_ref().clone()
            }
            OnlyConstructionRequirement::PreferExactNative => {
                if native.len() > 1 {
                    return Err(err("RESOLUTION_AMBIGUOUS"));
                }
                if native.len() == 1 {
                    OnlyConstructionRecipe::native(target.clone())
                } else {
                    let OnlyBarFormation::FixedDuration(formation) = target.formation() else {
                        unreachable!()
                    };
                    let base = OnlyBarSemantic::new(OnlyBarSemanticInput {
                        formation: OnlyBarFormation::FixedDuration(
                            OnlyFixedDurationBarFormation::new(
                                OnlyFixedDurationBarFormationInput {
                                    window_minutes: 1.into(),
                                    stride_minutes: 1.into(),
                                    alignment: *formation.alignment(),
                                    kind: OnlyBarFormationKind::FixedDuration,
                                },
                            )
                            .map_err(err)?,
                        ),
                        price_type: *target.price_type(),
                        adjustment_policy: *target.adjustment_policy(),
                    })
                    .map_err(err)?;
                    OnlyConstructionRecipe::derived(
                        target.clone(),
                        OnlyConstructionSemantic::Bar(base),
                        if target.is_aligned() {
                            "TIME_BAR"
                        } else {
                            "ROLLING_TIME_BAR"
                        },
                        1u32.into(),
                        OnlyMissingPolicy::Reject,
                        OnlyIncompletePolicy::Drop,
                    )?
                }
            }
        };
        let base = if recipe.is_native() {
            &target
        } else {
            match recipe.base() {
                Some(OnlyConstructionSemantic::Bar(base)) => base,
                _ => return Err(err("RESOLUTION_BASE_UNAVAILABLE")),
            }
        };
        let candidates: Vec<_> = capabilities
            .iter()
            .filter(|c| c.matches(base, &context.calendar))
            .collect();
        if candidates.len() != 1 {
            return Err(err("RESOLUTION_CAPABILITY_UNAVAILABLE_OR_AMBIGUOUS"));
        }
        let stride = base.stride_minutes().map_err(err)? * 60_000_000_000i64;
        let origin = positive_mod(candidates[0].origin.clone().expect("matched"), &stride);
        Ok(Self {
            target,
            requirement,
            recipe,
            context,
            origin,
        })
    }
    pub fn recipe(&self) -> &OnlyConstructionRecipe {
        &self.recipe
    }
    pub fn target(&self) -> &OnlyBarSemantic {
        &self.target
    }
    pub fn grid_origin(&self) -> &BigInt {
        &self.origin
    }
    pub fn context(&self) -> &OnlyConstructionResolutionContext {
        &self.context
    }
    fn payload(&self) -> Value {
        json!({"schema_version":3,"target_semantic":self.target.to_record(),"requirement":self.requirement.to_record(),"resolved_recipe":self.recipe.to_record(),"source_id":self.context.source,"instrument_id":self.context.instrument.to_string(),"integration_revision_fingerprint":self.context.integration,"calendar_fingerprint":self.context.calendar,"grid_origin_ns":number(&self.origin)})
    }
    pub fn fingerprint(&self) -> String {
        hash(&self.payload())
    }
    pub fn to_record(&self) -> Value {
        let mut v = self.payload();
        v["fingerprint"] = self.fingerprint().into();
        v
    }
    pub fn from_record(v: &Value) -> OnlyConstructionResult<Self> {
        let row = object(
            v,
            3,
            &[
                "target_semantic",
                "requirement",
                "resolved_recipe",
                "source_id",
                "instrument_id",
                "integration_revision_fingerprint",
                "calendar_fingerprint",
                "grid_origin_ns",
                "fingerprint",
            ],
        )?;
        let result = Self {
            target: domain(&row["target_semantic"])?,
            requirement: OnlyConstructionRequirement::from_record(&row["requirement"])?,
            recipe: OnlyConstructionRecipe::from_record(&row["resolved_recipe"])?,
            context: OnlyConstructionResolutionContext::new(
                text(&row["source_id"])?,
                text(&row["instrument_id"])?.parse().map_err(err)?,
                text(&row["integration_revision_fingerprint"])?,
                text(&row["calendar_fingerprint"])?,
            )?,
            origin: integer(&row["grid_origin_ns"])?,
        };
        let grid_semantic = if result.recipe.is_native() {
            Some(&result.target)
        } else {
            match result.recipe.base() {
                Some(OnlyConstructionSemantic::Bar(base)) => Some(base),
                _ => None,
            }
        };
        let canonical_origin = match grid_semantic {
            Some(semantic) if semantic.is_fixed_duration() => positive_mod(
                result.origin.clone(),
                &(semantic.stride_minutes().map_err(err)? * 60_000_000_000i64),
            ),
            _ => BigInt::from(0),
        };
        if result.origin != canonical_origin {
            return Err(err("PLAN_GRID_NOT_CANONICAL"));
        }
        if result.recipe.target() != &result.target
            || matches!(&result.requirement,OnlyConstructionRequirement::Exact(recipe) if recipe.as_ref()!=&result.recipe)
            || result.to_record() != *v
        {
            return Err(err("PLAN_RELATIONS_OR_FINGERPRINT"));
        }
        Ok(result)
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyConstructionBaseRevision {
    id: String,
    fingerprint: String,
    seal: String,
}
impl OnlyConstructionBaseRevision {
    pub fn new(id: &str, fingerprint: &str, seal: &str) -> OnlyConstructionResult<Self> {
        nonempty(id)?;
        digest(fingerprint)?;
        nonempty(seal)?;
        Ok(Self {
            id: id.into(),
            fingerprint: fingerprint.into(),
            seal: seal.into(),
        })
    }
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct OnlyConstructionIdentity {
    plan: OnlyConstructionResolutionPlan,
    data_version: String,
    provider_semantic: Option<String>,
    base: Option<OnlyConstructionBaseRevision>,
    adjustment: Option<String>,
}
impl OnlyConstructionIdentity {
    pub fn new(
        plan: OnlyConstructionResolutionPlan,
        data_version: &str,
        provider_semantic: Option<String>,
        base: Option<OnlyConstructionBaseRevision>,
        adjustment: Option<String>,
    ) -> OnlyConstructionResult<Self> {
        nonempty(data_version)?;
        for v in [provider_semantic.as_deref(), adjustment.as_deref()]
            .into_iter()
            .flatten()
        {
            nonempty(v)?;
        }
        if plan.recipe.is_native() == base.is_some() {
            return Err(err("CONSTRUCTION_BASE_LINEAGE"));
        }
        if plan.target.adjustment_policy() != &OnlyAdjustmentType::Raw && adjustment.is_none() {
            return Err(err("ADJUSTMENT_EVIDENCE_REQUIRED"));
        }
        Ok(Self {
            plan,
            data_version: data_version.into(),
            provider_semantic,
            base,
            adjustment,
        })
    }
    pub fn plan(&self) -> &OnlyConstructionResolutionPlan {
        &self.plan
    }
    fn payload(&self) -> Value {
        json!({"schema_version":2,"plan":self.plan.to_record(),"data_version":self.data_version,"provider_semantic":self.provider_semantic,"base_revision_id":self.base.as_ref().map(|v|&v.id),"base_revision_fingerprint":self.base.as_ref().map(|v|&v.fingerprint),"base_seal_id":self.base.as_ref().map(|v|&v.seal),"adjustment_evidence":self.adjustment})
    }
    pub fn fingerprint(&self) -> String {
        hash(&self.payload())
    }
    pub fn to_record(&self) -> Value {
        let mut v = self.payload();
        v["fingerprint"] = self.fingerprint().into();
        v
    }
    pub fn from_record(v: &Value) -> OnlyConstructionResult<Self> {
        let row = object(
            v,
            2,
            &[
                "plan",
                "data_version",
                "provider_semantic",
                "base_revision_id",
                "base_revision_fingerprint",
                "base_seal_id",
                "adjustment_evidence",
                "fingerprint",
            ],
        )?;
        let optional = |key: &str| -> OnlyConstructionResult<Option<String>> {
            if row[key].is_null() {
                Ok(None)
            } else {
                Ok(Some(text(&row[key])?.into()))
            }
        };
        let base = match (
            optional("base_revision_id")?,
            optional("base_revision_fingerprint")?,
            optional("base_seal_id")?,
        ) {
            (None, None, None) => None,
            (Some(id), Some(fp), Some(seal)) => {
                Some(OnlyConstructionBaseRevision::new(&id, &fp, &seal)?)
            }
            _ => return Err(err("BASE_LINEAGE_INCOMPLETE")),
        };
        let result = Self::new(
            OnlyConstructionResolutionPlan::from_record(&row["plan"])?,
            text(&row["data_version"])?,
            optional("provider_semantic")?,
            base,
            optional("adjustment_evidence")?,
        )?;
        if result.to_record() != *v {
            return Err(err("IDENTITY_FINGERPRINT"));
        }
        Ok(result)
    }
}
pub fn only_construction_expected_ends(
    semantic: &OnlyBarSemantic,
    start: BigInt,
    end: BigInt,
    origin: BigInt,
    limit: usize,
) -> OnlyConstructionResult<Vec<BigInt>> {
    if !semantic.is_fixed_duration() {
        return Err(err("EXPECTED_ENDS_UNSUPPORTED"));
    }
    let stride = semantic.stride_minutes().map_err(err)? * 60_000_000_000i64;
    let window = semantic.window_minutes().map_err(err)? * 60_000_000_000i64;
    if start >= end
        || positive_mod(&start - &origin, &stride) != 0.into()
        || positive_mod(&end - &origin, &stride) != 0.into()
    {
        return Ok(vec![]);
    }
    let first = start + window;
    if first > end {
        return Ok(vec![]);
    }
    let count = (&end - &first) / &stride + BigInt::from(1);
    if count > BigInt::from(limit) {
        return Err(err("EXPECTED_ENDS_BUDGET"));
    }
    let count: usize = count.try_into().map_err(err)?;
    let mut result = Vec::new();
    result.try_reserve(count).map_err(err)?;
    for index in 0..count {
        result.push(&first + BigInt::from(index) * &stride);
    }
    Ok(result)
}
