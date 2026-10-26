//! Owned private channel. No automatic retry after an uncertain exchange.
use onlyalpha_gateway_protocol::{
    CalculationEmpty, CalculationRequest, CalculationResponse, calculation_request,
    calculation_response,
};
use prost::Message;
use serde_json::Value;
use std::{
    io::{Read, Write},
    net::Shutdown,
    os::unix::net::UnixStream,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};
pub const MAX_FRAME: usize = 1024 * 1024;
#[derive(Debug, PartialEq, Eq)]
pub enum WorkerError {
    Invalid,
    Rejected,
    Unknown(&'static str),
}
impl std::fmt::Display for WorkerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for WorkerError {}
pub type Result<T> = std::result::Result<T, WorkerError>;
pub(crate) fn sha(s: &str) -> bool {
    s.len() == 64
        && s.bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProcessState {
    Running,
    Uncertain,
    Joined,
}
/// Supplied by the process owner. A failed join retains ownership and capacity.
pub trait ProcessControl: Send + Sync {
    fn state(&self) -> ProcessState;
    fn terminate(&self, recover: bool) -> Result<()>;
}
/// Recreates only an explicitly bound transport for checkpoint candidate recovery.
/// This interface grants no Generation admission or work retry authority.
pub trait WorkerConnector: Send + Sync {
    fn connect(
        &self,
        generation: String,
        artifact: String,
        hosted: bool,
        deadline: Duration,
    ) -> Result<Worker>;
}
/// Validate the supplied port before an adapter constructs any canonical binding.
pub(crate) fn connect_exact(
    connector: &dyn WorkerConnector,
    generation: &str,
    artifact: &str,
    hosted: bool,
    deadline: Duration,
) -> Result<Worker> {
    let worker = connector.connect(generation.into(), artifact.into(), hosted, deadline)?;
    if worker.binding() != (generation, artifact) {
        return Err(WorkerError::Invalid);
    }
    Ok(worker)
}
#[derive(Clone)]
pub struct Cancellation {
    socket: Arc<UnixStream>,
    control: Arc<dyn ProcessControl>,
    cancelled: Arc<AtomicBool>,
}
impl Cancellation {
    pub fn state(&self) -> ProcessState {
        self.control.state()
    }
    pub fn cancel(&self) -> Result<()> {
        self.cancelled.store(true, Ordering::SeqCst);
        let _ = self.socket.shutdown(Shutdown::Both);
        self.control.terminate(false)
    }
    /// Explicitly drain the retained owner, including a poisoned owner. No work retry.
    pub fn drain(&self) -> Result<()> {
        self.cancelled.store(true, Ordering::SeqCst);
        let _ = self.socket.shutdown(Shutdown::Both);
        self.control.terminate(true)
    }
}
pub struct Worker {
    socket: Arc<UnixStream>,
    control: Arc<dyn ProcessControl>,
    cancelled: Arc<AtomicBool>,
    generation: String,
    artifact: String,
    sequence: u64,
    poisoned: bool,
    last_compute_ns: u64,
    max_frame: usize,
}
impl Worker {
    /// Attach an already owned, private connected transport. No Generation admission is granted.
    pub fn from_stream(
        socket: UnixStream,
        generation: String,
        artifact: String,
        control: Arc<dyn ProcessControl>,
        max_frame: usize,
    ) -> Result<Self> {
        if !sha(&generation) || !sha(&artifact) || !matches!(max_frame, MAX_FRAME | 8388608) {
            return Err(WorkerError::Invalid);
        }
        Ok(Self {
            socket: Arc::new(socket),
            control,
            cancelled: Arc::new(AtomicBool::new(false)),
            generation,
            artifact,
            sequence: 0,
            poisoned: false,
            last_compute_ns: 0,
            max_frame,
        })
    }
    pub fn exchange_chart(&mut self, request: Value, deadline: Duration) -> Result<Value> {
        self.exchange(
            calculation_request::Operation::Chart(onlyalpha_gateway_protocol::ChartBatch {
                request_json: request.to_string().into_bytes(),
            }),
            deadline,
        )
    }
    pub fn terminate(&self) -> Result<()> {
        self.cancellation()?.cancel()
    }
    /// Called only after the Chart consumer has retained this owner's control handle.
    pub fn handshake_chart(&mut self, deadline: Duration) -> Result<()> {
        let result = self.exchange(
            calculation_request::Operation::Handshake(CalculationEmpty {}),
            deadline,
        )?;
        if result
            != serde_json::json!({"schema_version":1,"max_rows":2001,"max_frame":8*1024*1024,"isolation":"LINUX_SECCOMP_NO_NEW_PRIVS_RLIMIT_V1"})
        {
            return self.poison("CHART_HANDSHAKE");
        }
        Ok(())
    }
    pub(crate) fn uncertain(&self) -> bool {
        self.poisoned || self.cancelled.load(Ordering::SeqCst)
    }
    pub fn last_compute_time(&self) -> Duration {
        Duration::from_nanos(self.last_compute_ns)
    }
    pub fn generation(&self) -> &str {
        &self.generation
    }
    pub fn artifact(&self) -> &str {
        &self.artifact
    }
    pub fn cancellation(&self) -> Result<Cancellation> {
        Ok(Cancellation {
            socket: self.socket.clone(),
            control: self.control.clone(),
            cancelled: self.cancelled.clone(),
        })
    }
    pub(crate) fn poison<T>(&mut self, reason: &'static str) -> Result<T> {
        self.poisoned = true;
        let _ = self.socket.shutdown(Shutdown::Both);
        let _ = self.control.terminate(false);
        Err(WorkerError::Unknown(reason))
    }
    pub fn handshake(&mut self, deadline: Duration) -> Result<Value> {
        let value = self.exchange(
            calculation_request::Operation::Handshake(CalculationEmpty {}),
            deadline,
        )?;
        if value != serde_json::json!({"schema_version":1,"max_batch":256,"max_instances":16}) {
            return self.poison("HANDSHAKE");
        }
        Ok(value)
    }
    pub fn binding(&self) -> (&str, &str) {
        (&self.generation, &self.artifact)
    }
    /// Closed pure simulation adapter, retaining this worker's exact identity and failure bounds.
    pub fn exchange_replay(&mut self, request: Value, deadline: Duration) -> Result<Value> {
        self.exchange(
            calculation_request::Operation::Replay(onlyalpha_gateway_protocol::BacktestExternal {
                request_json: request.to_string().into_bytes(),
            }),
            deadline,
        )
    }
    pub fn exchange(
        &mut self,
        operation: calculation_request::Operation,
        deadline: Duration,
    ) -> Result<Value> {
        if self.poisoned || self.cancelled.load(Ordering::SeqCst) {
            return self.poison("POISONED_OR_CANCELLED");
        }
        if deadline.is_zero() {
            return Err(WorkerError::Invalid);
        }
        let sequence = self.sequence.checked_add(1).ok_or(WorkerError::Invalid)?;
        let request = CalculationRequest {
            protocol_version: 1,
            generation: self.generation.clone(),
            sequence,
            operation: Some(operation),
        };
        let data = request.encode_to_vec();
        if data.is_empty() || data.len() > self.max_frame {
            return Err(WorkerError::Invalid);
        }
        self.sequence = sequence;
        let start = Instant::now();
        let result = (|| {
            let head = (data.len() as u32).to_be_bytes();
            self.write(&head, start, deadline)?;
            self.write(&data, start, deadline)?;
            let mut head = [0; 4];
            self.read(&mut head, start, deadline)?;
            let size = u32::from_be_bytes(head) as usize;
            if size == 0 || size > self.max_frame {
                return Err(WorkerError::Unknown("FRAME"));
            }
            let mut raw = vec![0; size];
            self.read(&mut raw, start, deadline)?;
            let response = std::panic::catch_unwind(|| CalculationResponse::decode(raw.as_slice()))
                .map_err(|_| WorkerError::Unknown("PROTOBUF_PANIC"))?
                .map_err(|_| WorkerError::Unknown("PROTOBUF"))?;
            if response.protocol_version != 1
                || response.generation != self.generation
                || response.sequence != sequence
                || response.artifact_fingerprint != self.artifact
            {
                return Err(WorkerError::Unknown("IDENTITY"));
            }
            Self::remaining(start, deadline)?;
            if self.cancelled.load(Ordering::SeqCst) {
                return Err(WorkerError::Unknown("CANCELLED"));
            }
            self.last_compute_ns = response.diagnostic_compute_ns;
            match response.outcome {
                Some(calculation_response::Outcome::Error(e)) if e.code == "REQUEST_REJECTED" => {
                    Err(WorkerError::Rejected)
                }
                Some(calculation_response::Outcome::Result(r)) => {
                    let value: Value = serde_json::from_slice(&r.record_json)
                        .map_err(|_| WorkerError::Unknown("RECORD"))?;
                    if value.to_string().as_bytes() != r.record_json {
                        return Err(WorkerError::Unknown("NONCANONICAL_RECORD"));
                    }
                    Self::remaining(start, deadline)?;
                    Ok(value)
                }
                _ => Err(WorkerError::Unknown("OUTCOME")),
            }
        })();
        match result {
            Err(WorkerError::Unknown(reason)) => self.poison(reason),
            result => result,
        }
    }
    fn remaining(start: Instant, deadline: Duration) -> Result<Duration> {
        deadline
            .checked_sub(start.elapsed())
            .filter(|v| !v.is_zero())
            .ok_or(WorkerError::Unknown("DEADLINE"))
    }
    fn write(&mut self, mut data: &[u8], start: Instant, deadline: Duration) -> Result<()> {
        while !data.is_empty() {
            self.socket
                .set_write_timeout(Some(Self::remaining(start, deadline)?))
                .map_err(|_| WorkerError::Unknown("IO"))?;
            let n = (&*self.socket)
                .write(data)
                .map_err(|_| WorkerError::Unknown("WRITE"))?;
            if n == 0 {
                return Err(WorkerError::Unknown("WRITE_EOF"));
            }
            data = &data[n..];
        }
        Ok(())
    }
    fn read(&mut self, mut data: &mut [u8], start: Instant, deadline: Duration) -> Result<()> {
        while !data.is_empty() {
            self.socket
                .set_read_timeout(Some(Self::remaining(start, deadline)?))
                .map_err(|_| WorkerError::Unknown("IO"))?;
            let n = (&*self.socket)
                .read(data)
                .map_err(|_| WorkerError::Unknown("READ"))?;
            if n == 0 {
                return Err(WorkerError::Unknown("READ_EOF"));
            }
            data = &mut data[n..];
        }
        Ok(())
    }
}
impl Drop for Worker {
    fn drop(&mut self) {
        let _ = self.socket.shutdown(Shutdown::Both);
        let _ = self.control.terminate(false);
    }
}

#[cfg(test)]
mod binding_tests {
    use super::*;
    struct Control(Arc<AtomicBool>);
    impl ProcessControl for Control {
        fn state(&self) -> ProcessState {
            if self.0.load(Ordering::SeqCst) {
                ProcessState::Joined
            } else {
                ProcessState::Running
            }
        }
        fn terminate(&self, _: bool) -> Result<()> {
            self.0.store(true, Ordering::SeqCst);
            Ok(())
        }
    }
    struct Connector {
        generation: String,
        artifact: String,
        joined: Arc<AtomicBool>,
    }
    impl WorkerConnector for Connector {
        fn connect(&self, _: String, _: String, _: bool, _: Duration) -> Result<Worker> {
            let (socket, _peer) = UnixStream::pair().unwrap();
            Worker::from_stream(
                socket,
                self.generation.clone(),
                self.artifact.clone(),
                Arc::new(Control(self.joined.clone())),
                MAX_FRAME,
            )
        }
    }
    #[test]
    fn substituted_valid_generation_or_artifact_is_rejected_and_closed_before_use() {
        for (generation, artifact) in [
            ("c".repeat(64), "b".repeat(64)),
            ("a".repeat(64), "c".repeat(64)),
        ] {
            let joined = Arc::new(AtomicBool::new(false));
            let connector = Connector {
                generation,
                artifact,
                joined: joined.clone(),
            };
            assert!(matches!(
                connect_exact(
                    &connector,
                    &"a".repeat(64),
                    &"b".repeat(64),
                    false,
                    Duration::from_secs(1)
                ),
                Err(WorkerError::Invalid)
            ));
            assert!(joined.load(Ordering::SeqCst));
        }
    }
    #[test]
    fn matching_connector_retains_its_lifecycle_until_consumer_drop() {
        let joined = Arc::new(AtomicBool::new(false));
        let connector = Connector {
            generation: "a".repeat(64),
            artifact: "b".repeat(64),
            joined: joined.clone(),
        };
        let worker = connect_exact(
            &connector,
            &connector.generation,
            &connector.artifact,
            true,
            Duration::from_secs(1),
        )
        .unwrap();
        assert_eq!(
            worker.binding(),
            (connector.generation.as_str(), connector.artifact.as_str())
        );
        assert!(!joined.load(Ordering::SeqCst));
        drop(worker);
        assert!(joined.load(Ordering::SeqCst));
    }
}
