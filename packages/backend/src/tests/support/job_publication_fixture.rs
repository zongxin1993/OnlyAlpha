//! Synthetic storage-owner fixture, compiled ONLY in test artifacts. It proves
//! repository mechanics, never real engine completion or factor certification.
use super::model::ClaimSource;
use super::*;
use serde_json::json;
use std::time::{Duration, SystemTime};
pub struct Fixture {
    pub registration: FrozenBindingRegistration,
    pub candidate: CompletedJobCandidate,
    pub claim: AttemptClaim<'static>,
    pub preparation_ns: u128,
}
impl Fixture {
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
    pub fn changed_candidate(&self) -> CompletedJobCandidate {
        let mut c = self.candidate.clone();
        c.members[0].content = encode(&json!({"changed":true}), CONTENT_LIMIT).unwrap();
        c.members[0].content_fingerprint = digest(c.members[0].content.as_bytes());
        finish(&mut c);
        c
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
    let axis_rule = digest(b"fixture-ordered-event-index-v1");
    let mut specs = vec![
        json!({"key":"causal","kind":"CAUSAL_EVIDENCE","schema":pin('a'),"axis":null,"rows":1}),
    ];
    match k {
        JobKind::Backtest => {
            specs.push(json!({"key":"economic","kind":"ECONOMIC_RESULT","schema":pin('b'),"axis":null,"rows":1}));
            specs.push(json!({"key":"curve","kind":"CLOSE_CURVE","schema":pin('c'),"axis":pin('d'),"rows":1}));
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
    for descriptor in binding.result_plan().record()["members"]
        .as_array()
        .unwrap()
    {
        let mut descriptor = descriptor.clone();
        if descriptor["rows"].is_null() {
            descriptor["rows"] = json!(2);
            descriptor["axis"] = json!(digest(b"fixture actual ordered event axis 0,1"));
        }
        let content = encode(
            &json!({"fixture_only":true,"rows":descriptor["rows"],"padding":"x".repeat(padding)}),
            CONTENT_LIMIT,
        )
        .unwrap();
        members.push(PreparedMember {
            descriptor: serde_json::from_value(descriptor.clone()).unwrap(),
            descriptor_raw: encode(&descriptor, 8192).unwrap(),
            content_fingerprint: digest(content.as_bytes()),
            content,
        });
    }
    members.sort_by(|a, b| a.descriptor.key().cmp(b.descriptor.key()));
    let mut candidate = CompletedJobCandidate {
        binding: binding.clone(),
        members,
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
