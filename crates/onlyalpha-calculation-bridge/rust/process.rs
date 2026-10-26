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
fn terminate_owned<T>(
    slot: &mut Option<T>,
    kill: impl FnOnce(&mut T) -> std::io::Result<()>,
    wait: impl FnOnce(&mut T) -> std::io::Result<()>,
    exited: impl FnOnce(&mut T) -> std::io::Result<bool>,
) -> Result<()> {
    if let Some(process) = slot.as_mut() {
        if kill(process).is_err() {
            // A process that exited before kill is still a positive join through try_wait.
            if !exited(process).map_err(|_| WorkerError::Unknown("PROCESS_WAIT"))? {
                return Err(WorkerError::Unknown("PROCESS_KILL"));
            }
        } else {
            wait(process).map_err(|_| WorkerError::Unknown("PROCESS_WAIT"))?;
        }
        *slot = None;
    }
    Ok(())
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProcessState {
    Running,
    Uncertain,
    Joined,
}
struct ChildOwner {
    child: Option<Child>,
    completion: Option<Box<dyn Send>>,
    uncertain: bool,
    // Failed cleanup must survive the last caller's Drop. Explicit drain of this
    // same owner clears the hold only after wait; it never spawns/retries work.
    failed_hold: Option<Arc<Mutex<ChildOwner>>>,
}
fn terminate(owner: &Arc<Mutex<ChildOwner>>, recover: bool) -> Result<()> {
    terminate_with(owner, recover, |child| {
        terminate_owned(
            child,
            Child::kill,
            |p| p.wait().map(|_| ()),
            |p| p.try_wait().map(|v| v.is_some()),
        )
    })
}
fn terminate_with(
    owner: &Arc<Mutex<ChildOwner>>,
    recover: bool,
    finish: impl FnOnce(&mut Option<Child>) -> Result<()>,
) -> Result<()> {
    let mut slot = match owner.lock() {
        Ok(slot) => slot,
        Err(poison) => {
            let mut slot = poison.into_inner();
            slot.uncertain = true;
            slot.failed_hold = Some(owner.clone());
            if !recover {
                return Err(WorkerError::Unknown("PROCESS_OWNER_POISONED"));
            }
            slot
        }
    };
    slot.uncertain = true;
    slot.failed_hold = Some(owner.clone());
    finish(&mut slot.child)?;
    slot.completion = None;
    slot.uncertain = false;
    slot.failed_hold = None;
    if recover {
        owner.clear_poison();
    }
    Ok(())
}
#[derive(Clone)]
pub struct Cancellation {
    socket: Arc<UnixStream>,
    child: Arc<Mutex<ChildOwner>>,
    cancelled: Arc<AtomicBool>,
}
impl Cancellation {
    pub fn state(&self) -> ProcessState {
        match self.child.lock() {
            Ok(owner) if owner.uncertain => ProcessState::Uncertain,
            Ok(owner) if owner.child.is_some() => ProcessState::Running,
            Ok(_) => ProcessState::Joined,
            Err(_) => ProcessState::Uncertain,
        }
    }
    pub fn cancel(&self) -> Result<()> {
        self.cancelled.store(true, Ordering::SeqCst);
        let _ = self.socket.shutdown(Shutdown::Both);
        terminate(&self.child, false)
    }
    /// Explicitly drain the retained owner, including a poisoned owner. No work retry.
    pub fn drain(&self) -> Result<()> {
        self.cancelled.store(true, Ordering::SeqCst);
        let _ = self.socket.shutdown(Shutdown::Both);
        terminate(&self.child, true)
    }
}
pub struct Worker {
    socket: Arc<UnixStream>,
    child: Arc<Mutex<ChildOwner>>,
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
    pub fn from_stream(socket: UnixStream, generation: String, artifact: String) -> Result<Self> {
        if !sha(&generation) || !sha(&artifact) {
            return Err(WorkerError::Invalid);
        }
        Ok(Self {
            socket: Arc::new(socket),
            child: Arc::new(Mutex::new(ChildOwner {
                child: None,
                completion: None,
                uncertain: false,
                failed_hold: None,
            })),
            cancelled: Arc::new(AtomicBool::new(false)),
            generation,
            artifact,
            sequence: 0,
            poisoned: false,
            last_compute_ns: 0,
            max_frame: MAX_FRAME,
        })
    }
    /// Interpreter must belong to the caller's exact admitted materialization.
    pub fn spawn(
        interpreter: &Path,
        generation: String,
        artifact: String,
        deadline: Duration,
    ) -> Result<Self> {
        Self::spawn_bound(
            interpreter,
            generation,
            artifact,
            deadline,
            false,
            None,
            None,
        )
    }
    /// Formal work requires the installed Generation context; it never uses comparison registrations.
    pub fn spawn_hosted(
        interpreter: &Path,
        generation: String,
        artifact: String,
        deadline: Duration,
    ) -> Result<Self> {
        Self::spawn_bound(
            interpreter,
            generation,
            artifact,
            deadline,
            true,
            None,
            None,
        )
    }
    /// Disposable Chart composition, never a Trading Runtime Generation.
    pub fn spawn_chart(
        interpreter: &Path,
        installation: &Path,
        artifact: String,
        completion: Box<dyn Send>,
    ) -> Result<Self> {
        Self::spawn_bound(
            interpreter,
            artifact.clone(),
            artifact,
            Duration::ZERO,
            false,
            Some(installation),
            Some(completion),
        )
    }
    pub fn exchange_chart(&mut self, request: Value, deadline: Duration) -> Result<Value> {
        self.exchange(
            calculation_request::Operation::Chart(onlyalpha_gateway_protocol::ChartBatch {
                request_json: request.to_string().into_bytes(),
            }),
            deadline,
        )
    }
    fn spawn_bound(
        interpreter: &Path,
        generation: String,
        artifact: String,
        deadline: Duration,
        hosted: bool,
        chart_installation: Option<&Path>,
        completion: Option<Box<dyn Send>>,
    ) -> Result<Self> {
        if !interpreter.is_absolute() || !sha(&generation) || !sha(&artifact) {
            return Err(WorkerError::Invalid);
        }
        let (parent, child) = UnixStream::pair().map_err(|_| WorkerError::Invalid)?;
        let input: OwnedFd = child.try_clone().map_err(|_| WorkerError::Invalid)?.into();
        let output: OwnedFd = child.into();
        let mut command = Command::new(interpreter);
        command.args([
            "-B",
            "-I",
            "-m",
            if chart_installation.is_some() {
                "onlyalpha_calculation_worker.chart_worker"
            } else {
                "onlyalpha_calculation_worker.worker"
            },
            "--generation",
            &generation,
        ]);
        if let Some(installation) = chart_installation {
            command.arg("--installation").arg(installation);
        }
        if hosted {
            command.arg("--hosted-generation");
        }
        let mut worker = Self::from_stream(parent, generation, artifact)?;
        let owner = Arc::get_mut(&mut worker.child)
            .ok_or(WorkerError::Invalid)?
            .get_mut()
            .map_err(|_| WorkerError::Invalid)?;
        owner.completion = completion;
        owner.child = Some(
            command
                .env_clear()
                .env("PYTHONDONTWRITEBYTECODE", "1")
                .current_dir("/")
                .stdin(Stdio::from(input))
                .stdout(Stdio::from(output))
                .stderr(Stdio::inherit())
                .spawn()
                .map_err(|_| WorkerError::Invalid)?,
        );
        if chart_installation.is_some() {
            worker.max_frame = 8 * 1024 * 1024;
        } else {
            worker.handshake(deadline)?;
        }
        Ok(worker)
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
            child: self.child.clone(),
            cancelled: self.cancelled.clone(),
        })
    }
    pub(crate) fn poison<T>(&mut self, reason: &'static str) -> Result<T> {
        self.poisoned = true;
        let _ = self.socket.shutdown(Shutdown::Both);
        let _ = terminate(&self.child, false);
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
        let _ = terminate(&self.child, false);
    }
}

#[cfg(test)]
mod lifecycle_faults {
    use super::*;
    #[test]
    fn kill_and_wait_failure_retain_the_same_owner_until_positive_join() {
        for failed_kill in [true, false] {
            let mut slot = Some(71u32);
            let result = terminate_owned(
                &mut slot,
                |_| {
                    if failed_kill {
                        Err(std::io::Error::other("controlled kill failure"))
                    } else {
                        Ok(())
                    }
                },
                |_| Err(std::io::Error::other("controlled wait failure")),
                |_| Ok(false),
            );
            assert!(result.is_err());
            assert_eq!(slot, Some(71));
            assert!(terminate_owned(&mut slot, |_| Ok(()), |_| Ok(()), |_| Ok(false)).is_ok());
            assert_eq!(slot, None);
        }
    }
    struct Guard(Arc<std::sync::atomic::AtomicUsize>);
    impl Drop for Guard {
        fn drop(&mut self) {
            self.0.fetch_sub(1, Ordering::SeqCst);
        }
    }
    fn owned() -> (Worker, Cancellation, Arc<std::sync::atomic::AtomicUsize>) {
        let (socket, _peer) = UnixStream::pair().unwrap();
        let worker = Worker::from_stream(socket, "a".repeat(64), "b".repeat(64)).unwrap();
        let count = Arc::new(std::sync::atomic::AtomicUsize::new(1));
        let child = Command::new("/bin/cat")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .spawn()
            .unwrap();
        {
            let mut owner = worker.child.lock().unwrap();
            owner.child = Some(child);
            owner.completion = Some(Box::new(Guard(count.clone())));
        }
        let control = worker.cancellation().unwrap();
        (worker, control, count)
    }
    #[test]
    fn actual_child_and_capacity_survive_kill_wait_failures_and_last_control_drop() {
        for kill_failure in [true, false] {
            let (worker, control, count) = owned();
            let owner = worker.child.clone();
            assert!(
                terminate_with(&owner, false, |slot| terminate_owned(
                    slot,
                    |child| if kill_failure {
                        Err(std::io::Error::other("kill fault"))
                    } else {
                        child.kill()
                    },
                    |_| Err(std::io::Error::other("wait fault")),
                    |_| Ok(false)
                ))
                .is_err()
            );
            assert_eq!(control.state(), ProcessState::Uncertain);
            assert_eq!(count.load(Ordering::SeqCst), 1);
            assert!(owner.lock().unwrap().child.is_some());
            // Simulate disappearance of all callers after failed best effort. The
            // failed lifecycle still owns its Child/permit and can be drained.
            let weak = Arc::downgrade(&owner);
            // Poison makes Worker Drop preserve the injected uncertain lifecycle.
            let _ = std::panic::catch_unwind(|| {
                let _lock = owner.lock().unwrap();
                panic!("drop barrier")
            });
            drop(worker);
            drop(control);
            drop(owner);
            let retained = weak.upgrade().unwrap();
            terminate(&retained, true).unwrap();
            assert_eq!(count.load(Ordering::SeqCst), 0);
            assert!(retained.lock().unwrap().child.is_none());
            drop(retained);
        }
    }
    #[test]
    fn poison_is_explicit_and_only_explicit_drain_recovers_same_child() {
        let (worker, control, count) = owned();
        let owner = worker.child.clone();
        let _ = std::panic::catch_unwind(|| {
            let _lock = owner.lock().unwrap();
            panic!("controlled owner poison")
        });
        assert!(control.cancel().is_err());
        assert_eq!(control.state(), ProcessState::Uncertain);
        assert_eq!(count.load(Ordering::SeqCst), 1);
        drop(worker); // best effort cannot recover a poisoned owner
        assert_eq!(count.load(Ordering::SeqCst), 1);
        control.drain().unwrap();
        assert_eq!(control.state(), ProcessState::Joined);
        assert_eq!(count.load(Ordering::SeqCst), 0);
        control.drain().unwrap(); // reentry cannot release twice
    }
    #[test]
    fn normal_cancel_and_worker_drop_release_only_after_join() {
        for cancel in [true, false] {
            let (worker, control, count) = owned();
            if cancel {
                control.cancel().unwrap();
            }
            drop(worker);
            assert_eq!(control.state(), ProcessState::Joined);
            assert_eq!(count.load(Ordering::SeqCst), 0);
            control.cancel().unwrap();
        }
    }
}
