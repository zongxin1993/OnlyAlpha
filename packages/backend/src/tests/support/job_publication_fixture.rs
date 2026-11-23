//! Synthetic storage-owner fixture, compiled ONLY in test artifacts. It proves
//! repository mechanics, never real engine completion or factor certification.
use super::model::ClaimSource;
use super::*;
use crate::application::job_contract::{fact_axis_rule, fact_coordinate};
use serde_json::json;
use std::time::{Duration, SystemTime};
/// SQL storage mechanics only. Real finite-owner candidates are explicitly
/// rejected by this test-only repository; it grants no Node publication proof.
pub async fn storage_repository<'a>(client:&'a mut Client,namespace:&SemanticStoreId,owner:&str) -> Result<PublicationRepository<'a>> {
    let mut repository = PublicationRepository::new(client,namespace,owner).await?;
    repository.mutation_guard = MutationGuard::StorageFixture;
    Ok(repository)
}
/// Negative association vectors over an actual opaque Claim. The synthetic
/// fixture itself is separately required to fail operational capture.
pub(crate) fn assert_execution_association(claim:&AttemptClaim<'_>) {
    let execution = AttemptExecutionBinding::capture(claim).unwrap();
    assert!(execution.matches(claim));
    for field in 0..7 {
        let mut wrong = AttemptClaim {
            locator: claim.locator.clone(),attempt:claim.attempt.clone(),worker:claim.worker.clone(),
            number:claim.number,fence:claim.fence,generation:claim.generation.clone(),
            source:match claim.source {
                ClaimSource::Backtest(c)=>ClaimSource::Backtest(c),
                ClaimSource::Research(c)=>ClaimSource::Research(c),
                ClaimSource::Fixture=>panic!("real Claim required"),
            },
        };
        match field {
            0=>wrong.locator.kind=if claim.locator.kind==JobKind::Backtest {JobKind::Research} else {JobKind::Backtest},
            1=>wrong.locator.run="00000000-0000-4000-8000-000000000999".into(),
            2=>wrong.attempt="00000000-0000-4000-8000-000000000999".into(),
            3=>wrong.worker="00000000-0000-4000-8000-000000000999".into(),
            4=>wrong.number+=1,
            5=>wrong.fence+=1,
            _=>wrong.generation="f".repeat(64),
        }
        assert!(!execution.matches(&wrong),"operational field {field}");
    }
}
pub struct Fixture {
    pub registration: FrozenBindingRegistration,
    pub candidate: CompletedJobCandidate,
    pub claim: AttemptClaim<'static>,
    pub preparation_ns: u128,
}
impl Fixture {
    /// Relate synthetic storage input metadata to an actually admitted test Run.
    /// This never authenticates that metadata or constructs production proof.
    pub fn bind_original_run(&mut self, specification: &str, admission: &str) {
        self.registration.specification = specification.into();
        self.registration.admission = admission.into();
    }
    /// Pure recovery-decision vectors; no DB observation or Claim authority.
    pub fn unpublished(&self, state: &str, attempts: i32, active_attempts: i64) -> PublicationObservation {
        PublicationObservation::ConfirmedUnpublished(ConfirmedUnpublished {
            binding: self.registration.binding.clone(),
            revision: 1,
            state: state.into(),
            attempts,
            active_attempts,
        })
    }
    pub fn payload_bytes(&self) -> usize {
        self.candidate.members.iter().map(|m| m.content.len()).sum()
    }
    pub fn descriptor_rows(&self) -> u64 {
        self.candidate
            .members
            .iter()
            .map(|m| m.descriptor.rows().unwrap())
            .sum()
    }
    pub fn content_digest(&self) -> String {
        digest(
            &serde_json::to_vec(
                &self
                    .candidate
                    .members
                    .iter()
                    .map(|m| (&m.descriptor_raw, &m.content_fingerprint))
                    .collect::<Vec<_>>(),
            )
            .unwrap(),
        )
    }
    pub fn run_id(&self) -> &str {
        self.registration.binding.run_id()
    }
    pub fn locator(&self) -> RunLocator {
        RunLocator::new(self.registration.binding.kind(), self.run_id()).unwrap()
    }
    pub fn specification(&self) -> &str {
        &self.registration.specification
    }
    pub fn admission(&self) -> &str {
        &self.registration.admission
    }
    pub async fn write_registration(&self, tx: &Transaction<'_>) -> Result<()> {
        let binding = &self.registration.binding;
        let namespace = SemanticStoreId::new(binding.namespace()).unwrap();
        writer::write_registration(tx, &namespace, binding.owner(), &self.registration).await?;
        Ok(())
    }
    pub fn changed_candidate(&self) -> CompletedJobCandidate {
        let mut c = self.candidate.clone();
        c.members[0].content = encode(&json!({"changed":true}), CONTENT_LIMIT).unwrap();
        c.members[0].content_fingerprint = digest(c.members[0].content.as_bytes());
        finish(&mut c);
        c
    }
    pub fn changed_curve_candidate(&self, change: impl FnOnce(&mut Value)) -> CompletedJobCandidate {
        let mut candidate = self.candidate.clone();
        let curve = candidate
            .members
            .iter_mut()
            .find(|member| member.descriptor.kind() == MemberKind::CloseCurve)
            .unwrap();
        let mut body = document(&curve.content, CONTENT_LIMIT).unwrap();
        change(&mut body);
        curve.content = encode(&body, CONTENT_LIMIT).unwrap();
        curve.content_fingerprint = digest(curve.content.as_bytes());
        finish(&mut candidate);
        candidate
    }
    pub fn changed_facts_candidate(
        &self,
        change: impl FnOnce(&mut [(Value, Value)]),
    ) -> CompletedJobCandidate {
        let mut candidate = self.candidate.clone();
        let facts = candidate
            .members
            .iter_mut()
            .filter(|member| member.descriptor.kind() == MemberKind::ExecutionFacts)
            .collect::<Vec<_>>();
        let mut records = facts
            .iter()
            .map(|member| {
                (
                    document(&member.descriptor_raw, 8192).unwrap(),
                    document(&member.content, CONTENT_LIMIT).unwrap(),
                )
            })
            .collect::<Vec<_>>();
        change(&mut records);
        for (member, (descriptor, body)) in facts.into_iter().zip(records) {
            *member = prepared_member(descriptor, &body);
        }
        finish(&mut candidate);
        candidate
    }
    pub fn wrong_binding_candidate(&self) -> CompletedJobCandidate {
        let mut c = self.candidate.clone();
        let mut raw = c.binding.record();
        raw["initial_state"] = json!("0".repeat(64));
        c.binding = FrozenJobBinding::from_record(&raw).unwrap();
        finish(&mut c);
        c
    }
}
fn prepared_member(descriptor: Value, body: &Value) -> PreparedMember {
    let content = encode(body, CONTENT_LIMIT).unwrap();
    PreparedMember {
        descriptor_raw: encode(&descriptor, 8192).unwrap(),
        descriptor: serde_json::from_value(descriptor).unwrap(),
        content_fingerprint: digest(content.as_bytes()),
        content,
    }
}

fn finish(c: &mut CompletedJobCandidate) {
    c.manifest = super::reader::manifest(&c.binding, &c.members).unwrap();
    c.fingerprint = digest(c.manifest.as_bytes());
}
pub fn fixture(
    k: JobKind,
    scope: (&str, &str),
    run: &str,
    attempt: &str,
    worker: &str,
    parts: usize,
    padding: usize,
) -> Fixture {
    let (namespace, owner) = scope;
    let start = std::time::Instant::now();
    let pin = |c: char| c.to_string().repeat(64);
    let axis_rule = fact_axis_rule().unwrap();
    let curve_axis = json!([["FIXTURE.TEST", 1, 2, 2, 1]]);
    let mut specs = vec![
        json!({"key":"causal","kind":"CAUSAL_EVIDENCE","schema":pin('a'),"axis":null,"rows":1}),
    ];
    match k {
        JobKind::Backtest => {
            specs.push(json!({"key":"economic","kind":"ECONOMIC_RESULT","schema":pin('b'),"axis":null,"rows":1}));
            let axis = crate::application::factor_content::hash(&curve_axis).unwrap();
            specs.push(json!({"key":"curve","kind":"CLOSE_CURVE","schema":pin('c'),"axis":axis,"rows":1}));
            for i in 0..parts {
                specs.push(json!({"key":format!("facts-{i:04}"),"kind":"EXECUTION_FACTS","schema":pin('e'),"axis":null,"axis_rule":axis_rule,"rows":null}));
            }
        }
        JobKind::Research => {
            for (key, kind, axis, rows) in [
                ("calculation", "CALCULATION_VALUES", Some(pin('d')), 2),
                ("signals", "SIGNAL_VALUES", Some(pin('d')), 2),
                ("statistics", "STATISTICS", None, 1),
                ("report", "RESEARCH_REPORT", None, 1),
            ] {
                specs
                    .push(json!({"key":key,"kind":kind,"schema":pin('e'),"axis":axis,"rows":rows}));
            }
        }
    }
    let raw = json!({"schema_version":1,"kind":kind(k),"scope":{"namespace":namespace,"owner":owner,"run_id":run},"strategy_revision":pin('a'),"signal_graph":pin('b'),"factor_bindings":[],"kernel_artifact":pin('c'),"runtime_generation":pin('3'),"initial_state":pin('d'),"execution_configuration":pin('e'),"calendar":pin('f'),"fees":pin('1'),"market_rules":pin('2'),"market":{"dataset_snapshot":pin('3'),"source_revision":pin('4'),"bar_semantic":pin('5'),"instruments":["FIXTURE.TEST"],"start_ns":0,"end_ns":2,"versions":[pin('6')],"seals":[pin('7')],"segments":[pin('8')],"rows":2,"warmup_rows":1,"sample_rows":1,"axis":pin('9'),"content":pin('a')},"result_plan":{"kind":kind(k),"members":specs}});
    let binding = FrozenJobBinding::from_record(&raw).unwrap();
    let mut members = Vec::new();
    let mut sequence = 1;
    for descriptor in binding.result_plan().record()["members"]
        .as_array()
        .unwrap()
    {
        let mut descriptor = descriptor.clone();
        let body = if descriptor["kind"] == "EXECUTION_FACTS" {
            let rows = (sequence..sequence + 2)
                .map(|number| {
                    let family = match number {
                        1 => "OPEN",
                        number if number == parts * 2 => "END",
                        _ => "BAR",
                    };
                    json!({"schema_version":1,"sequence":number,"family":family,"body":{"padding":"x".repeat(padding)}})
                })
                .collect::<Vec<_>>();
            let axis = json!(rows
                .iter()
                .enumerate()
                .map(|(index, row)| fact_coordinate(row, sequence + index).unwrap())
                .collect::<Vec<_>>());
            sequence += rows.len();
            descriptor["rows"] = json!(rows.len());
            descriptor["axis"] = json!(crate::application::factor_content::hash(&axis).unwrap());
            json!({"schema_version":1,"kind":"EXECUTION_FACTS","axis":axis,"rows":rows})
        } else if descriptor["kind"] == "CLOSE_CURVE" {
            json!({"schema_version":1,"kind":"CLOSE_CURVE","axis":curve_axis,"rows":[{"bar_start_ns":"1","bar_end_ns":"2","nav":"10000","padding":"x".repeat(padding)}]})
        } else {
            json!({"fixture_only":true,"rows":descriptor["rows"],"padding":"x".repeat(padding)})
        };
        members.push(prepared_member(descriptor, &body));
    }
    members.sort_by(|a, b| a.descriptor.key().cmp(b.descriptor.key()));
    let mut candidate = CompletedJobCandidate {
        owner: None,
        binding: binding.clone(),
        members,
        // Research 候选必须携带完整 SHA-256 科学结果身份，Backtest 不得携带（writer::candidate 校验）。
        research_result: (k == JobKind::Research).then(|| digest(b"fixture research scientific identity")),
        manifest: String::new(),
        fingerprint: String::new(),
        ended_at: SystemTime::UNIX_EPOCH + Duration::from_secs(1_577_923_200),
    };
    finish(&mut candidate);
    Fixture {
        registration: FrozenBindingRegistration {
            binding,
            specification: pin('b'),
            admission: pin('c'),
        },
        candidate,
        claim: AttemptClaim {
            locator: RunLocator::new(k, run).unwrap(),
            attempt: attempt.into(),
            worker: worker.into(),
            number: 1,
            fence: 1,
            generation: pin('3'),
            source: ClaimSource::Fixture,
        },
        preparation_ns: start.elapsed().as_nanos(),
    }
}
