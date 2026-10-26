//! Actual sealed minimal Python installation, never a descriptor's assertion.
use crate::{Result, WorkerError};
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
    fn manifest(&self) -> Result<Value> {
        let raw = std::fs::read(self.root.join("algorithm-installation.json"))
            .map_err(|_| WorkerError::Invalid)?;
        if raw.len() > 8 * 1024 * 1024 || hash(&raw) != self.artifact {
            return Err(WorkerError::Invalid);
        }
        serde_json::from_slice(&raw).map_err(|_| WorkerError::Invalid)
    }
    /// Base environment release, checked against the backend at startup.
    pub fn distribution_version(&self) -> Result<String> {
        self.manifest()?["distribution_version"]
            .as_str()
            .map(str::to_owned)
            .ok_or(WorkerError::Invalid)
    }
    /// Exact installed distribution provenance, distinct from the backend release.
    pub fn installed_distribution_version(&self, distribution: &str) -> Result<String> {
        if distribution.is_empty()
            || !distribution
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b == b'-')
        {
            return Err(WorkerError::Invalid);
        }
        let manifest = self.manifest()?;
        let files = manifest["files"].as_object().ok_or(WorkerError::Invalid)?;
        let normalized = distribution.replace('-', "_");
        let prefix = format!("/site-packages/{normalized}-");
        let matches = files
            .iter()
            .filter(|(path, _)| path.contains(&prefix) && path.ends_with(".dist-info/METADATA"))
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return Err(WorkerError::Invalid);
        }
        let (relative, expected) = matches[0];
        if Path::new(relative)
            .components()
            .any(|c| !matches!(c, Component::Normal(_)))
        {
            return Err(WorkerError::Invalid);
        }
        let path = self.root.join(relative);
        let meta = std::fs::symlink_metadata(&path).map_err(|_| WorkerError::Invalid)?;
        if !meta.is_file() || meta.permissions().mode() & 0o222 != 0 || meta.len() > 1024 * 1024 {
            return Err(WorkerError::Invalid);
        }
        let raw = std::fs::read(path).map_err(|_| WorkerError::Invalid)?;
        if raw.len() > 1024 * 1024 || expected.as_str() != Some(hash(&raw).as_str()) {
            return Err(WorkerError::Invalid);
        }
        let metadata = std::str::from_utf8(&raw).map_err(|_| WorkerError::Invalid)?;
        let field = |key: &str| -> Result<&str> {
            let values = metadata
                .lines()
                .take_while(|line| !line.is_empty())
                .filter_map(|line| line.strip_prefix(key))
                .collect::<Vec<_>>();
            if values.len() != 1 || values[0].is_empty() {
                return Err(WorkerError::Invalid);
            }
            Ok(values[0])
        };
        let version = field("Version: ")?;
        if field("Name: ")? != distribution
            || !relative.ends_with(&format!(
                "/site-packages/{normalized}-{version}.dist-info/METADATA"
            ))
        {
            return Err(WorkerError::Invalid);
        }
        Ok(version.to_owned())
    }
    pub fn require_resources(&self, required: &BTreeSet<(String, String)>) -> Result<()> {
        let manifest = self.manifest()?;
        // One request-local manifest observation covers every resource binding.
        // The next pass reads and fingerprints it again; this retains no proof cache.
        let files = manifest["files"].as_object().ok_or(WorkerError::Invalid)?;
        for (relative, digest) in required {
            let suffix = format!("/site-packages/{relative}");
            let matches = files
                .iter()
                .filter(|(name, _)| name.ends_with(&suffix))
                .collect::<Vec<_>>();
            if matches.len() != 1 || matches[0].1.as_str() != Some(digest.as_str()) {
                return Err(WorkerError::Invalid);
            }
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
    pub fn root(&self) -> &Path {
        &self.root
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn resource_pass_checks_every_binding_and_reobserves_manifest() {
        let root = std::env::temp_dir().join(format!(
            "onlyalpha-chart-resource-pass-{}",
            std::process::id()
        ));
        std::fs::create_dir(&root).unwrap();
        struct Cleanup(PathBuf);
        impl Drop for Cleanup {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }
        let _cleanup = Cleanup(root.clone());
        let path = root.join("algorithm-installation.json");
        let bytes = serde_json::to_vec(&json!({"files": {
            "lib/python3.12/site-packages/a.py": "a".repeat(64),
            "lib/python3.12/site-packages/b.py": "b".repeat(64)
        }}))
        .unwrap();
        std::fs::write(&path, &bytes).unwrap();
        let installation = ChartInstallation {
            root,
            artifact: hash(&bytes),
        };
        let bindings = BTreeSet::from([
            ("a.py".to_owned(), "a".repeat(64)),
            ("b.py".to_owned(), "b".repeat(64)),
        ]);
        installation.require_resources(&bindings).unwrap();
        let mut wrong = bindings.clone();
        wrong.insert(("b.py".into(), "c".repeat(64)));
        assert!(installation.require_resources(&wrong).is_err());
        let mut missing = bindings.clone();
        missing.insert(("missing.py".into(), "a".repeat(64)));
        assert!(installation.require_resources(&missing).is_err());
        let ambiguous = serde_json::to_vec(&json!({"files": {
            "lib/python3.12/site-packages/a.py": "a".repeat(64),
            "lib/other/site-packages/a.py": "a".repeat(64),
            "lib/python3.12/site-packages/b.py": "b".repeat(64)
        }}))
        .unwrap();
        std::fs::write(&path, &ambiguous).unwrap();
        let duplicate = ChartInstallation {
            root: installation.root.clone(),
            artifact: hash(&ambiguous),
        };
        assert!(duplicate.require_resources(&bindings).is_err());
        // A successful prior pass cannot authorize changed or unavailable files.
        std::fs::write(&path, b"{}").unwrap();
        assert!(installation.require_resources(&bindings).is_err());
        std::fs::remove_file(&path).unwrap();
        assert!(installation.require_resources(&bindings).is_err());
    }
}

#[cfg(test)]
mod distribution_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn backend_and_provider_versions_use_distinct_sealed_metadata() {
        let root = std::env::temp_dir().join(format!(
            "onlyalpha-distribution-provenance-{}",
            std::process::id()
        ));
        std::fs::create_dir(&root).unwrap();
        let relative =
            "lib/python3.12/site-packages/onlyalpha_plugin_indicators-0.2.0.dist-info/METADATA";
        let metadata =
            b"Metadata-Version: 2.1\nName: onlyalpha-plugin-indicators\nVersion: 0.2.0\n";
        let path = root.join(relative);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, metadata).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o444)).unwrap();
        let mut manifest =
            json!({"distribution_version":"0.7.0", "files":{(relative):hash(metadata)}});
        let seal = |value: &Value| {
            let bytes = serde_json::to_vec(value).unwrap();
            std::fs::write(root.join("algorithm-installation.json"), &bytes).unwrap();
            ChartInstallation {
                root: root.clone(),
                artifact: hash(&bytes),
            }
        };
        let installed = seal(&manifest);
        assert_eq!(installed.distribution_version().unwrap(), "0.7.0");
        assert_eq!(
            installed
                .installed_distribution_version("onlyalpha-plugin-indicators")
                .unwrap(),
            "0.2.0"
        );
        assert!(installed.installed_distribution_version("missing").is_err());
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        std::fs::write(
            &path,
            b"Name: onlyalpha-plugin-indicators\nVersion: 0.3.0\n",
        )
        .unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o444)).unwrap();
        assert!(
            installed
                .installed_distribution_version("onlyalpha-plugin-indicators")
                .is_err()
        );
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        std::fs::write(&path, metadata).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o444)).unwrap();
        let duplicate =
            "lib/python3.12/site-packages/onlyalpha_plugin_indicators-0.3.0.dist-info/METADATA";
        manifest["files"][duplicate] = json!(hash(metadata));
        assert!(
            seal(&manifest)
                .installed_distribution_version("onlyalpha-plugin-indicators")
                .is_err()
        );
        manifest["files"].as_object_mut().unwrap().remove(duplicate);
        let conflicting = b"Name: onlyalpha-plugin-indicators\nVersion: 0.2.0\nVersion: 0.3.0\n";
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
        std::fs::write(&path, conflicting).unwrap();
        std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o444)).unwrap();
        manifest["files"][relative] = json!(hash(conflicting));
        assert!(
            seal(&manifest)
                .installed_distribution_version("onlyalpha-plugin-indicators")
                .is_err()
        );
        std::fs::remove_dir_all(root).unwrap();
    }
}
