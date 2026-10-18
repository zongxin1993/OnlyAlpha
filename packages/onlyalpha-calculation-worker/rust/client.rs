//! Typed calculation lifecycle. The worker owns algorithm values and readiness.
use crate::process::sha;
use crate::{Result, Worker, WorkerError};
use onlyalpha_calculation::{Definition, ExecutionBinding, ExecutionCursor};
use onlyalpha_domain::{
    base::OnlyDomainModel,
    market::{OnlyBar, OnlyBarType},
    numeric::OnlyDecimal,
    time::OnlyTimestamp,
};
use onlyalpha_gateway_protocol::{
    CalculationCreate, CalculationInstance, CalculationResolve, CalculationRestore,
    CalculationUpdate, calculation_request::Operation,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{collections::BTreeMap, str::FromStr, time::Duration};
pub fn fingerprint(raw: &[u8]) -> String {
    Sha256::digest(raw)
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect()
}
fn invalid<T>(_: T) -> WorkerError {
    WorkerError::Invalid
}
fn keys(v: &Value, fields: &[&str]) -> bool {
    v.as_object()
        .is_some_and(|m| m.len() == fields.len() && fields.iter().all(|k| m.contains_key(*k)))
}
#[derive(Debug)]
pub struct Resolution {
    definition: Definition,
    native: String,
    implementation: String,
    parameters: Value,
}
impl Resolution {
    pub fn definition(&self) -> &Definition {
        &self.definition
    }
}
#[derive(Debug)]
pub struct Checkpoint {
    record: Value,
    fingerprint: String,
}
impl Checkpoint {
    pub fn from_bytes(raw: &[u8], expected: &str) -> Result<Self> {
        if !sha(expected) || raw.len() > crate::process::MAX_FRAME || fingerprint(raw) != expected {
            return Err(WorkerError::Invalid);
        }
        let record: Value = serde_json::from_slice(raw).map_err(invalid)?;
        if record.to_string().as_bytes() != raw
            || !keys(&record, &["schema_version", "cursor", "plugin_state"])
            || record["schema_version"].as_u64() != Some(1)
        {
            return Err(WorkerError::Invalid);
        }
        Ok(Self {
            record,
            fingerprint: expected.into(),
        })
    }
    pub fn to_bytes(&self) -> Vec<u8> {
        self.record.to_string().into_bytes()
    }
    pub fn fingerprint(&self) -> &str {
        &self.fingerprint
    }
}
struct Session {
    cursor: ExecutionCursor,
    bar_type: OnlyBarType,
    fresh: bool,
}
pub struct Client {
    worker: Worker,
    instances: BTreeMap<String, Session>,
}
impl Client {
    pub fn new(worker: Worker) -> Self {
        Self {
            worker,
            instances: BTreeMap::new(),
        }
    }
    pub fn last_compute_time(&self) -> Duration {
        self.worker.last_compute_time()
    }
    pub fn resolve(&mut self, parameters: Value, deadline: Duration) -> Result<Resolution> {
        if !parameters.is_object() {
            return Err(WorkerError::Invalid);
        }
        let result = self.worker.exchange(
            Operation::Resolve(CalculationResolve {
                parameters_json: parameters.to_string().into_bytes(),
            }),
            deadline,
        )?;
        let checked = (|| {
            if !keys(
                &result,
                &[
                    "schema_version",
                    "definition",
                    "definition_fingerprint",
                    "native_definition",
                    "implementation",
                ],
            ) || result["schema_version"].as_u64() != Some(1)
            {
                return Err(WorkerError::Invalid);
            }
            let definition = Definition::from_record(&result["definition"]).map_err(invalid)?;
            if definition.fingerprint()
                != result["definition_fingerprint"]
                    .as_str()
                    .ok_or(WorkerError::Invalid)?
                || definition.reference().kind() != "INDICATOR"
                || definition.reference().type_id() != "onlyalpha.indicator.sma"
                || definition.reference().semantic_version() != "1"
            {
                return Err(WorkerError::Invalid);
            }
            let native = result["native_definition"]
                .as_str()
                .filter(|v| sha(v))
                .ok_or(WorkerError::Invalid)?
                .into();
            let implementation = result["implementation"]
                .as_str()
                .filter(|v| sha(v))
                .ok_or(WorkerError::Invalid)?
                .into();
            Ok(Resolution {
                definition,
                native,
                implementation,
                parameters,
            })
        })();
        checked.or_else(|_| self.worker.poison("RESOLUTION"))
    }
    pub fn create(
        &mut self,
        scope: &str,
        resolution: Resolution,
        bar_type: OnlyBarType,
        source: &str,
        deadline: Duration,
    ) -> Result<()> {
        if self.instances.len() >= 16 || self.instances.contains_key(scope) || !sha(source) {
            return Err(WorkerError::Invalid);
        }
        let input = fingerprint(
            json!({"schema_version":1,"bar_type":bar_type.to_record(),"source_fingerprint":source})
                .to_string()
                .as_bytes(),
        );
        let binding = ExecutionBinding::new(
            [
                self.worker.generation().into(),
                self.worker.artifact().into(),
                resolution.definition.fingerprint(),
                resolution.native,
                resolution.implementation,
                input,
            ],
            scope,
        )
        .map_err(invalid)?;
        let cursor = ExecutionCursor::new(binding.clone());
        let result = self.worker.exchange(
            Operation::Create(CalculationCreate {
                binding_json: binding.to_record().to_string().into_bytes(),
                definition_json: resolution.definition.to_record().to_string().into_bytes(),
                bar_type_json: bar_type.to_record().to_string().into_bytes(),
                parameters_json: resolution.parameters.to_string().into_bytes(),
                source_fingerprint: source.into(),
            }),
            deadline,
        )?;
        if result != cursor.capture() {
            return self.worker.poison("CREATE_CURSOR");
        }
        self.instances.insert(
            scope.into(),
            Session {
                cursor,
                bar_type,
                fresh: true,
            },
        );
        Ok(())
    }
    fn instance(&self, scope: &str) -> Result<CalculationInstance> {
        let s = self.instances.get(scope).ok_or(WorkerError::Invalid)?;
        Ok(CalculationInstance {
            scope: scope.into(),
            revision: s.cursor.revision(),
        })
    }
    pub fn update(
        &mut self,
        scope: &str,
        bars: &[OnlyBar],
        deadline: Duration,
    ) -> Result<Vec<Value>> {
        let instance = self.instance(scope)?;
        let session = &self.instances[scope];
        if bars.iter().any(|b| {
            b.bar_type() != &session.bar_type || !*b.is_closed() || b.ts_event() != b.bar_end()
        }) {
            return Err(WorkerError::Invalid);
        }
        let times: Vec<_> = bars
            .iter()
            .map(|b| {
                OnlyTimestamp::from_datetime(*b.ts_event())
                    .to_unix_nanos()
                    .to_string()
            })
            .collect();
        let times_ref: Vec<_> = times.iter().map(String::as_str).collect();
        let records: Vec<_> = bars
            .iter()
            .map(|b| b.to_record().to_string().into_bytes())
            .collect();
        let input = fingerprint(&records.concat());
        let prepared = session
            .cursor
            .prepare(&times_ref, &input)
            .map_err(invalid)?;
        let result = self.worker.exchange(
            Operation::Update(CalculationUpdate {
                instance: Some(instance),
                bars_json: records,
                input_digest: input.clone(),
            }),
            deadline,
        )?;
        let checked = (|| {
            if !keys(&result, &["cursor", "input_digest", "points"])
                || result["input_digest"] != input
            {
                return Err(WorkerError::Invalid);
            }
            let points = result["points"].as_array().ok_or(WorkerError::Invalid)?;
            if points.len() != times.len() {
                return Err(WorkerError::Invalid);
            }
            let session = &self.instances[scope];
            let mut expected = session.cursor.capture();
            let samples = session.cursor.samples() + times.len() as u64;
            expected["revision"] = json!(session.cursor.revision() + 1);
            expected["samples"] = json!(samples);
            expected["last_event_ns"] = json!(times.last());
            if result["cursor"] != expected {
                return Err(WorkerError::Invalid);
            }
            for (index, p) in points.iter().enumerate() {
                if !keys(p, &["ts_event_ns", "samples", "value", "ready"])
                    || p["ts_event_ns"] != times[index]
                    || p["samples"].as_u64() != Some(session.cursor.samples() + index as u64 + 1)
                    || !p["ready"].is_boolean()
                {
                    return Err(WorkerError::Invalid);
                }
                if !p["value"].is_null() {
                    let value = p["value"]
                        .as_str()
                        .filter(|v| v.len() <= 4096)
                        .ok_or(WorkerError::Invalid)?;
                    OnlyDecimal::from_str(value).map_err(invalid)?;
                }
            }
            Ok(points.clone())
        })();
        let points = match checked {
            Ok(v) => v,
            Err(_) => return self.worker.poison("BATCH_RECEIPT"),
        };
        let session = self.instances.get_mut(scope).ok_or(WorkerError::Invalid)?;
        if session
            .cursor
            .commit(
                &prepared,
                &ExecutionBinding::from_record(&result["cursor"]["binding"]).map_err(invalid)?,
                result["cursor"]["revision"]
                    .as_u64()
                    .ok_or(WorkerError::Invalid)?,
                &times_ref,
                result["cursor"]["samples"]
                    .as_u64()
                    .ok_or(WorkerError::Invalid)?,
                result["input_digest"]
                    .as_str()
                    .ok_or(WorkerError::Invalid)?,
            )
            .is_err()
        {
            return self.worker.poison("BATCH_COMMIT");
        }
        session.fresh = false;
        Ok(points)
    }
    pub fn capture(&mut self, scope: &str, deadline: Duration) -> Result<Checkpoint> {
        let instance = self.instance(scope)?;
        let value = self
            .worker
            .exchange(Operation::Checkpoint(instance), deadline)?;
        if value["cursor"] != self.instances[scope].cursor.capture() {
            return self.worker.poison("CHECKPOINT_CURSOR");
        }
        let raw = value.to_string();
        match Checkpoint::from_bytes(raw.as_bytes(), &fingerprint(raw.as_bytes())) {
            Ok(v) => Ok(v),
            Err(_) => self.worker.poison("CHECKPOINT"),
        }
    }
    pub fn restore(
        &mut self,
        scope: &str,
        checkpoint: &Checkpoint,
        deadline: Duration,
    ) -> Result<()> {
        let instance = self.instance(scope)?;
        let session = &self.instances[scope];
        if !session.fresh {
            return Err(WorkerError::Invalid);
        }
        let mut proposed = ExecutionCursor::new(session.cursor.binding().clone());
        proposed
            .restore(&checkpoint.record["cursor"])
            .map_err(invalid)?;
        let value = self.worker.exchange(
            Operation::Restore(CalculationRestore {
                instance: Some(instance),
                checkpoint_json: checkpoint.to_bytes(),
                expected_sha256: checkpoint.fingerprint.clone(),
            }),
            deadline,
        )?;
        if value != proposed.capture() {
            return self.worker.poison("RESTORE_CURSOR");
        }
        let session = self.instances.get_mut(scope).ok_or(WorkerError::Invalid)?;
        session.cursor = proposed;
        session.fresh = false;
        Ok(())
    }
    pub fn reset(&mut self, scope: &str, deadline: Duration) -> Result<()> {
        let instance = self.instance(scope)?;
        let revision = instance
            .revision
            .checked_add(1)
            .ok_or(WorkerError::Invalid)?;
        let value = self.worker.exchange(Operation::Reset(instance), deadline)?;
        let mut expected = self.instances[scope].cursor.capture();
        expected["revision"] = json!(revision);
        expected["samples"] = json!(0);
        expected["last_event_ns"] = Value::Null;
        if value != expected {
            return self.worker.poison("RESET_CURSOR");
        }
        let session = self.instances.get_mut(scope).ok_or(WorkerError::Invalid)?;
        session.cursor.reset(revision).map_err(invalid)?;
        session.fresh = false;
        Ok(())
    }
    pub fn close(&mut self, scope: &str, deadline: Duration) -> Result<()> {
        let instance = self.instance(scope)?;
        let value = self.worker.exchange(Operation::Close(instance), deadline)?;
        if value != self.instances[scope].cursor.capture() {
            return self.worker.poison("CLOSE_CURSOR");
        }
        self.instances.remove(scope);
        Ok(())
    }
}
