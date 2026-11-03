//! Exact Qualification command inputs, separate from evaluator-owned decisions.
use crate::application::{command::CommandId, factor_content::hash};
use crate::persistence::research_evidence::VerifiedResearchCounts;
use serde_json::{Value, json};
type Result<T> = std::result::Result<T, &'static str>;
const INVALID: &str = "QUALIFICATION_REQUEST_INVALID";

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct Request {
    command: CommandId,
    subject: String,
    policy_id: String,
    policy_version: String,
    evidence: Value,
}
impl Request {
    pub(crate) fn new(command: CommandId, subject: &str, policy_id: &str, policy_version: &str, evidence: &Value) -> Result<Self> {
        if !crate::is_sha256_hex(subject) || policy_id.is_empty() || policy_id.len()>128
            || !policy_id.bytes().all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || matches!(b,b'.'|b'_'|b'-'))
            || !policy_id.as_bytes()[0].is_ascii_alphanumeric() || policy_version.is_empty()
            || policy_version.len()>128 || policy_version.starts_with('0') || !policy_version.bytes().all(|b|b.is_ascii_digit()) {
            return Err(INVALID);
        }
        let rows=evidence.as_array().filter(|rows|rows.len()==1).ok_or(INVALID)?;
        let row=&rows[0];
        let locator=match row["kind"].as_str() {
            Some("RESEARCH_RESULT")=>"locator_fingerprint",
            Some("STRATEGY_VALIDATION")=>"preparation_command_id",
            _=>return Err(INVALID),
        };
        let fields=["kind","evidence_fingerprint",locator,"subject_binding_fingerprint"];
        if row.as_object().is_none_or(|m|m.len()!=fields.len()||fields.iter().any(|k|!m.contains_key(*k))) {return Err(INVALID);}
        for key in ["evidence_fingerprint","subject_binding_fingerprint"] {if row[key].as_str().is_none_or(|s|!crate::is_sha256_hex(s)) {return Err(INVALID);}}
        let selected=row[locator].as_str().ok_or(INVALID)?;
        if (locator=="locator_fingerprint"&&!crate::is_sha256_hex(selected))
            ||(locator=="preparation_command_id"&&CommandId::new(selected).is_err()) {return Err(INVALID);}
        Ok(Self {command,subject:subject.into(),policy_id:policy_id.into(),policy_version:policy_version.into(),evidence:evidence.clone()})
    }
    /// Evidence values come only from the actual completed Research/Frozen owner.
    /// The Run occurrence remains a read locator, outside public semantic identity.
    pub(crate) fn from_counts(command:CommandId,policy_id:&str,policy_version:&str,counts:&VerifiedResearchCounts)->Result<Self> {
        counts.verify_cut()?;
        let request=Self::new(command,counts.subject_strategy_fingerprint(),policy_id,policy_version,&json!([{
            "kind":"RESEARCH_RESULT","evidence_fingerprint":counts.research_result_fingerprint(),
            "locator_fingerprint":counts.research_result_plan_fingerprint(),"subject_binding_fingerprint":counts.freeze_relation_fingerprint()}]))?;
        request.matches_counts(counts)?;Ok(request)
    }
    pub(crate) fn from_manual(command:CommandId,policy_id:&str,policy_version:&str,evidence:&crate::application::frozen_strategy::VerifiedManualBacktestEvidence)->Result<Self> {
        evidence.verify_cut()?;
        let request=Self::new(command,evidence.subject_strategy_fingerprint(),policy_id,policy_version,&json!([{
            "kind":"STRATEGY_VALIDATION","evidence_fingerprint":evidence.validation_fingerprint(),
            "preparation_command_id":evidence.preparation_command_id(),"subject_binding_fingerprint":evidence.freeze_relation_fingerprint()}]))?;
        request.matches_manual(evidence)?;Ok(request)
    }
    pub(crate) fn evidence_kind(&self)->&str {self.evidence[0]["kind"].as_str().expect("validated evidence kind")}
    pub(crate) fn evidence_fingerprint(&self)->&str {self.evidence[0]["evidence_fingerprint"].as_str().expect("validated evidence identity")}
    pub(crate) fn preparation_command_id(&self)->Result<&str> {
        self.evidence[0]["preparation_command_id"].as_str().ok_or("QUALIFICATION_EVIDENCE_GATE_MISMATCH")
    }
    pub(crate) fn matches_manual(&self,evidence:&crate::application::frozen_strategy::VerifiedManualBacktestEvidence)->Result<()> {
        evidence.verify_cut()?;
        if self.evidence_kind()!="STRATEGY_VALIDATION" || evidence.subject_strategy_fingerprint()!=self.subject()
            || evidence.validation_fingerprint()!=self.evidence_fingerprint()
            || evidence.preparation_command_id()!=self.preparation_command_id()?
            || evidence.freeze_relation_fingerprint()!=self.relation_fingerprint() {return Err("QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH");}
        Ok(())
    }
    pub(crate) fn command_id(&self)->&CommandId {&self.command}
    pub(crate) fn subject(&self)->&str {&self.subject}
    pub(crate) fn policy_id(&self)->&str {&self.policy_id}
    pub(crate) fn policy_version(&self)->&str {&self.policy_version}
    pub(crate) fn evidence(&self)->&Value {&self.evidence}
    pub(crate) fn result_fingerprint(&self)->&str {self.evidence[0]["evidence_fingerprint"].as_str().expect("validated Result identity")}
    pub(crate) fn result_plan_fingerprint(&self)->&str {self.evidence[0]["locator_fingerprint"].as_str().expect("validated ResultPlan identity")}
    pub(crate) fn relation_fingerprint(&self)->&str {self.evidence[0]["subject_binding_fingerprint"].as_str().expect("validated Freeze relation identity")}
    pub(crate) fn fingerprint(&self)->Result<String> {
        hash(&json!({"subject_strategy_fingerprint":self.subject,"policy_id":self.policy_id,"policy_version":self.policy_version,"evidence":self.evidence}))
    }
    pub(crate) fn matches_counts(&self, counts:&VerifiedResearchCounts)->Result<()> {
        counts.verify_cut()?;
        if self.evidence_kind()!="RESEARCH_RESULT" || counts.subject_strategy_fingerprint()!=self.subject() || counts.research_result_fingerprint()!=self.result_fingerprint()
            || counts.research_result_plan_fingerprint()!=self.result_plan_fingerprint()
            || counts.freeze_relation_fingerprint()!=self.relation_fingerprint() {return Err("QUALIFICATION_EVIDENCE_SUBJECT_MISMATCH");}
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::{command::CommandId, factor_content::hash};
    use serde_json::{Value, json};
    fn evidence() -> Value {
        json!([{"kind":"RESEARCH_RESULT","evidence_fingerprint":"b".repeat(64),
            "locator_fingerprint":"c".repeat(64),"subject_binding_fingerprint":"d".repeat(64)}])
    }
    fn command() -> CommandId {CommandId::new("00000000-0000-4000-8000-000000000801").unwrap()}
    #[test]
    fn exact_qualification_command_preserves_original_public_operational_identity() {
        let request=Request::new(command(), &"a".repeat(64),"experimental-backtest","1",&evidence()).unwrap();
        assert_eq!(request.fingerprint().unwrap(),hash(&json!({"subject_strategy_fingerprint":"a".repeat(64),
            "policy_id":"experimental-backtest","policy_version":"1","evidence":evidence()})).unwrap());
        assert_eq!(request.command_id(),&command());
        assert_eq!(request.subject(),"a".repeat(64));
        assert_eq!(request.evidence(),&evidence());
        assert_eq!(request.result_fingerprint(),"b".repeat(64));
        assert_eq!(request.result_plan_fingerprint(),"c".repeat(64));
        assert_eq!(request.relation_fingerprint(),"d".repeat(64));
        let other=CommandId::new("00000000-0000-4000-8000-000000000802").unwrap();
        assert_eq!(Request::new(other,&"a".repeat(64),"experimental-backtest","1",&evidence()).unwrap().fingerprint().unwrap(),request.fingerprint().unwrap());
    }
    #[test]
    fn unsupported_or_unbound_qualification_inputs_are_not_silently_reinterpreted() {
        for index in 0..10 {
            let mut rows=evidence();
            match index {
                0=>rows=json!([]),1=>rows[0]["kind"]=json!("BACKTEST_EVIDENCE"),
                2=>rows[0]["locator_fingerprint"]=Value::Null,
                3=>rows[0]["subject_binding_fingerprint"]=Value::Null,
                4=>rows[0]["evidence_fingerprint"]=json!("A".repeat(64)),
                5=>rows[0]["outcome"]=json!("APPROVED"),
                6=>rows[0].as_object_mut().unwrap().remove("kind").map(|_|()).unwrap(),
                7=>{let item=rows[0].clone();rows.as_array_mut().unwrap().push(item);},
                8=>rows[0]["locator_fingerprint"]=json!(true),
                _=>rows=json!({"kind":"RESEARCH_RESULT"}),
            }
            assert!(Request::new(command(),&"a".repeat(64),"experimental-backtest","1",&rows).is_err(),"case {index}");
        }
        for (subject,id,version) in [("bad","experimental-backtest","1"),("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","../policy","1"),("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","experimental-backtest","latest"),("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","experimental-backtest","01")] {
            assert!(Request::new(command(),subject,id,version,&evidence()).is_err());
        }
    }
}

#[cfg(test)]
mod manual_reference_tests {
    use super::*;
    #[test]
    fn manual_validation_reference_keeps_its_real_preparation_occurrence() {
        let command=CommandId::new("00000000-0000-4000-8000-000000008801").unwrap();
        let preparation="00000000-0000-4000-8000-000000008802";
        let evidence=json!([{"kind":"STRATEGY_VALIDATION","evidence_fingerprint":"b".repeat(64),
            "preparation_command_id":preparation,"subject_binding_fingerprint":"d".repeat(64)}]);
        let request=Request::new(command,&"a".repeat(64),"manual-backtest","1",&evidence).unwrap();
        assert_eq!(request.evidence(),&evidence);
        assert_eq!(request.fingerprint().unwrap(),hash(&json!({"subject_strategy_fingerprint":"a".repeat(64),
            "policy_id":"manual-backtest","policy_version":"1","evidence":evidence})).unwrap());
        for mutation in 0..5 {
            let mut wrong=evidence.clone();
            match mutation {
                0=>wrong[0]["preparation_command_id"]=json!("latest"),
                1=>wrong[0]["preparation_command_id"]=json!("e".repeat(64)),
                2=>{wrong[0].as_object_mut().unwrap().remove("preparation_command_id");wrong[0]["locator_fingerprint"]=json!("e".repeat(64));},
                3=>wrong[0]["outcome"]=json!("APPROVED"),
                _=>wrong[0]["kind"]=json!("RESEARCH_RESULT"),
            }
            assert!(Request::new(CommandId::new("00000000-0000-4000-8000-000000008803").unwrap(),&"a".repeat(64),"manual-backtest","1",&wrong).is_err(),"mutation {mutation}");
        }
    }
}
