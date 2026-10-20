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
    os::{fd::OwnedFd, unix::net::UnixStream},
    path::Path,
    process::{Child, Command, Stdio},
    sync::{
        Arc, Mutex,
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
fn kill(child: &Arc<Mutex<Option<Child>>>) {
    if let Ok(mut slot) = child.lock()
        && let Some(mut process) = slot.take()
    {
        let _ = process.kill();
        let _ = process.wait();
    }
}
pub struct Cancellation {
    socket: UnixStream,
    child: Arc<Mutex<Option<Child>>>,
    cancelled: Arc<AtomicBool>,
}
impl Cancellation {
    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::SeqCst);
        let _ = self.socket.shutdown(Shutdown::Both);
        kill(&self.child);
    }
}
pub struct Worker {
    socket: UnixStream,
    child: Arc<Mutex<Option<Child>>>,
    cancelled: Arc<AtomicBool>,
    generation: String,
    artifact: String,
    sequence: u64,
    poisoned: bool,
    last_compute_ns: u64,
}
impl Worker {
    /// Attach an already owned, private connected transport. No Generation admission is granted.
    pub fn from_stream(socket: UnixStream, generation: String, artifact: String) -> Result<Self> {
        if !sha(&generation) || !sha(&artifact) {
            return Err(WorkerError::Invalid);
        }
        Ok(Self {
            socket,
            child: Arc::new(Mutex::new(None)),
            cancelled: Arc::new(AtomicBool::new(false)),
            generation,
            artifact,
            sequence: 0,
            poisoned: false,
            last_compute_ns: 0,
        })
    }
    /// Interpreter must belong to the caller's exact admitted materialization.
    pub fn spawn(
        interpreter: &Path,
        generation: String,
        artifact: String,
        deadline: Duration,
    ) -> Result<Self> {
        if !interpreter.is_absolute() || !sha(&generation) || !sha(&artifact) {
            return Err(WorkerError::Invalid);
        }
        let (parent, child) = UnixStream::pair().map_err(|_| WorkerError::Invalid)?;
        let input: OwnedFd = child.try_clone().map_err(|_| WorkerError::Invalid)?.into();
        let output: OwnedFd = child.into();
        let process = Command::new(interpreter)
            .args([
                "-B",
                "-I",
                "-m",
                "onlyalpha_calculation_worker.worker",
                "--generation",
                &generation,
            ])
            .env_clear()
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .current_dir("/")
            .stdin(Stdio::from(input))
            .stdout(Stdio::from(output))
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|_| WorkerError::Invalid)?;
        let mut worker = Self::from_stream(parent, generation, artifact)?;
        *worker.child.lock().map_err(|_| WorkerError::Invalid)? = Some(process);
        worker.handshake(deadline)?;
        Ok(worker)
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
            socket: self.socket.try_clone().map_err(|_| WorkerError::Invalid)?,
            child: self.child.clone(),
            cancelled: self.cancelled.clone(),
        })
    }
    pub(crate) fn poison<T>(&mut self, reason: &'static str) -> Result<T> {
        self.poisoned = true;
        let _ = self.socket.shutdown(Shutdown::Both);
        kill(&self.child);
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
        if data.is_empty() || data.len() > MAX_FRAME {
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
            if size == 0 || size > MAX_FRAME {
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
            let n = self
                .socket
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
            let n = self
                .socket
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
        kill(&self.child);
    }
}
