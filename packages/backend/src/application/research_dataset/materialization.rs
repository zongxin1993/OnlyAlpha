//! Source-backed Dataset materialization. No acquisition, generation selection,
//! Human authorization, Run creation or executable permission is inferred here.
use super::*;
use crate::persistence::{
    market_data::{Scope, SealedInput, Storage},
    research_dataset::{Store, VerifiedDataset},
};
use onlyalpha_market_data_construction::OnlyConstructionIdentity;
pub struct MaterializedDataset {
    verified: VerifiedDataset,
    lineage: Value,
}
impl MaterializedDataset {
    /// Reconstitute the owning retained fact, never mint a new materialization.
    pub fn load(store: &Store, id: &str) -> Result<Self> {
        let lineage = store.load_materialization(id)?;
        let verified = store.load(text(&lineage["dataset_snapshot_fingerprint"])?)?;
        let provenance = verified.manifest()["provenance"]
            .as_array()
            .filter(|p| p.len() == 1)
            .ok_or(INVALID)?;
        let sealed = &provenance[0]["source_metadata"]["sealed_input"];
        crate::persistence::market_data::validate_retained_input(
            &sealed["evidence"],
            &sealed["segments"],
        )
        .map_err(|_| "DATASET_SOURCE_LINEAGE_MISMATCH")?;
        let scope = Scope::from_record(&sealed["scope"]).map_err(|_| INVALID)?;
        let record = scope.to_record();
        let revision = &sealed["evidence"]["revision"];
        let construction = OnlyConstructionIdentity::from_record(&record["bar_construction"])
            .map_err(|_| INVALID)?;
        let bindings = json!([{"source_id":record["source_id"],"instrument_id":record["instrument_id"],"data_kind":"BAR","revision_id":revision["revision_id"],"revision_fingerprint":revision["fingerprint"]}]);
        if lineage["market_data_revision_bindings"] != bindings
            || revision["scope"] != record
            || fp(&json!([[
                record["instrument_id"],
                construction.fingerprint(),
                revision["fingerprint"],
                sealed["evidence"]["seal"]["seal_id"]
            ]]))?
                != verified.dataset().construction_fingerprint()
        {
            return Err("DATASET_SOURCE_LINEAGE_MISMATCH");
        }
        NativeMaterializationPlan::new(
            verified.dataset().definition(),
            text(&revision["revision_id"])?,
            scope,
            8192,
        )?;
        if lineage["request_fingerprint"]
            != request_fingerprint(
                verified.dataset().definition(),
                &record,
                &construction.fingerprint(),
            )?
        {
            return Err("DATASET_SOURCE_LINEAGE_MISMATCH");
        }
        // The original requester fingerprint is pinned by its immutable lineage ID;
        // admission additionally compares this full fact to the accepted Run grant.
        Ok(Self { verified, lineage })
    }

    pub fn verified(&self) -> &VerifiedDataset {
        &self.verified
    }
    pub fn lineage(&self) -> &Value {
        &self.lineage
    }
}
pub struct NativeMaterializationPlan {
    definition: Value,
    revision: String,
    scope: Scope,
    construction: OnlyConstructionIdentity,
    max_rows: usize,
}
impl NativeMaterializationPlan {
    pub fn new(
        definition: &Value,
        expected_revision: &str,
        scope: Scope,
        max_rows: usize,
    ) -> Result<Self> {
        if max_rows == 0
            || !expected_revision
                .strip_prefix("market-data-revision:")
                .is_some_and(crate::is_sha256_hex)
        {
            return Err(INVALID);
        }
        let definition = validate_definition(definition)?;
        let scope_record = scope.to_record();
        let context = &scope_record;
        let construction = OnlyConstructionIdentity::from_record(&context["bar_construction"])
            .map_err(|_| "DATASET_BAR_CONSTRUCTION_UNPROVABLE")?;
        let record = construction.to_record();
        let target = &record["plan"]["target_semantic"];
        if context["data_kind"] != "BAR"
            || record["plan"]["resolved_recipe"]["kind"] != "PROVIDER_NATIVE"
            || target["formation"]["kind"] != "FIXED_DURATION"
            || target["formation"]["window_minutes"] != target["formation"]["stride_minutes"]
        {
            return Err("DATASET_CONSTRUCTION_UNSUPPORTED");
        }
        if definition["instruments"] != json!([context["instrument_id"]])
            || definition["bar_semantic"] != *target
        {
            return Err("DATASET_BAR_CONSTRUCTION_MISMATCH");
        }
        let bar_ns = number(&target["formation"]["stride_minutes"])?
            .checked_mul(60_000_000_000)
            .filter(|n| *n > 0)
            .ok_or(INVALID)?;
        let start = ns(&definition["time_range"]["start"])?;
        let end = ns(&definition["time_range"]["end"])?;
        if scope.start_ns().checked_add(bar_ns) != Some(start)
            || scope.end_ns().checked_add(bar_ns) != Some(end)
        {
            return Err("DATASET_MARKET_DATA_SCOPE_MISMATCH");
        }
        let origin = number(&record["plan"]["grid_origin_ns"])?;
        let width = i128::from(end) - i128::from(start);
        if (i128::from(start) - i128::from(origin)) % i128::from(bar_ns) != 0
            || width % i128::from(bar_ns) != 0
            || usize::try_from(width / i128::from(bar_ns))
                .ok()
                .is_none_or(|n| n > max_rows)
        {
            return Err(INVALID);
        }
        Ok(Self {
            definition,
            revision: expected_revision.into(),
            scope,
            construction,
            max_rows,
        })
    }
    pub async fn materialize(
        &self,
        source: &mut Storage<'_>,
        store: &Store,
        created_at: &str,
    ) -> Result<MaterializedDataset> {
        let input = source
            .read_dataset_input(&self.revision, &self.scope)
            .await
            .map_err(|e| e.code())?;
        materialize_native(self, &input, store, created_at)
    }
}
fn materialize_native(
    plan: &NativeMaterializationPlan,
    input: &SealedInput,
    store: &Store,
    created_at: &str,
) -> Result<MaterializedDataset> {
    if input.revision().id() != plan.revision {
        return Err("DATASET_MARKET_DATA_SCOPE_MISMATCH");
    }
    let revision = input.revision().revision();
    let seal = input.revision().seal();
    let scope = &revision["scope"];
    let definition = &plan.definition;
    let construction = &plan.construction;
    let record = construction.to_record();
    let max_rows = plan.max_rows;
    let bindings = json!([[
        scope["instrument_id"],
        construction.fingerprint(),
        revision["fingerprint"],
        seal["seal_id"]
    ]]);
    let construction_fingerprint = fp(&bindings)?;
    let bars = input
        .facts()
        .iter()
        .map(|fact| {
            if fact["source_id"] != scope["source_id"]
                || fact["instrument_id"] != scope["instrument_id"]
                || fact["data_kind"] != "BAR"
                || fact["canonical_payload"]["payload"]["kind"] != "BAR"
            {
                return Err(INVALID);
            }
            Ok(fact["canonical_payload"]["payload"]["value"].clone())
        })
        .collect::<Result<Vec<_>>>()?;
    let dataset = Dataset::from_bars(definition, &bars, &construction_fingerprint, max_rows)?;
    let bar_ns = number(&record["plan"]["target_semantic"]["formation"]["stride_minutes"])?
        .checked_mul(60_000_000_000)
        .ok_or(INVALID)?;
    let expected_count =
        (i128::from(plan.scope.end_ns()) - i128::from(plan.scope.start_ns())) / i128::from(bar_ns);
    if usize::try_from(expected_count).ok() != Some(dataset.rows.len()) {
        return Err("DATASET_MARKET_DATA_SCOPE_MISMATCH");
    }
    let request = request_fingerprint(&dataset.definition, scope, &construction.fingerprint())?;
    let semantic = json!({"dataset_snapshot_fingerprint":dataset.snapshot,"market_data_revision_bindings":[{"source_id":scope["source_id"],"instrument_id":scope["instrument_id"],"data_kind":"BAR","revision_id":revision["revision_id"],"revision_fingerprint":revision["fingerprint"]}],"materializer_id":"onlyalpha.sealed-market-data","materializer_version":"1","request_fingerprint":request});
    let mut lineage = semantic.clone();
    lineage["schema_version"] = json!(1);
    lineage["materialization_id"] = format!("dataset-materialization:{}", fp(&semantic)?).into();
    lineage["created_at"] = iso(created_at)?.into();
    let provenance = json!([{"instrument_id":scope["instrument_id"],"source_id":scope["source_id"],"plugin_id":"durable-market-data","plugin_version":"1","data_version":scope["data_version"],"cache_content_fingerprint":null,"resolved_ranges":[[number(&scope["start_ns"])?.to_string(),number(&scope["end_ns"])?.to_string()]],"observed_ranges":[[number(&scope["start_ns"])?.to_string(),number(&scope["end_ns"])?.to_string()]],"source_metadata":{"bar_construction_fingerprint":construction.fingerprint(),"construction_recipe":record["plan"]["resolved_recipe"],"sealed_input":{"scope":scope,"evidence":input.evidence(),"segments":input.segments()}}}]);
    let verified = store.commit(&dataset, &provenance, created_at)?;
    // A generic Dataset read is not a source-proof grant. Reuse must also prove
    // the exact immutable source occurrence retained by this materialization.
    if verified.manifest()["provenance"] != provenance {
        return Err("DATASET_SOURCE_LINEAGE_MISMATCH");
    }
    let lineage = store.commit_materialization(&lineage)?;
    let verified = store.load(dataset.snapshot_fingerprint())?;
    if verified.manifest()["provenance"] != provenance {
        return Err("DATASET_SOURCE_LINEAGE_MISMATCH");
    }
    Ok(MaterializedDataset { verified, lineage })
}
fn request_fingerprint(definition: &Value, scope: &Value, construction: &str) -> Result<String> {
    let mut definition = definition.clone();
    definition["bar_semantic"] = projection(&definition["bar_semantic"]);
    definition["instruments"] = json!([projection(
        &text(&scope["instrument_id"])?
            .parse::<onlyalpha_domain::identifiers::OnlyInstrumentId>()
            .map_err(|_| INVALID)?
            .to_record()
    )]);
    fp(
        &json!({"definition":definition,"scopes":[projection(scope)],"constructions":[construction]}),
    )
}
fn projection(v: &Value) -> Value {
    match v {
        Value::Object(o) => Value::Object(
            o.iter()
                .filter(|(k, _)| k.as_str() != "schema_version")
                .map(|(k, v)| (k.clone(), projection(v)))
                .collect(),
        ),
        Value::Array(a) => Value::Array(a.iter().map(projection).collect()),
        _ => v.clone(),
    }
}
