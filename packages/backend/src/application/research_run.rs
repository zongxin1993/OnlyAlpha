//! One finite Research intent and opaque execution/recovery proofs.
//! Operational authority remains the existing Command, Run and Attempt tables.
use crate::application::research_novelty::Subject;
use crate::application::{
    command::CommandId,
    factor_content::hash,
    research_factor::{self, CompiledFactor},
    research_specification::Study,
};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};

type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "RESEARCH_NATIVE_SPECIFICATION_INVALID";
#[derive(Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Specification {
    pub schema_version: u32,
    pub kind: String,
    pub candidate: Value,
    pub draft: Value,
    pub revision: Value,
    pub study: Study,
    pub dataset_snapshot_fingerprint: String,
    pub runtime_generation_fingerprint: String,
    pub catalog_generation_fingerprint: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub authoring_generation_fingerprint: Option<String>,
    pub algorithm_artifact_fingerprint: String,
    pub execution_binding: Value,
}
impl Specification {
    pub fn record(&self) -> Result<Value> {
        serde_json::to_value(self).map_err(|_| INVALID)
    }
    pub fn fingerprint(&self) -> Result<String> {
        self.validate()?;
        hash(&self.record()?)
    }
    pub fn factor(&self) -> Result<CompiledFactor> {
        let candidate = json!({"name":"Factor","purpose":"Research","hypothesis":self.candidate["hypothesis"],"expression":self.candidate["expression"]});
        research_factor::compile(&candidate, &self.draft, &self.revision)
    }
    pub fn validate(&self) -> Result<()> {
        if self.kind != "TIME_SERIES_FACTOR_RESEARCH"
            || !match (
                self.schema_version,
                self.authoring_generation_fingerprint.as_deref(),
            ) {
                (4, None) => true,
                (6, Some(pin)) => crate::is_sha256_hex(pin),
                _ => false,
            }
        {
            return Err(INVALID);
        }
        if self.candidate.as_object().is_none_or(|o| {
            o.len() != 2 || !o.contains_key("expression") || !o.contains_key("hypothesis")
        }) {
            return Err(INVALID);
        }
        self.study.comparison_family()?;
        for pin in [
            &self.dataset_snapshot_fingerprint,
            &self.runtime_generation_fingerprint,
            &self.catalog_generation_fingerprint,
            &self.algorithm_artifact_fingerprint,
        ] {
            if !crate::is_sha256_hex(pin) {
                return Err(INVALID);
            }
        }
        self.factor()?;
        let binding = self.execution_binding.as_object().ok_or(INVALID)?;
        if binding.len() != 5
            || self.execution_binding["protocol"] != "onlyalpha.research.executor/1"
            || !self.execution_binding["executor_version"]
                .as_str()
                .is_some_and(|v| {
                    !v.is_empty()
                        && v.len() <= 255
                        && v.bytes()
                            .all(|c| c.is_ascii_alphanumeric() || b"._+-".contains(&c))
                })
        {
            return Err(INVALID);
        }
        for k in [
            "executor_manifest_fingerprint",
            "executor_artifact_sha256",
            "core_execution_fingerprint",
        ] {
            if !self.execution_binding[k]
                .as_str()
                .is_some_and(crate::is_sha256_hex)
            {
                return Err(INVALID);
            }
        }
        Ok(())
    }
    pub(crate) fn matches_prepared_authoring(&self, prepared: &Value) -> bool {
        match self.authoring_generation_fingerprint.as_deref() {
            Some(pin) => {
                prepared["schema_version"] == 2
                    && prepared["contract"] == "ONLYALPHA_RESEARCH_PREPARED_INPUTS_V2"
                    && prepared["authoring_generation_fingerprint"] == pin
            }
            None => {
                prepared["schema_version"] == 1
                    && prepared["contract"] == "ONLYALPHA_RESEARCH_PREPARED_INPUTS_V1"
                    && prepared.get("authoring_generation_fingerprint").is_none()
            }
        }
    }
    pub fn calculation_fingerprint(&self) -> Result<String> {
        let window = self
            .factor()?
            .window(crate::application::research_factor::Window {
                start_ns: self.study.samples[0].start_ns,
                end_ns: self.study.samples[1].end_ns,
                bar_ns: self.study.bar_ns,
                horizon_bars: self.study.horizon_bars,
            })?
            .to_record();
        hash(
            &json!({"execution_axis":{"dataset_event_start_ns":window["dataset_event_start_ns"],"dataset_event_end_ns":window["dataset_event_end_ns"],"bar_ns":window["bar_ns"]},"schema_version":3,"contract":"ONLYALPHA_NATIVE_TIME_SERIES_FEATURE_V1","dataset_snapshot_fingerprint":self.dataset_snapshot_fingerprint,
            "calculation_graph_fingerprint":self.factor()?.graph().fingerprint(),"factor_revision_fingerprint":self.revision["revision_fingerprint"],"algorithm_artifact_fingerprint":self.algorithm_artifact_fingerprint,"backend":"RESEARCH"}),
        )
    }
    pub fn statistics_intents(&self) -> Result<Vec<Value>> {
        let family = self.study.comparison_family()?;
        let calculation = self.calculation_fingerprint()?;
        self.study.samples.iter().map(|sample| Ok(json!({
            "contract":"ONLYALPHA_TIME_SERIES_STATISTICS_INTENT_V1",
            "specification_fingerprint":hash(&self.record()?)?,
            "dataset_snapshot_fingerprint":self.dataset_snapshot_fingerprint,
            "feature_calculation_fingerprint":calculation,"feature_node_fingerprint":self.factor()?.root_fingerprint(),
            "feature_output_name":"value","target":{"contract":"CLOSE_FORWARD_RETURN_V1","horizon_bars":self.study.horizon_bars,
                "numeric":{"precision":38,"quantum":"0.000000000001","rounding":"ROUND_HALF_EVEN"}},
            "sample":sample,"study_fingerprint":self.study.logical_fingerprint()?,"comparison_family":family,
        }))).collect()
    }
    pub fn result_plan(&self) -> Result<Value> {
        let mut statistics = self
            .statistics_intents()?
            .iter()
            .map(hash)
            .collect::<Result<Vec<_>>>()?;
        statistics.sort();
        Ok(
            json!({"schema_version":5,"family":"TIME_SERIES_FACTOR_RESEARCH",
            "specification_fingerprint":hash(&self.record()?)?,
            "dataset_snapshot_fingerprint":self.dataset_snapshot_fingerprint,
            "calculation_fingerprint":self.calculation_fingerprint()?,
            "graph_fingerprint":self.factor()?.graph().fingerprint(),"statistics_fingerprints":statistics,
            "study_fingerprint":self.study.logical_fingerprint()?}),
        )
    }
    pub fn subject(&self) -> Result<Subject> {
        self.validate()?;
        let specification = hash(&self.record()?)?;
        let calculation = self.calculation_fingerprint()?;
        let candidate = hash(
            &json!({"schema_version":1,"specification_fingerprint":specification,
            "candidate_calculation_id":self.revision["factor_id"],"assignment":{},"calculation_fingerprint":calculation}),
        )?;
        let plan = self.result_plan()?;
        Subject::new(
            json!({"schema_version":1,"graph_fingerprint":self.factor()?.graph().fingerprint(),
            "candidate_node_fingerprint":self.factor()?.root_fingerprint(),"output_name":"value",
            "candidate_fingerprint":candidate,"dataset_snapshot_fingerprint":self.dataset_snapshot_fingerprint,
            "specification_fingerprint":specification,"result_plan_fingerprint":hash(&plan)?,
            "statistics_fingerprints":plan["statistics_fingerprints"],
            "catalog_generation_fingerprint":self.catalog_generation_fingerprint,
            "runtime_generation_fingerprint":self.runtime_generation_fingerprint,"authoring_generation_fingerprint":self.authoring_generation_fingerprint}),
        )
    }
}
/// One explicit finite-executor family; parsing a value is never Run permission.
#[derive(Clone)]
pub enum NativeSpecification {
    Factor(Box<Specification>),
    Strategy(Box<crate::application::strategy_research::RunSpecification>),
}
impl NativeSpecification {
    pub fn from_record(record: &Value) -> Result<Self> {
        if record.to_string().len() > 8 * 1024 * 1024 {
            return Err(INVALID);
        }
        match record["schema_version"].as_u64() {
            Some(4 | 6) => {
                let spec: Specification =
                    serde_json::from_value(record.clone()).map_err(|_| INVALID)?;
                spec.validate()?;
                if spec.record()? != *record {
                    return Err(INVALID);
                }
                Ok(Self::Factor(Box::new(spec)))
            }
            Some(5) => Ok(Self::Strategy(Box::new(
                crate::application::strategy_research::RunSpecification::from_record(record)?,
            ))),
            _ => Err(INVALID),
        }
    }
    pub fn record(&self) -> Result<Value> {
        match self {
            Self::Factor(s) => s.record(),
            Self::Strategy(s) => Ok(s.record().clone()),
        }
    }
    pub fn fingerprint(&self) -> Result<String> {
        match self {
            Self::Factor(s) => s.fingerprint(),
            Self::Strategy(s) => s.fingerprint(),
        }
    }
    pub fn scientific_specification_fingerprint(&self) -> Result<String> {
        match self {
            Self::Factor(s) => s.fingerprint(),
            Self::Strategy(s) => s.scientific_specification_fingerprint(),
        }
    }
    pub fn subject(&self) -> Result<Subject> {
        match self {
            Self::Factor(s) => s.subject(),
            Self::Strategy(s) => s.subject(),
        }
    }
    pub fn result_plan(&self) -> Result<Value> {
        match self {
            Self::Factor(s) => s.result_plan(),
            Self::Strategy(s) => s.result_plan(),
        }
    }
    pub fn as_factor(&self) -> Result<&Specification> {
        match self {
            Self::Factor(s) => Ok(s),
            Self::Strategy(_) => Err("RESEARCH_FACTOR_SPECIFICATION_REQUIRED"),
        }
    }
    pub fn as_strategy(&self) -> Result<&crate::application::strategy_research::RunSpecification> {
        match self {
            Self::Strategy(s) => Ok(s),
            Self::Factor(_) => Err("RESEARCH_STRATEGY_SPECIFICATION_REQUIRED"),
        }
    }
    fn pin(&self, key: &str) -> Result<&str> {
        let value = match self {
            Self::Factor(s) => match key {
                "runtime_generation_fingerprint" => &s.runtime_generation_fingerprint,
                "catalog_generation_fingerprint" => &s.catalog_generation_fingerprint,
                "algorithm_artifact_fingerprint" => &s.algorithm_artifact_fingerprint,
                "dataset_snapshot_fingerprint" => &s.dataset_snapshot_fingerprint,
                _ => return Err(INVALID),
            },
            Self::Strategy(s) => {
                let value = if key == "dataset_snapshot_fingerprint" {
                    &s.record()["scientific_specification"][key]
                } else {
                    &s.record()[key]
                };
                value.as_str().ok_or(INVALID)?
            }
        };
        if !crate::is_sha256_hex(value) {
            return Err(INVALID);
        }
        Ok(value)
    }
    pub fn runtime_generation_fingerprint(&self) -> Result<&str> {
        self.pin("runtime_generation_fingerprint")
    }
    pub fn catalog_generation_fingerprint(&self) -> Result<&str> {
        self.pin("catalog_generation_fingerprint")
    }
    pub fn algorithm_artifact_fingerprint(&self) -> Result<&str> {
        self.pin("algorithm_artifact_fingerprint")
    }
    pub fn dataset_snapshot_fingerprint(&self) -> Result<&str> {
        self.pin("dataset_snapshot_fingerprint")
    }
}

pub fn verify_native_spec_record(record: &Value) -> Result<()> {
    NativeSpecification::from_record(record).map(drop)
}
pub fn source_subject(row: &Value) -> Result<Subject> {
    let payload = row["specification_payload"].as_str().ok_or(INVALID)?;
    let record: Value = serde_json::from_str(payload).map_err(|_| INVALID)?;
    let spec = NativeSpecification::from_record(&record)?;
    if spec.fingerprint()? != row["specification_fingerprint"]
        || !row["authoring_provenance"].is_null()
    {
        return Err(INVALID);
    }
    spec.subject()
}
/// Exact trace pins derived only from the already verified DB Human admission.
/// This is not a replacement for reading the original Decision owning records.
#[derive(Clone)]
pub struct DecisionReference {
    pub(crate) command: CommandId,
    pub(crate) group_fingerprint: String,
    pub(crate) policy_id: String,
    pub(crate) policy_version: String,
    subject: String,
    decision: String,
    intent: String,
    decision_time_proof: String,
}
impl DecisionReference {
    pub(crate) fn from_member(
        command: CommandId,
        group: &str,
        policy: &str,
        version: &str,
        member: &Value,
    ) -> Result<Self> {
        let invalid = "RESEARCH_DECISION_PROVENANCE_MISMATCH";
        let pin = |key: &str| {
            member[key]
                .as_str()
                .filter(|v| crate::is_sha256_hex(v))
                .map(str::to_owned)
                .ok_or(invalid)
        };
        if !crate::is_sha256_hex(group) || policy.is_empty() || version.is_empty() {
            return Err(invalid);
        }
        Ok(Self {
            command,
            group_fingerprint: group.into(),
            policy_id: policy.into(),
            policy_version: version.into(),
            subject: pin("evaluation_subject_fingerprint")?,
            decision: pin("novelty_decision_fingerprint")?,
            intent: pin("canonical_intent_fingerprint")?,
            decision_time_proof: pin("decision_time_proof_fingerprint")?,
        })
    }
    /// Called after the actual owning historical Group reader, never on a client claim.
    pub(crate) fn verify_group(&self, group: &Value) -> Result<()> {
        let invalid = "RESEARCH_DECISION_PROVENANCE_MISMATCH";
        let members = group["members"].as_array().ok_or(invalid)?;
        if group["group_fingerprint"] != self.group_fingerprint
            || group["product_command_id"] != self.command.value()
            || group["disposition"] != "ACTIONABLE"
            || members.len() != 1
        {
            return Err(invalid);
        }
        let bundle = &members[0];
        let decision = &bundle["decision"];
        let witness = &bundle["witness"];
        let subject =
            Subject::new(witness["subject"]["resolved_subject"]["evaluation_subject"].clone())
                .map_err(|_| invalid)?;
        if subject.fingerprint().map_err(|_| invalid)? != self.subject
            || decision["decision_fingerprint"] != self.decision
            || decision["canonical_intent_fingerprint"] != self.intent
            || decision["product_command_id"] != self.command.value()
            || decision["policy_id"] != self.policy_id
            || decision["policy_version"] != self.policy_version
            || decision["outcome"] != "ADMIT"
            || witness["proofs"].as_array().map(Vec::len) != Some(1)
            || witness["proofs"][0]["proof"]["result_fingerprint"] != self.decision_time_proof
        {
            return Err(invalid);
        }
        Ok(())
    }
}
/// Only an owning, verified persisted admission can construct this handle.
#[derive(Clone)]
pub struct VerifiedRun {
    pub(crate) run_id: String,
    pub(crate) payload: String,
    pub(crate) specification: NativeSpecification,
    pub(crate) specification_fingerprint: String,
    pub(crate) admission_fingerprint: String,
    pub(crate) prepared_inputs: Value,
    pub(crate) name_snapshot: Value,
    pub(crate) accepted_at: String,
    pub(crate) decision_reference: DecisionReference,
    pub(crate) completion: Option<(String, String, Vec<String>)>,
}
impl VerifiedRun {
    pub fn run_id(&self) -> &str {
        &self.run_id
    }
    pub fn specification_fingerprint(&self) -> &str {
        &self.specification_fingerprint
    }
    pub fn admission_resolution_fingerprint(&self) -> &str {
        &self.admission_fingerprint
    }
    pub fn canonical_specification_payload(&self) -> &str {
        &self.payload
    }
    pub fn runtime_generation_fingerprint(&self) -> Result<&str> {
        self.specification.runtime_generation_fingerprint()
    }
    pub(crate) fn verify_completion(&self, completion: &VerifiedCompletion) -> Result<()> {
        if self.completion.as_ref().is_some_and(|(r, a, e)| {
            r != completion.research_result_fingerprint()
                || a != completion.artifact_content_fingerprint()
                || e != completion.calculation_execution_evidence_fingerprints()
        }) {
            Err("RESEARCH_COMPLETION_PROOF_MISMATCH")
        } else {
            Ok(())
        }
    }
    pub(crate) fn completed(&self) -> bool {
        self.completion.is_some()
    }
    pub fn specification(&self) -> &NativeSpecification {
        &self.specification
    }
    pub fn factor_specification(&self) -> Result<&Specification> {
        self.specification.as_factor()
    }
    pub fn strategy_specification(
        &self,
    ) -> Result<&crate::application::strategy_research::RunSpecification> {
        self.specification.as_strategy()
    }
}
/// Issued only after verified immutable semantic and report publication.
pub struct VerifiedCompletion {
    pub(crate) run: VerifiedRun,
    pub(crate) result: String,
    pub(crate) artifact: String,
    pub(crate) execution_evidence: Vec<String>,
    pub(crate) strategy_cut:
        Option<std::sync::Arc<crate::persistence::research_evidence::StrategyReadCut>>,
}
impl VerifiedCompletion {
    pub(crate) fn verify_cut(&self) -> Result<()> {
        if let Some(cut) = &self.strategy_cut {
            cut.verify()?;
        }
        Ok(())
    }
    pub fn run_id(&self) -> &str {
        self.run.run_id()
    }
    pub fn specification_fingerprint(&self) -> &str {
        self.run.specification_fingerprint()
    }
    pub fn admission_resolution_fingerprint(&self) -> &str {
        self.run.admission_resolution_fingerprint()
    }
    pub fn research_result_fingerprint(&self) -> &str {
        &self.result
    }
    pub fn artifact_content_fingerprint(&self) -> &str {
        &self.artifact
    }
    pub fn calculation_execution_evidence_fingerprints(&self) -> &[String] {
        &self.execution_evidence
    }
}
pub enum InspectionOutcome {
    Complete(Box<VerifiedCompletion>),
    Absent,
    Corrupt,
}
pub struct VerifiedInspection {
    pub(crate) run: VerifiedRun,
    pub(crate) revision: i64,
    pub(crate) outcome: InspectionOutcome,
    pub(crate) publication_cut: Vec<std::sync::Arc<crate::security::immutable_json::SourceLock>>,
}
impl VerifiedInspection {
    pub fn run_id(&self) -> &str {
        self.run.run_id()
    }
    pub fn specification_fingerprint(&self) -> &str {
        self.run.specification_fingerprint()
    }
    pub fn admission_resolution_fingerprint(&self) -> &str {
        self.run.admission_resolution_fingerprint()
    }
    pub fn expected_revision(&self) -> i64 {
        self.revision
    }
    pub(crate) fn verify_cut(&self) -> Result<()> {
        if self.publication_cut.is_empty() {
            return Err("RESEARCH_INSPECTION_CUT_REQUIRED");
        }
        if let InspectionOutcome::Complete(completion) = &self.outcome {
            completion.verify_cut()?;
        }
        for lock in &self.publication_cut {
            lock.verify()?;
        }
        Ok(())
    }
    pub fn outcome(&self) -> &InspectionOutcome {
        &self.outcome
    }
}

#[cfg(test)]
mod decision_reference_tests {
    use super::*;
    use crate::application::command::CommandId;

    #[test]
    fn report_trace_requires_original_admission_leaves_not_a_shared_group_label() {
        // Original immutable contract vector; this checks metadata closure only,
        // not the independent source-owner completeness proved by retained_group.
        let vector: Value = serde_json::from_str(include_str!(
            "../../tests/application/fixtures/research_novelty.json"
        ))
        .unwrap();
        let group = vector["group"].clone();
        let bundle = &group["members"][0];
        let subject = Subject::new(
            bundle["witness"]["subject"]["resolved_subject"]["evaluation_subject"].clone(),
        )
        .unwrap();
        let member = json!({"evaluation_subject_fingerprint":subject.fingerprint().unwrap(),
            "novelty_decision_fingerprint":bundle["decision"]["decision_fingerprint"],
            "canonical_intent_fingerprint":bundle["decision"]["canonical_intent_fingerprint"],
            "decision_time_proof_fingerprint":bundle["witness"]["proofs"][0]["proof"]["result_fingerprint"]});
        let reference = DecisionReference::from_member(
            CommandId::new(group["product_command_id"].as_str().unwrap()).unwrap(),
            group["group_fingerprint"].as_str().unwrap(),
            bundle["decision"]["policy_id"].as_str().unwrap(),
            bundle["decision"]["policy_version"].as_str().unwrap(),
            &member,
        )
        .unwrap();
        reference.verify_group(&group).unwrap();
        for (container, key) in [
            ("decision", "decision_fingerprint"),
            ("decision", "canonical_intent_fingerprint"),
        ] {
            let mut changed = group.clone();
            changed["members"][0][container][key] = "f".repeat(64).into();
            assert!(reference.verify_group(&changed).is_err());
        }
        let mut changed = group.clone();
        changed["members"][0]["witness"]["proofs"][0]["proof"]["result_fingerprint"] =
            "f".repeat(64).into();
        assert!(reference.verify_group(&changed).is_err());
        let mut changed = group.clone();
        changed["product_command_id"] = "00000000-0000-4000-8000-000000000001".into();
        assert!(reference.verify_group(&changed).is_err());
        let mut changed = group;
        changed["members"] = json!([]);
        assert!(reference.verify_group(&changed).is_err());
    }
}

#[cfg(test)]
mod native_specification_tests {
    use super::*;
    #[test]
    fn executable_family_is_explicit_and_preserves_scientific_identity() {
        let record = crate::application::strategy_research::test_run_record();
        let science =
            crate::application::strategy_research::RunSpecification::from_record(&record).unwrap();
        let executable = NativeSpecification::from_record(&record).unwrap();
        assert_eq!(executable.record().unwrap(), record);
        assert_eq!(
            executable.dataset_snapshot_fingerprint().unwrap(),
            record["scientific_specification"]["dataset_snapshot_fingerprint"]
                .as_str()
                .unwrap()
        );
        assert_eq!(
            executable.fingerprint().unwrap(),
            science.fingerprint().unwrap()
        );
        assert_eq!(
            executable.scientific_specification_fingerprint().unwrap(),
            science.scientific_specification_fingerprint().unwrap()
        );
        assert!(executable.as_factor().is_err());
        assert_eq!(
            executable
                .as_strategy()
                .unwrap()
                .candidate_fingerprint()
                .unwrap(),
            science.candidate_fingerprint().unwrap()
        );
        verify_native_spec_record(&record).unwrap();
        let row = json!({"specification_payload":onlyalpha_metadata_json::canonical_json(&record.to_string(),8*1024*1024).unwrap(),"specification_fingerprint":science.fingerprint().unwrap(),"authoring_provenance":null});
        assert_eq!(
            source_subject(&row).unwrap().record(),
            science.subject().unwrap().record()
        );
        let mut detached = row.clone();
        detached["specification_fingerprint"] = json!("f".repeat(64));
        assert!(source_subject(&detached).is_err());
    }
    #[test]
    fn factor4_record_and_identity_remain_exact() {
        let fixture: Value = serde_json::from_str(include_str!(
            "../../tests/application/fixtures/research_factor.json"
        ))
        .unwrap();
        let spec=Specification{schema_version:4,kind:"TIME_SERIES_FACTOR_RESEARCH".into(),candidate:json!({"hypothesis":fixture["candidate"]["hypothesis"],"expression":fixture["candidate"]["expression"]}),draft:fixture["draft"].clone(),revision:fixture["revision"].clone(),study:serde_json::from_value(json!({"schema_version":1,"bar_ns":60000000000u64,"horizon_bars":5,"samples":[{"role":"DEVELOPMENT","start_ns":1200000000000u64,"end_ns":2400000000000u64},{"role":"OUT_OF_SAMPLE","start_ns":2400000000000u64,"end_ns":3600000000000u64}],"protected_start_ns":6000000000000u64,"protected_end_ns":7200000000000u64,"expected_block_length":20,"replicates":400,"confidence_bps":9500,"seed":"a".repeat(64)})).unwrap(),dataset_snapshot_fingerprint:"b".repeat(64),runtime_generation_fingerprint:"c".repeat(64),catalog_generation_fingerprint:"d".repeat(64),authoring_generation_fingerprint:None,algorithm_artifact_fingerprint:"e".repeat(64),execution_binding:json!({"protocol":"onlyalpha.research.executor/1","executor_version":"0.11.1","executor_manifest_fingerprint":"e".repeat(64),"executor_artifact_sha256":"f".repeat(64),"core_execution_fingerprint":"a".repeat(64)})};
        spec.validate().unwrap();
        let record = spec.record().unwrap();
        let executable = NativeSpecification::from_record(&record).unwrap();
        assert_eq!(executable.record().unwrap(), record);
        assert_eq!(
            executable.fingerprint().unwrap(),
            spec.fingerprint().unwrap()
        );
        assert_eq!(
            executable.subject().unwrap().record(),
            spec.subject().unwrap().record()
        );
        assert!(executable.as_strategy().is_err());
        assert_eq!(executable.as_factor().unwrap().record().unwrap(), record);
        let mut alias = record.clone();
        alias["authoring_generation_fingerprint"] = Value::Null;
        assert!(NativeSpecification::from_record(&alias).is_err());
        let mut authoring = record;
        authoring["schema_version"] = json!(6);
        assert!(NativeSpecification::from_record(&authoring).is_err());
        let pin = json!("f".repeat(64));
        authoring["authoring_generation_fingerprint"] = pin.clone();
        let bound = NativeSpecification::from_record(&authoring).unwrap();
        assert_eq!(
            bound.subject().unwrap().record()["authoring_generation_fingerprint"],
            pin
        );
        assert_ne!(bound.fingerprint().unwrap(), spec.fingerprint().unwrap());
    }
}
