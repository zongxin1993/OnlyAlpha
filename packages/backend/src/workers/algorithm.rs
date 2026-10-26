//! Backend-owned algorithm children. No admission or automatic work retry.
use onlyalpha_calculation_bridge::{
    ChartInstallation, ProcessControl, ProcessState, Result, Worker, WorkerConnector, WorkerError,
};
use std::{
    os::{fd::OwnedFd, unix::net::UnixStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
    time::Duration,
};
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

struct Control(Arc<Mutex<ChildOwner>>);
impl ProcessControl for Control {
    fn state(&self) -> ProcessState {
        match self.0.lock() {
            Ok(owner) if owner.uncertain => ProcessState::Uncertain,
            Ok(owner) if owner.child.is_some() => ProcessState::Running,
            Ok(_) => ProcessState::Joined,
            Err(_) => ProcessState::Uncertain,
        }
    }
    fn terminate(&self, recover: bool) -> Result<()> {
        terminate(&self.0, recover)
    }
}
/// Exact interpreter selected by the owning composition, never ambient PATH.
pub struct AlgorithmProcess {
    interpreter: PathBuf,
}
impl AlgorithmProcess {
    pub fn new(interpreter: PathBuf) -> Self {
        Self { interpreter }
    }
    pub fn spawn(
        interpreter: &Path,
        generation: String,
        artifact: String,
        deadline: Duration,
    ) -> Result<Worker> {
        Self::new(interpreter.into()).connect(generation, artifact, false, deadline)
    }
    pub fn spawn_hosted(
        interpreter: &Path,
        generation: String,
        artifact: String,
        deadline: Duration,
    ) -> Result<Worker> {
        Self::new(interpreter.into()).connect(generation, artifact, true, deadline)
    }
    pub fn chart(installation: &ChartInstallation, completion: Box<dyn Send>) -> Result<Worker> {
        installation.verify()?;
        Self::new(installation.root().join("bin/python")).spawn_bound(
            installation.artifact_fingerprint().into(),
            installation.artifact_fingerprint().into(),
            false,
            Some(installation.root()),
            Some(completion),
        )
    }
    fn spawn_bound(
        &self,
        generation: String,
        artifact: String,
        hosted: bool,
        installation: Option<&Path>,
        completion: Option<Box<dyn Send>>,
    ) -> Result<Worker> {
        let sha = |s: &str| {
            s.len() == 64
                && s.bytes()
                    .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
        };
        if !self.interpreter.is_absolute() || !sha(&generation) || !sha(&artifact) {
            return Err(WorkerError::Invalid);
        }
        let (parent, child) = UnixStream::pair().map_err(|_| WorkerError::Invalid)?;
        let input: OwnedFd = child.try_clone().map_err(|_| WorkerError::Invalid)?.into();
        let output: OwnedFd = child.into();
        let mut command = Command::new(&self.interpreter);
        command.args([
            "-B",
            "-I",
            "-m",
            if installation.is_some() {
                "onlyalpha_backend_algorithms.chart_worker"
            } else {
                "onlyalpha_calculation_worker.worker"
            },
            "--generation",
            &generation,
        ]);
        if let Some(root) = installation {
            command.arg("--installation").arg(root);
        }
        if hosted {
            command.arg("--hosted-generation");
        }
        let child = command
            .env_clear()
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .current_dir("/")
            .stdin(Stdio::from(input))
            .stdout(Stdio::from(output))
            .stderr(Stdio::inherit())
            .spawn()
            .map_err(|_| WorkerError::Invalid)?;
        let control = Arc::new(Control(Arc::new(Mutex::new(ChildOwner {
            child: Some(child),
            completion,
            uncertain: false,
            failed_hold: None,
        }))));
        Worker::from_stream(
            parent,
            generation,
            artifact,
            control,
            if installation.is_some() {
                8 * 1024 * 1024
            } else {
                1024 * 1024
            },
        )
    }
}
impl WorkerConnector for AlgorithmProcess {
    fn connect(
        &self,
        generation: String,
        artifact: String,
        hosted: bool,
        deadline: Duration,
    ) -> Result<Worker> {
        let mut worker = self.spawn_bound(generation, artifact, hosted, None, None)?;
        worker.handshake(deadline)?;
        Ok(worker)
    }
}
#[cfg(test)]
mod lifecycle_faults {
    use super::*;
    use std::sync::atomic::Ordering;
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
    fn owned() -> (
        Worker,
        onlyalpha_calculation_bridge::Cancellation,
        Arc<std::sync::atomic::AtomicUsize>,
        Arc<Mutex<ChildOwner>>,
    ) {
        let (socket, _peer) = UnixStream::pair().unwrap();
        let count = Arc::new(std::sync::atomic::AtomicUsize::new(1));
        let child = Command::new("/bin/cat")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .spawn()
            .unwrap();
        let owner = Arc::new(Mutex::new(ChildOwner {
            child: Some(child),
            completion: Some(Box::new(Guard(count.clone()))),
            uncertain: false,
            failed_hold: None,
        }));
        let worker = Worker::from_stream(
            socket,
            "a".repeat(64),
            "b".repeat(64),
            Arc::new(Control(owner.clone())),
            1024 * 1024,
        )
        .unwrap();
        let control = worker.cancellation().unwrap();
        (worker, control, count, owner)
    }
    #[test]
    fn actual_child_and_capacity_survive_kill_wait_failures_and_last_control_drop() {
        for kill_failure in [true, false] {
            let (worker, control, count, owner) = owned();
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
        let (worker, control, count, owner) = owned();
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
            let (worker, control, count, _owner) = owned();
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
