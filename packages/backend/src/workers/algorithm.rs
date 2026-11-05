//! Backend-owned algorithm children. No admission or automatic work retry.
use onlyalpha_calculation_bridge::{
    ChartInstallation, ProcessControl, ProcessState, Result, Worker, WorkerError,
};
use std::{
    os::{fd::OwnedFd, unix::net::UnixStream},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::{Arc, Mutex},
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
#[derive(Clone, Copy, PartialEq, Eq)]
enum WorkerRole {
    Research,
    Trading,
}
/// Exact interpreter selected by the owning composition, never ambient PATH.
pub struct AlgorithmProcess {
    interpreter: PathBuf,
}
impl AlgorithmProcess {
    fn new(interpreter: PathBuf) -> Self {
        Self { interpreter }
    }
    pub fn native_chart(
        executable: &std::fs::File,
        artifact: &str,
        completion: Box<dyn Send>,
    ) -> Result<Worker> {
        use std::os::fd::AsRawFd;

        // The inherited descriptor remains open through exec path resolution.
        // Close-on-exec prevents it from becoming a worker capability.
        let executable = format!("/proc/self/fd/{}", executable.as_raw_fd());
        let (parent, child) = UnixStream::pair().map_err(|_| WorkerError::Invalid)?;
        let input: OwnedFd = child.try_clone().map_err(|_| WorkerError::Invalid)?.into();
        let output: OwnedFd = child.into();
        let child = Command::new(&executable)
            .arg("--native-chart-worker")
            .env_clear()
            .current_dir("/")
            .stdin(Stdio::from(input))
            .stdout(Stdio::from(output))
            .stderr(Stdio::null())
            .spawn()
            .map_err(|_| WorkerError::Invalid)?;
        let control = Arc::new(Control(Arc::new(Mutex::new(ChildOwner {
            child: Some(child),
            completion: Some(completion),
            uncertain: false,
            failed_hold: None,
        }))));
        Worker::from_stream(parent, artifact.into(), artifact.into(), control, 8 * 1024 * 1024)
    }
    /// Static source resolver. The completion hold is retained until positive join.
    pub fn research_resolution(
        installation: &ChartInstallation,
        generation: &str,
        completion: Box<dyn Send>,
    ) -> Result<super::research_calculations::ResearchProcess> {
        installation.verify()?;
        let image = describe_research_runtime(env!("CARGO_PKG_VERSION"))?;
        let worker = Self::new(installation.root().join("bin/python")).spawn_bound(
            generation.into(),
            installation.artifact_fingerprint().into(),
            installation.root(),
            completion,
            WorkerRole::Research,
        )?;
        Ok(super::research_calculations::ResearchProcess::new(worker, image["artifact"].as_str().ok_or(WorkerError::Invalid)?.into(), image["version"].as_str().ok_or(WorkerError::Invalid)?.into()))
    }
    /// Installed numerical factory process, retaining its owning hold to join.
    pub fn trading(
        installation: &ChartInstallation,
        generation: &str,
        completion: Box<dyn Send>,
    ) -> Result<Worker> {
        installation.verify()?;
        Self::new(installation.root().join("bin/python")).spawn_bound(
            generation.into(),
            installation.artifact_fingerprint().into(),
            installation.root(),
            completion,
            WorkerRole::Trading,
        )
    }
    fn spawn_bound(
        &self,
        generation: String,
        artifact: String,
        installation: &Path,
        completion: Box<dyn Send>,
        role: WorkerRole,
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
            match role {
                WorkerRole::Research => "onlyalpha_backend_algorithms.research_worker",
                WorkerRole::Trading => "onlyalpha_backend_algorithms.trading_worker",
            },
            "--generation",
            &generation,
        ]);
        command
            .arg("--installation")
            .arg(installation)
            .arg("--artifact")
            .arg(&artifact);
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
            completion: Some(completion),
            uncertain: false,
            failed_hold: None,
        }))));
        Worker::from_stream(parent, generation, artifact, control, 8 * 1024 * 1024)
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

/// Exact native image descriptor for the existing Runtime builder, no activation.
pub fn describe_research_runtime(version: &str) -> Result<serde_json::Value> {
    let artifact = loaded_native_image_sha256()?;
    let target = if cfg!(all(target_os = "linux", target_arch = "aarch64")) {
        "aarch64-unknown-linux-gnu"
    } else if cfg!(all(target_os = "linux", target_arch = "x86_64")) {
        "x86_64-unknown-linux-gnu"
    } else {
        return Err(WorkerError::Invalid);
    };
    Ok(
        serde_json::json!({"protocol":"onlyalpha.research.executor/1","artifact":artifact,"target":target,"version":version}),
    )
}

/// Hash the actual Linux executable inode, including after its pathname has
/// been atomically replaced. /proc/self/exe is the kernel's selected image,
/// not an untrusted filesystem locator or a custom executable loader.
fn loaded_native_image_sha256() -> Result<String> {
    #[cfg(target_os = "linux")]
    {
        use sha2::{Digest, Sha256};
        use std::io::Read;
        use std::os::unix::fs::MetadataExt;
        const LIMIT: u64 = 128 * 1024 * 1024;
        let mut image = std::fs::File::open("/proc/self/exe").map_err(|_| WorkerError::Invalid)?;
        let metadata = image.metadata().map_err(|_| WorkerError::Invalid)?;
        if !metadata.is_file()
            || metadata.len() == 0
            || metadata.len() > LIMIT
            || metadata.mode() & 0o022 != 0
            || metadata.mode() & 0o111 == 0
            || (metadata.uid() != 0 && metadata.uid() != rustix::process::geteuid().as_raw())
        {
            return Err(WorkerError::Invalid);
        }
        let mut hash = Sha256::new();
        let mut read = 0_u64;
        let mut buffer = [0_u8; 8192];
        loop {
            let count = image.read(&mut buffer).map_err(|_| WorkerError::Invalid)?;
            if count == 0 {
                break;
            }
            read = read.checked_add(count as u64).ok_or(WorkerError::Invalid)?;
            if read > LIMIT {
                return Err(WorkerError::Invalid);
            }
            hash.update(&buffer[..count]);
        }
        let after = image.metadata().map_err(|_| WorkerError::Invalid)?;
        if read != metadata.len()
            || after.len() != metadata.len()
            || after.dev() != metadata.dev()
            || after.ino() != metadata.ino()
        {
            return Err(WorkerError::Invalid);
        }
        Ok(hash.finalize().iter().map(|b| format!("{b:02x}")).collect())
    }
    #[cfg(not(target_os = "linux"))]
    Err(WorkerError::Invalid)
}

/// Actual linked capabilities of this backend image. This is an Infrastructure
/// observation, not work admission, evidence publication or Backtest permission.
pub fn describe_native_runtime(version: &str) -> Result<serde_json::Value> {
    if version != env!("CARGO_PKG_VERSION") {
        return Err(WorkerError::Invalid);
    }
    let image = describe_research_runtime(version)?;
    let mut implementations =
        onlyalpha_calculation_bridge::native_predicates::implementation_manifests(
            image["artifact"].as_str().ok_or(WorkerError::Invalid)?,
        )
        .map_err(|_| WorkerError::Invalid)?;
    implementations.extend(onlyalpha_calculation_bridge::native_operators::implementation_manifests(image["artifact"].as_str().ok_or(WorkerError::Invalid)?).map_err(|_| WorkerError::Invalid)?);
    Ok(
        serde_json::json!({"schema_version":1,"protocol":"onlyalpha.native.runtime/1","image":image,
        "execution_capabilities":[{"kind":"RESEARCH","contract":"onlyalpha.research.executor/1"},{"kind":"BACKTEST","contract":"onlyalpha.backtest.executor/1"}],
        "implementations":implementations}),
    )
}

#[cfg(all(test, target_os = "linux"))]
mod native_runtime_tests {
    use super::*;
    use serde_json::json;
    use std::io::{BufRead, Read, Write};
    use std::os::unix::fs::PermissionsExt;

    // Shipping images are stripped and capped at 128 MiB. The debug libtest ELF
    // is larger; execute a stripped copy to test that same physical image policy.
    fn test_image(label: &str) -> (std::path::PathBuf, std::path::PathBuf) {
        let mut entropy = [0_u8; 8];
        getrandom::fill(&mut entropy).unwrap();
        let suffix = entropy
            .iter()
            .map(|v| format!("{v:02x}"))
            .collect::<String>();
        let root =
            std::env::temp_dir().join(format!("onlyalpha-{label}-{}-{suffix}", std::process::id()));
        std::fs::create_dir(&root).unwrap();
        let path = root.join("original");
        std::fs::copy(std::env::current_exe().unwrap(), &path).unwrap();
        let stripped = Command::new("strip")
            .arg("--strip-all")
            .arg(&path)
            .output()
            .unwrap();
        assert!(
            stripped.status.success(),
            "{}",
            String::from_utf8_lossy(&stripped.stderr)
        );
        assert!(std::fs::metadata(&path).unwrap().len() <= 128 * 1024 * 1024);
        (root, path)
    }
    #[test]
    fn native_descriptor_preserves_legacy_four_fields_and_complete_actual_capabilities() {
        const CHILD: &str = "ONLYALPHA_NATIVE_DESCRIPTOR_CHILD";
        if std::env::var_os(CHILD).is_none() {
            let (root, path) = test_image("native-descriptor");
            let output=Command::new(path).args(["--exact","workers::algorithm::native_runtime_tests::native_descriptor_preserves_legacy_four_fields_and_complete_actual_capabilities","--nocapture","--test-threads=1"]).env(CHILD,"1").output().unwrap();
            std::fs::remove_dir_all(root).unwrap();
            assert!(
                output.status.success(),
                "{}{}",
                String::from_utf8_lossy(&output.stdout),
                String::from_utf8_lossy(&output.stderr)
            );
            return;
        }
        let legacy = describe_research_runtime(env!("CARGO_PKG_VERSION")).unwrap();
        assert_eq!(legacy.as_object().unwrap().len(), 4);
        let native = describe_native_runtime(env!("CARGO_PKG_VERSION")).unwrap();
        assert_eq!(native["schema_version"], 1);
        assert_eq!(native["protocol"], "onlyalpha.native.runtime/1");
        assert_eq!(native["image"], legacy);
        assert_eq!(
            native["execution_capabilities"],
            json!([{"kind":"RESEARCH","contract":"onlyalpha.research.executor/1"},{"kind":"BACKTEST","contract":"onlyalpha.backtest.executor/1"}])
        );
        let image=legacy["artifact"].as_str().unwrap();
        let mut expected=onlyalpha_calculation_bridge::native_predicates::implementation_manifests(image).unwrap();
        expected.extend(onlyalpha_calculation_bridge::native_operators::implementation_manifests(image).unwrap());
        assert_eq!(native["implementations"],json!(expected));
        assert_eq!(native["implementations"].as_array().unwrap().len(),80);
    }
    #[test]
    fn loaded_image_survives_executable_path_replacement() {
        const CHILD: &str = "ONLYALPHA_NATIVE_IMAGE_REPLACEMENT_CHILD";
        if std::env::var_os(CHILD).is_some() {
            let before = describe_research_runtime(env!("CARGO_PKG_VERSION")).unwrap();
            println!("NATIVE_IMAGE_READY");
            std::io::stdout().flush().unwrap();
            std::io::stdin().read_exact(&mut [0_u8]).unwrap();
            assert_eq!(
                describe_research_runtime(env!("CARGO_PKG_VERSION")).unwrap(),
                before
            );
            assert_eq!(
                describe_native_runtime(env!("CARGO_PKG_VERSION")).unwrap()["image"],
                before
            );
            return;
        }
        let (root, path) = test_image("loaded-image");
        let mut child = Command::new(&path)
            .args(["--exact", "workers::algorithm::native_runtime_tests::loaded_image_survives_executable_path_replacement", "--nocapture", "--test-threads=1"])
            .env(CHILD, "1").stdin(Stdio::piped()).stdout(Stdio::piped()).spawn().unwrap();
        let mut stdout = std::io::BufReader::new(child.stdout.take().unwrap());
        loop {
            let mut line = String::new();
            assert!(
                stdout.read_line(&mut line).unwrap() > 0,
                "child exited before actual-image barrier"
            );
            if line.contains("NATIVE_IMAGE_READY") {
                break;
            }
        }
        let replacement = root.join("replacement");
        std::fs::write(
            &replacement,
            b"replaced locator bytes must never become running image proof",
        )
        .unwrap();
        std::fs::set_permissions(&replacement, std::fs::Permissions::from_mode(0o700)).unwrap();
        std::fs::rename(&replacement, &path).unwrap();
        child.stdin.take().unwrap().write_all(b"1").unwrap();
        let result = child.wait().unwrap();
        let mut remaining = String::new();
        stdout.read_to_string(&mut remaining).unwrap();
        std::fs::remove_dir_all(root).unwrap();
        assert!(result.success(), "{remaining}");
    }
}
