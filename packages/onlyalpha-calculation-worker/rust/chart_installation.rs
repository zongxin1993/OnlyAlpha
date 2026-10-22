//! Actual sealed minimal Python installation, never a descriptor's assertion.
use crate::{Result, Worker, WorkerError};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::{
    collections::BTreeSet,
    os::unix::fs::PermissionsExt,
    path::{Component, Path, PathBuf},
};
fn hash(bytes: &[u8]) -> String {
    Sha256::digest(bytes)
        .iter()
        .map(|v| format!("{v:02x}"))
        .collect()
}
pub struct ChartInstallation {
    root: PathBuf,
    artifact: String,
}
impl ChartInstallation {
    pub fn open(root: &Path, artifact: &str) -> Result<Self> {
        if !root.is_absolute()
            || !super::process::sha(artifact)
            || root.canonicalize().map_err(|_| WorkerError::Invalid)? != root
        {
            return Err(WorkerError::Invalid);
        }
        let result = Self {
            root: root.into(),
            artifact: artifact.into(),
        };
        result.verify()?;
        Ok(result)
    }
    pub fn distribution_version(&self) -> Result<String> {
        let value: Value = serde_json::from_slice(
            &std::fs::read(self.root.join("algorithm-installation.json"))
                .map_err(|_| WorkerError::Invalid)?,
        )
        .map_err(|_| WorkerError::Invalid)?;
        value["distribution_version"]
            .as_str()
            .map(str::to_owned)
            .ok_or(WorkerError::Invalid)
    }
    pub fn require_resource(&self, relative: &str, digest: &str) -> Result<()> {
        let raw = std::fs::read(self.root.join("algorithm-installation.json"))
            .map_err(|_| WorkerError::Invalid)?;
        if hash(&raw) != self.artifact {
            return Err(WorkerError::Invalid);
        }
        let manifest: Value = serde_json::from_slice(&raw).map_err(|_| WorkerError::Invalid)?;
        let suffix = format!("/site-packages/{relative}");
        let matches = manifest["files"]
            .as_object()
            .ok_or(WorkerError::Invalid)?
            .iter()
            .filter(|(name, _)| name.ends_with(&suffix))
            .collect::<Vec<_>>();
        if matches.len() != 1 || matches[0].1.as_str() != Some(digest) {
            return Err(WorkerError::Invalid);
        }
        Ok(())
    }
    pub fn artifact_fingerprint(&self) -> &str {
        &self.artifact
    }
    pub fn verify(&self) -> Result<()> {
        let invalid = || WorkerError::Unknown("CHART_INSTALLATION_UNAVAILABLE");
        for relative in ["algorithm-installation.json", "bin/python"] {
            let path = self.root.join(relative);
            let meta = std::fs::symlink_metadata(&path).map_err(|_| invalid())?;
            if !meta.is_file() || meta.permissions().mode() & 0o222 != 0 {
                return Err(invalid());
            }
        }
        let bytes =
            std::fs::read(self.root.join("algorithm-installation.json")).map_err(|_| invalid())?;
        if bytes.len() > 8 * 1024 * 1024 || hash(&bytes) != self.artifact {
            return Err(invalid());
        }
        let manifest: Value = serde_json::from_slice(&bytes).map_err(|_| invalid())?;
        if manifest["schema_version"] != 1 || manifest["kind"] != "ONLYALPHA_ALGORITHM_INSTALLATION"
        {
            return Err(invalid());
        }
        let config = manifest["environment_files"]
            .as_object()
            .ok_or_else(invalid)?;
        if config.len() != 1 || !config.contains_key("pyvenv.cfg") {
            return Err(invalid());
        }
        let cfg = self.root.join("pyvenv.cfg");
        let meta = std::fs::symlink_metadata(&cfg).map_err(|_| invalid())?;
        if !meta.is_file()
            || meta.permissions().mode() & 0o222 != 0
            || config["pyvenv.cfg"].as_str()
                != Some(hash(&std::fs::read(cfg).map_err(|_| invalid())?).as_str())
        {
            return Err(invalid());
        }
        let runtime = manifest["runtime_files"].as_object().ok_or_else(invalid)?;
        if runtime.len() != 3 {
            return Err(invalid());
        }
        for (name, digest) in runtime {
            let path = Path::new(name);
            if !path.is_absolute()
                || digest.as_str()
                    != Some(hash(&std::fs::read(path).map_err(|_| invalid())?).as_str())
            {
                return Err(invalid());
            }
        }
        let files = manifest["files"].as_object().ok_or_else(invalid)?;
        if files.is_empty() || files.len() > 10000 {
            return Err(invalid());
        }
        let mut expected = BTreeSet::new();
        let mut total = 0usize;
        for (relative, digest) in files {
            let path = Path::new(relative);
            if path
                .components()
                .any(|c| !matches!(c, Component::Normal(_)))
                || relative.ends_with(".pth")
                || !relative.contains("/site-packages/")
            {
                return Err(invalid());
            }
            let path = self.root.join(path);
            let m = std::fs::symlink_metadata(&path).map_err(|_| invalid())?;
            if !m.is_file() || m.permissions().mode() & 0o222 != 0 {
                return Err(invalid());
            }
            total = total
                .checked_add(usize::try_from(m.len()).map_err(|_| invalid())?)
                .ok_or_else(invalid)?;
            if total > 1024 * 1024 * 1024
                || digest.as_str()
                    != Some(hash(&std::fs::read(&path).map_err(|_| invalid())?).as_str())
            {
                return Err(invalid());
            }
            expected.insert(path);
        }
        let mut actual = BTreeSet::new();
        let mut pending = vec![self.root.join("lib")];
        while let Some(directory) = pending.pop() {
            let m = std::fs::symlink_metadata(&directory).map_err(|_| invalid())?;
            if !m.is_dir() || m.permissions().mode() & 0o222 != 0 {
                return Err(invalid());
            }
            for entry in std::fs::read_dir(directory).map_err(|_| invalid())? {
                let entry = entry.map_err(|_| invalid())?;
                let ty = entry.file_type().map_err(|_| invalid())?;
                if ty.is_symlink() {
                    return Err(invalid());
                }
                if ty.is_dir() {
                    pending.push(entry.path());
                } else if ty.is_file() {
                    actual.insert(entry.path());
                } else {
                    return Err(invalid());
                }
            }
        }
        if actual != expected
            || manifest["interpreter_sha256"].as_str()
                != Some(
                    hash(&std::fs::read(self.root.join("bin/python")).map_err(|_| invalid())?)
                        .as_str(),
                )
        {
            return Err(invalid());
        }
        Ok(())
    }
    pub fn spawn(&self, completion: Box<dyn Send>) -> Result<Worker> {
        self.verify()?;
        Worker::spawn_chart(
            &self.root.join("bin/python"),
            &self.root,
            self.artifact.clone(),
            completion,
        )
    }
}
